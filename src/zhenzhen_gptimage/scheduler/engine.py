"""Durable bounded scheduler; provider performs one remote attempt only."""
from __future__ import annotations
import asyncio
from pathlib import Path
import random
import time
from zhenzhen_gptimage.artifacts.storage import write_response, ResponseWriter
from zhenzhen_gptimage.generation.admission import _finish_thread
from zhenzhen_gptimage.generation.snapshot import RequestSnapshot
from zhenzhen_gptimage.providers.t8_star.client import ProviderError, build_request
from zhenzhen_gptimage.repository.tasks import start_attempt, transition, publish_images, StateConflict
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
                    attempt = await self.worker.run(start_attempt,task_id,row['revision'],_now_ms())
                except StateConflict:
                    continue
                row = await self._row(task_id)
                try:
                    remaining = max(0.0,(row['deadline_at']-_now_ms())/1000)
                    async with asyncio.timeout(remaining):
                        if hasattr(self.provider, 'generate_stream'):
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
            # Do not occupy a generation concurrency slot while processing local output.
            row = await self._row(task_id)
            if row['status'] != 'materializing': return
            try:
                remaining = (row['deadline_at']-_now_ms())/1000
                if remaining <= 0: raise TimeoutError()
                async with asyncio.timeout(remaining):
                    async with self.response_parsing:
                        raw = await _finish_thread(Path(artifact.local_path).read_bytes)
                        images = await self.materializer.materialize(task_id,raw,channel=snapshot.channel,
                            expected_size=None if snapshot.channel=='chat' else (snapshot.width,snapshot.height),
                            deadline=asyncio.get_running_loop().time()+remaining)
                        await self.worker.run(publish_images,task_id,row['revision'],images,_now_ms())
            except asyncio.CancelledError:
                await asyncio.shield(self._mark_recovery(task_id))
                raise
            except Exception:
                await self._mark_recovery(task_id)
            return

    async def _mark_unknown(self, task_id):
        row = await self._row(task_id)
        if row['status']=='submitting':
            await self._transition(row,'unknown',reason='interrupted',attempt_certainty='unknown',error_category='SUBMISSION_UNKNOWN')

    async def _mark_recovery(self, task_id):
        row = await self._row(task_id)
        if row['status']=='materializing':
            await self._transition(row,'recovery_pending',reason='local_failure',error_category='ARTIFACT_UNAVAILABLE')

    async def resume(self):
        rows = await self.worker.run(lambda db: db.execute("SELECT task_id FROM tasks WHERE status IN ('queued','retry_wait') ORDER BY created_at,task_id").fetchall())
        for row in rows: self.kick(row[0])

    async def close(self, grace_seconds=30):
        self.closing = True
        tasks = list(self.inflight.values())
        if not tasks: return
        _, pending = await asyncio.wait(tasks, timeout=min(30,max(0,grace_seconds)))
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
