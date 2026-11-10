"""Local-only recovery, explicit closure, and bounded previews."""
from __future__ import annotations
import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
import time
from PIL import Image
from .storage import inspect_response
from zhenzhen_gptimage.generation.snapshot import RequestSnapshot
from zhenzhen_gptimage.repository.tasks import StateConflict, transition, publish_images, stage_gif_size_mismatch, accept_pending_gif
from .output import ImageResultError

def _now(): return time.time_ns() // 1_000_000

def _close(db, task_id, expected_status, reason, now):
    if expected_status not in ('unknown', 'recovery_pending') or not 1 <= len(reason) <= 1024:
        raise ValueError('invalid closure')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None: raise KeyError(task_id)
        if row['status'] == 'closed':
            closure = db.execute('SELECT * FROM closure_records WHERE task_id=?', (task_id,)).fetchone()
            if closure is None: raise StateConflict('missing closure record')
            db.commit()
            return dict(row), dict(closure)
        if row['status'] != expected_status: raise StateConflict('task state changed')
        remote=db.execute('SELECT remote_status FROM remote_tasks WHERE task_id=?',(task_id,)).fetchone()
        if remote is not None and remote['remote_status'] not in ('SUCCESS','FAILURE'):
            raise StateConflict('remote task has not reached a terminal state')
        db.execute('INSERT INTO closure_records VALUES (?,?,?,?)', (task_id, row['status'], reason, now))
        db.execute("UPDATE tasks SET status='closed',updated_at=?,revision=revision+1 WHERE task_id=? AND revision=?", (now, task_id, row['revision']))
        db.execute("INSERT INTO task_events(task_id,from_status,to_status,reason_code,created_at) VALUES (?,?,'closed','user_closed',?)", (task_id, row['status'], now))
        result = dict(db.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone())
        closure = dict(db.execute('SELECT * FROM closure_records WHERE task_id=?', (task_id,)).fetchone())
        db.commit()
        return result, closure
    except BaseException:
        db.rollback()
        raise

def _read_image(row, include_preview, max_edge, max_bytes):
    path = Path(row['local_path'])
    if path.is_symlink() or not path.is_file():
        return False, None
    try:
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                size += len(chunk)
                if size > row['bytes']: return False, None
                digest.update(chunk)
        if size != row['bytes'] or digest.hexdigest() != row['sha256']: return False, None
    except OSError:
        return False, None
    if not include_preview: return True, None
    # A preview failure does not invalidate a verified stored original.
    try:
        with Image.open(path) as src:
            src.load()
            image = src.convert('RGB')
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            for quality in (85, 70, 50, 30):
                out = BytesIO()
                image.save(out, format='JPEG', quality=quality)
                if out.tell() <= max_bytes: return True, out.getvalue()
        return True, None
    except (OSError, ValueError, Image.DecompressionBombError):
        return True, None

class RecoveryService:
    def __init__(self, worker, materializer, data_dir: Path, locks):
        self.worker, self.materializer, self.data_dir, self.locks = worker, materializer, data_dir, locks
        self._active_recoveries = {}
        self._closing = False
        self.scheduler = None

    async def _row(self, task_id):
        row = await self.worker.fetchone('SELECT * FROM tasks WHERE task_id=?', (task_id,))
        if row is None: raise KeyError(task_id)
        return dict(row)

    async def startup(self):
        """Classify interrupted operations before the scheduler starts."""
        rows = await self.worker.run(lambda db: db.execute("SELECT task_id FROM tasks WHERE status IN ('submitting','materializing') ORDER BY created_at,task_id").fetchall())
        for item in rows:
            task_id = item['task_id']
            async with self.locks.hold(task_id):
                row = await self._row(task_id)
                if row['status'] == 'submitting':
                    remote = await self.worker.fetchone('SELECT remote_id FROM remote_tasks WHERE task_id=?',(task_id,))
                    artifact = await asyncio.to_thread(inspect_response, self.data_dir, task_id, row['attempt_count'])
                    if artifact is not None:
                        await self.worker.run(lambda db: transition(db, task_id, row['revision'], 'materializing', _now(), reason='recovered_response', response_ref=artifact.local_path, attempt_certainty='response_received'))
                        row = await self._row(task_id)
                    elif remote is not None:
                        continue
                    else:
                        await self.worker.run(lambda db: transition(db, task_id, row['revision'], 'unknown', _now(), reason='interrupted', attempt_certainty='unknown', error_category='SUBMISSION_UNKNOWN'))
                        continue
                if row['status'] == 'materializing':
                    await self.worker.run(lambda db: transition(db, task_id, row['revision'], 'recovery_pending', _now(), reason='startup_recovery', error_category='ARTIFACT_UNAVAILABLE'))

    async def recover(self, task_id):
        if self._closing: raise RuntimeError('recovery service closing')
        row = await self._row(task_id)
        if row['status'] == 'unknown' and self.scheduler is not None:
            return await self.scheduler.recover_remote(task_id)
        active = self._active_recoveries.get(task_id)
        if active is None:
            active = asyncio.create_task(self._recover(task_id))
            self._active_recoveries[task_id] = active
            def forget(done):
                if self._active_recoveries.get(task_id) is done:
                    self._active_recoveries.pop(task_id, None)
                if not done.cancelled():
                    done.exception()
            active.add_done_callback(forget)
        return await asyncio.shield(active)

    async def shutdown(self, grace_seconds=30):
        self._closing = True
        tasks = list(self._active_recoveries.values())
        if not tasks: return
        _, pending = await asyncio.wait(tasks, timeout=min(30, max(0, grace_seconds)))
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)

    async def _recover(self, task_id):
        initial = await self._row(task_id)
        if initial['status'] != 'recovery_pending': raise StateConflict('task is not recoverable')
        async with self.locks.hold(task_id):
            row = await self._row(task_id)
            # An overlapping recovery may have completed while we waited.
            if row['status'] == 'succeeded': return row
            if row['status'] != 'recovery_pending': raise StateConflict('task is not recoverable')
            artifact = await asyncio.to_thread(inspect_response, self.data_dir, task_id, row['attempt_count'])
            if artifact is None or artifact.local_path != row['response_ref']:
                raise StateConflict('complete response evidence unavailable')
            raw = await asyncio.to_thread(Path(artifact.local_path).read_bytes)
            snapshot = RequestSnapshot.model_validate_json(row['snapshot_json'])
            await self.worker.run(lambda db: transition(db, task_id, row['revision'], 'materializing', _now(), reason='local_recovery'))
            row = await self._row(task_id)
            try:
                deadline = asyncio.get_running_loop().time() + 600
                async with asyncio.timeout_at(deadline):
                    expected = None if snapshot.channel=='chat' or snapshot.size is not None else (snapshot.width,snapshot.height)
                    kwargs = {} if snapshot.output_format is None else {'expected_format':snapshot.output_format,
                        'accept_actual_size':snapshot.size_policy=='accept_actual'}
                    if snapshot.size and ':' in snapshot.size:
                        kwargs['expected_ratio']=tuple(map(int,snapshot.size.split(':')))
                    if snapshot.output_format=='gif':
                        kwargs.update(expected_frame_count=snapshot.frame_count,expected_frame_duration_ms=snapshot.frame_duration_ms)
                    images = await self.materializer.materialize(task_id, raw, channel=snapshot.channel,
                        expected_size=expected, deadline=deadline, **kwargs)
                    await self.worker.run(publish_images, task_id, row['revision'], images, _now())
            except ImageResultError as exc:
                if snapshot.output_format=='gif' and exc.artifacts:
                    await self.worker.run(stage_gif_size_mismatch,task_id,row['revision'],exc.artifacts,_now())
                    return await self._row(task_id)
                current = await self._row(task_id)
                if current['status'] == 'materializing':
                    await self.worker.run(lambda db: transition(db,task_id,current['revision'],'recovery_pending',_now(),reason='local_failure',error_category='ARTIFACT_UNAVAILABLE'))
                raise
            except BaseException:
                current = await self._row(task_id)
                if current['status'] == 'materializing':
                    await asyncio.shield(self.worker.run(lambda db: transition(db, task_id, current['revision'], 'recovery_pending', _now(), reason='local_failure', error_category='ARTIFACT_UNAVAILABLE')))
                raise
            return await self._row(task_id)

    async def close(self, task_id, expected_status, reason):
        async with self.locks.hold(task_id):
            return await self.worker.run(_close, task_id, expected_status, reason, _now())

    async def accept_gif_size(self, task_id, sha256, width, height):
        async with self.locks.hold(task_id):
            existing=await self.worker.fetchone('SELECT * FROM image_acceptance_records WHERE task_id=?',(task_id,))
            if existing is None:
                row=await self.worker.fetchone('SELECT * FROM pending_image_artifacts WHERE task_id=? AND image_index=0',(task_id,))
                if row is None or (row['sha256'],row['width'],row['height'])!=(sha256,width,height):
                    raise StateConflict('pending image differs')
                available,_=await asyncio.to_thread(_read_image,dict(row),False,1,1)
                if not available: raise StateConflict('pending file unavailable')
            await self.worker.run(accept_pending_gif,task_id,sha256,width,height,_now())
            return await self._row(task_id)

    async def image(self, task_id, index=0, include_preview=True):
        # A concurrent cleanup must not remove the original mid-read. If the
        # caller cancels, keep the lock until the worker thread has finished.
        from zhenzhen_gptimage.generation.admission import _finish_thread
        async with self.locks.hold(task_id):
            row = await self.worker.fetchone('SELECT * FROM image_artifacts WHERE task_id=? AND image_index=?', (task_id, index))
            if row is None: raise KeyError((task_id, index))
            result = dict(row)
            limits = self.materializer.limits
            # MCP image content is base64 encoded; budget the encoded representation.
            raw_limit = (limits.preview_bytes // 4) * 3
            available, preview = await _finish_thread(_read_image, result, include_preview, limits.preview_long_edge, raw_limit)
            result['available'] = available
            return result, preview
