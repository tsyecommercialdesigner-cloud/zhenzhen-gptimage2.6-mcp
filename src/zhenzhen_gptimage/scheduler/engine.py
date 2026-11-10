"""Durable bounded scheduler; provider performs one remote attempt only."""
from __future__ import annotations
import asyncio
from pathlib import Path
import random
import time
from zhenzhen_gptimage.artifacts.storage import write_response, inspect_response, ResponseWriter
from zhenzhen_gptimage.generation.admission import _finish_thread
from zhenzhen_gptimage.generation.snapshot import RequestSnapshot
from zhenzhen_gptimage.providers.t8_star.client import ProviderError, build_request
from zhenzhen_gptimage.repository.tasks import start_attempt, transition, publish_images, stage_gif_size_mismatch, record_remote_task, StateConflict, RemoteCapacityBusy
from zhenzhen_gptimage.artifacts.output import ImageResultError
from zhenzhen_gptimage.generation.task_locks import TaskLocks

def _now_ms(): return time.time_ns() // 1_000_000

def retry_delay(attempt: int, retry_after_seconds=None) -> float:
    if attempt not in (1, 2):
        raise ValueError('only the first two attempts may be retried')
    delay = random.uniform(1, 2) * (2 ** (attempt - 1))
    if isinstance(retry_after_seconds, (int, float)) and not isinstance(retry_after_seconds, bool) and retry_after_seconds >= 0:
        delay = max(delay, retry_after_seconds)
    return delay

class Scheduler:
    def __init__(self, worker, provider, data_dir: Path, materializer, *, concurrency=6, response_limit=64*1024*1024, task_locks=None):
        if not 1 <= concurrency <= 6: raise ValueError('invalid concurrency')
        self.worker, self.provider, self.data_dir, self.materializer = worker, provider, data_dir, materializer
        self.semaphore = asyncio.Semaphore(concurrency)
        self.concurrency = concurrency
        self.response_limit = response_limit
        self.inflight = {}
        self.no_retry = set()
        self.closing = False
        self.task_locks = task_locks if task_locks is not None else TaskLocks()
        # Bound in-memory JSON/Base64 parsing independently of paid submissions.
        self.response_parsing = asyncio.Semaphore(1)

    async def _row(self, task_id):
        row = await self.worker.fetchone('SELECT * FROM tasks WHERE task_id=?', (task_id,))
        if row is None: raise KeyError(task_id)
        return dict(row)

    def kick(self, task_id):
        if self.closing: raise RuntimeError('scheduler closing')
        task = self.inflight.get(task_id)
        if task is None or task.done():
            task = asyncio.create_task(self._run_until_deadline(task_id))
            self.inflight[task_id] = task
            def forget(done):
                if self.inflight.get(task_id) is done: self.inflight.pop(task_id, None)
                if not done.cancelled(): done.exception()  # consume background exceptions
            task.add_done_callback(forget)
        return task

    async def _run_until_deadline(self, task_id):
        row = await self._row(task_id)
        remaining = max(0.0, (row['deadline_at'] - _now_ms()) / 1000)
        try:
            async with asyncio.timeout(remaining):
                async with self.task_locks.hold(task_id):
                    await self._execute(task_id)
        except TimeoutError:
            row = await self._row(task_id)
            if row['status'] in ('queued','retry_wait'):
                await self._transition(row,'expired',reason='deadline')
            elif row['status'] == 'submitting':
                await self._mark_unknown(task_id)
            elif row['status'] == 'materializing':
                await self._mark_recovery(task_id)

    async def wait(self, task_id):
        # Cancellation of one waiting Host must not cancel shared job execution.
        try:
            await asyncio.shield(self.kick(task_id))
        except asyncio.CancelledError:
            # Do not start a further paid attempt after a client cancels.
            self.no_retry.add(task_id)
            raise
        return await self._row(task_id)

    async def _transition(self, row, target, **kwargs):
        await self.worker.run(lambda db: transition(db,row['task_id'],row['revision'],target,_now_ms(),**kwargs))

    async def _execute(self, task_id):
        while not self.closing:
            row = await self._row(task_id)
            if row['status'] in ('submitting','unknown'):
                remote = await self.worker.fetchone('SELECT remote_id FROM remote_tasks WHERE task_id=?',(task_id,))
                if remote is not None:
                    async with self.semaphore:
                        artifact = await self._poll_remote(task_id, remote['remote_id'], row['deadline_at'])
                    if artifact is not None:
                        await self._materialize(task_id, artifact, row['deadline_at'])
                return
            if row['status'] not in ('queued','retry_wait'): return
            now = _now_ms()
            if task_id in self.no_retry:
                await self._transition(row,'cancelled',reason='client_cancelled')
                return
            if now >= row['deadline_at']:
                await self._transition(row,'expired',reason='deadline')
                return
            if row['status'] == 'retry_wait' and row['next_attempt_at'] > now:
                await asyncio.sleep(min((row['next_attempt_at']-now)/1000, (row['deadline_at']-now)/1000))
                continue
            async with self.semaphore:
                row = await self._row(task_id)
                if row['status'] not in ('queued','retry_wait'): return
                if task_id in self.no_retry or self.closing:
                    await self._transition(row,'cancelled',reason='client_cancelled' if task_id in self.no_retry else 'shutdown')
                    return
                now = _now_ms()
                if now >= row['deadline_at']:
                    await self._transition(row,'expired',reason='deadline')
                    return
                try:
                    snapshot = RequestSnapshot.model_validate_json(row['snapshot_json'])
                    refs = await self.worker.run(lambda db: db.execute('SELECT local_path FROM reference_assets WHERE task_id=? ORDER BY input_index',(task_id,)).fetchall())
                    reference_bytes = await asyncio.to_thread(lambda: tuple(Path(r[0]).read_bytes() for r in refs))
                    # Validate local encoding and frozen hashes before marking a paid attempt.
                    build_request(snapshot, reference_bytes)
                except (ValueError, OSError):
                    await self._transition(row,'failed',reason='invalid_local_input',error_category='INVALID_ARGUMENT')
                    return
                # The Host may have cancelled while reference files were read.
                if task_id in self.no_retry or self.closing:
                    row = await self._row(task_id)
                    await self._transition(row,'cancelled',reason='client_cancelled' if task_id in self.no_retry else 'shutdown')
                    return
                try:
                    attempt = await self.worker.run(lambda db: start_attempt(db,task_id,row['revision'],_now_ms(),concurrency=self.concurrency))
                except RemoteCapacityBusy:
                    await asyncio.sleep(0.25)
                    continue
                except StateConflict:
                    continue
                row = await self._row(task_id)
                try:
                    remaining = max(0.0,(row['deadline_at']-_now_ms())/1000)
                    async with asyncio.timeout(remaining):
                        if snapshot.execution_mode == 'async':
                            remote_id = await self.provider.submit_async(snapshot,remaining_seconds=remaining)
                            await asyncio.shield(self.worker.run(record_remote_task,task_id,row['revision'],remote_id,_now_ms()))
                            artifact = await self._poll_remote(task_id,remote_id,row['deadline_at'])
                            if artifact is None: return
                        elif hasattr(self.provider, 'generate_stream'):
                            writer = await _finish_thread(ResponseWriter, self.data_dir, task_id, attempt, self.response_limit)
                            try:
                                async def write_chunk(chunk):
                                    await _finish_thread(writer.write, chunk)
                                await self.provider.generate_stream(snapshot, reference_bytes, remaining_seconds=remaining, write_chunk=write_chunk)
                                artifact = await _finish_thread(writer.finish)
                            finally:
                                await _finish_thread(writer.abort)
                        else:
                            # Isolated test adapters may return a complete bounded response.
                            raw = await self.provider.generate(snapshot,reference_bytes,remaining_seconds=remaining)
                            artifact = await _finish_thread(write_response,self.data_dir,task_id,attempt,[raw],max_bytes=self.response_limit)
                        if snapshot.execution_mode != 'async':
                            await self._transition(row,'materializing',reason='response_received',response_ref=artifact.local_path,
                                attempt_certainty='response_received',http_status=200)
                except asyncio.CancelledError:
                    await asyncio.shield(self._mark_unknown(task_id))
                    raise
                except ProviderError as exc:
                    row = await self._row(task_id)
                    if exc.safe_retry and attempt < 3 and not self.closing and task_id not in self.no_retry:
                        retry_after = getattr(exc, 'retry_after_seconds', None)
                        delay = retry_delay(attempt, retry_after)
                        next_at = _now_ms()+int(delay*1000)
                        if next_at < row['deadline_at']:
                            await self._transition(row,'retry_wait',reason=exc.category,next_attempt_at=next_at,
                                attempt_certainty='not_sent',error_category=exc.category,http_status=exc.status)
                            continue
                    target = 'failed' if exc.safe_retry or exc.category in ('PROVIDER_REJECTED','CONFIG_ERROR') else 'unknown'
                    certainty = 'not_sent' if exc.safe_retry else 'rejected' if target == 'failed' else 'unknown'
                    await self._transition(row,target,reason=exc.category,attempt_certainty=certainty,error_category=exc.category,http_status=exc.status)
                    return
                except (TimeoutError, OSError, ValueError):
                    await self._mark_unknown(task_id)
                    return
            await self._materialize(task_id,artifact,row['deadline_at'])
            return

    async def _materialize(self, task_id, artifact, deadline_at):
            row = await self._row(task_id)
            if row['status'] != 'materializing': return
            snapshot = RequestSnapshot.model_validate_json(row['snapshot_json'])
            try:
                remaining = (deadline_at-_now_ms())/1000
                if remaining <= 0: raise TimeoutError()
                async with asyncio.timeout(remaining):
                    async with self.response_parsing:
                        raw = await _finish_thread(Path(artifact.local_path).read_bytes)
                        expected = None if snapshot.channel=='chat' or snapshot.size is not None else (snapshot.width,snapshot.height)
                        kwargs = {} if snapshot.output_format is None else {'expected_format':snapshot.output_format,
                            'accept_actual_size':snapshot.size_policy=='accept_actual'}
                        if snapshot.size and ':' in snapshot.size:
                            kwargs['expected_ratio']=tuple(map(int,snapshot.size.split(':')))
                        if snapshot.output_format=='gif':
                            kwargs.update(expected_frame_count=snapshot.frame_count,expected_frame_duration_ms=snapshot.frame_duration_ms)
                        images = await self.materializer.materialize(task_id,raw,channel=snapshot.channel,
                            expected_size=expected, deadline=asyncio.get_running_loop().time()+remaining, **kwargs)
                        await self.worker.run(publish_images,task_id,row['revision'],images,_now_ms())
            except asyncio.CancelledError:
                await asyncio.shield(self._mark_recovery(task_id))
                raise
            except ImageResultError as exc:
                if snapshot.output_format=='gif' and exc.artifacts:
                    await self.worker.run(stage_gif_size_mismatch,task_id,row['revision'],exc.artifacts,_now_ms())
                else:
                    await self._mark_recovery(task_id)
            except Exception:
                await self._mark_recovery(task_id)
            return

    async def _poll_remote(self, task_id, remote_id, deadline_at):
        while not self.closing and _now_ms() < deadline_at:
            remaining=(deadline_at-_now_ms())/1000
            try:
                status, raw=await self.provider.query_async(remote_id,remaining_seconds=remaining)
            except ProviderError:
                await asyncio.sleep(min(3,max(0,remaining)))
                continue
            await self.worker.run(lambda db: db.execute('UPDATE remote_tasks SET remote_status=?,updated_at=? WHERE task_id=? AND remote_id=?',(status,_now_ms(),task_id,remote_id)))
            if status == 'FAILURE':
                row=await self._row(task_id)
                await self._transition(row,'failed',reason='remote_failed',error_category='PROVIDER_REJECTED',
                    **({'attempt_certainty':'response_received'} if row['status']=='submitting' else {}))
                return None
            if status == 'SUCCESS':
                row=await self._row(task_id)
                artifact=await _finish_thread(inspect_response,self.data_dir,task_id,row['attempt_count'])
                if artifact is None:
                    artifact=await _finish_thread(write_response,self.data_dir,task_id,row['attempt_count'],[raw],max_bytes=self.response_limit)
                await self._transition(row,'materializing',reason='remote_success',response_ref=artifact.local_path,
                    **({'attempt_certainty':'response_received','http_status':200} if row['status']=='submitting' else {}))
                return artifact
            await asyncio.sleep(min(3,max(0,remaining)))
        return None

    async def recover_remote(self, task_id):
        async with self.task_locks.hold(task_id):
            row=await self._row(task_id)
            remote=await self.worker.fetchone('SELECT remote_id FROM remote_tasks WHERE task_id=?',(task_id,))
            if row['status']!='unknown' or remote is None: raise StateConflict('no recoverable remote task')
            deadline=_now_ms()+600000
            async with self.semaphore:
                artifact=await self._poll_remote(task_id,remote['remote_id'],deadline)
            if artifact is not None: await self._materialize(task_id,artifact,deadline)
            return await self._row(task_id)

    async def _mark_unknown(self, task_id):
        row = await self._row(task_id)
        if row['status']=='submitting':
            await self._transition(row,'unknown',reason='interrupted',attempt_certainty='unknown',error_category='SUBMISSION_UNKNOWN')

    async def _mark_recovery(self, task_id):
        row = await self._row(task_id)
        if row['status']=='materializing':
            await self._transition(row,'recovery_pending',reason='local_failure',error_category='ARTIFACT_UNAVAILABLE')

    async def resume(self):
        rows = await self.worker.run(lambda db: db.execute("SELECT t.task_id FROM tasks t LEFT JOIN remote_tasks r ON r.task_id=t.task_id WHERE t.status IN ('queued','retry_wait') OR (t.status IN ('submitting','unknown') AND r.remote_id IS NOT NULL AND t.deadline_at>?) ORDER BY t.created_at,t.task_id",(_now_ms(),)).fetchall())
        for row in rows: self.kick(row[0])

    async def close(self, grace_seconds=30):
        self.closing = True
        tasks = list(self.inflight.values())
        if not tasks: return
        _, pending = await asyncio.wait(tasks, timeout=min(30,max(0,grace_seconds)))
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
