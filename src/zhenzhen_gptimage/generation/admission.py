"""Serialize snapshot preparation, admission, and staging cleanup."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
from pathlib import Path
from zhenzhen_gptimage.artifacts.storage import prepare_references, cleanup_unreferenced, check_disk_budget
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.snapshot import create_snapshot, input_digest, IdempotencyConflict
from zhenzhen_gptimage.prompts.templates import get_template, render_template
from zhenzhen_gptimage.repository.tasks import accept_batch

async def _finish_thread(func, *args, **kwargs):
    # Cancellation cannot release the admission lock while a disk operation is running.
    future = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        await future
        raise

class Admission:
    def __init__(self, worker, data_dir: Path, limits: Limits = Limits()):
        self.worker = worker
        self.data_dir = data_dir
        self.limits = limits
        self.lock = asyncio.Lock()
        self._stopping = False

    async def stop(self):
        """Reject future admissions and wait for any transaction already in flight."""
        self._stopping = True
        async with self.lock:
            pass

    async def _cleanup(self):
        rows = await self.worker.run(lambda db: db.execute('SELECT local_path FROM reference_assets').fetchall())
        await _finish_thread(cleanup_unreferenced, self.data_dir, {row[0] for row in rows})

    async def submit(self, requests, now_ms: int):
        if self._stopping:
            raise RuntimeError('admission is stopping')
        if not 1 <= len(requests) <= 20:
            raise ValueError('invalid batch size')
        async with self.lock:
            if self._stopping:
                raise RuntimeError('admission is stopping')
            snapshots = []
            assets = []
            seen = {}
            try:
                for request in requests:
                    digest = input_digest(request)
                    key = request.idempotency_key
                    if key in seen:
                        if seen[key] != digest:
                            raise IdempotencyConflict(key)
                        snapshots.append(None); assets.append(None)
                        continue
                    seen[key] = digest
                    existing = await self.worker.fetchone('SELECT input_digest FROM tasks WHERE idempotency_key=?', (key,))
                    if existing is not None:
                        if existing[0] != digest:
                            raise IdempotencyConflict(key)
                        snapshots.append(None); assets.append(None)
                        continue
                    if request.template_code:
                        template = await self.worker.run(get_template, request.template_code)
                        if template is None:
                            raise ValueError('template not found')
                        rendered = render_template(template, request.template_variables or {})
                        prompt, version = rendered['prompt'], rendered['version']
                    else:
                        prompt, version = request.prompt, None
                    outstanding = await self.worker.fetchone("SELECT count(*) FROM tasks WHERE status IN ('queued','submitting','retry_wait','materializing','recovery_pending','unknown')")
                    prospective = sum(item is not None for item in snapshots) + 1
                    await _finish_thread(check_disk_budget, self.data_dir,
                        (outstanding[0] + prospective) * self.limits.output_total_bytes, self.limits)
                    refs = await _finish_thread(prepare_references,
                        [Path(ref.local_path) for ref in request.references], self.data_dir, self.limits)
                    if any(ref.mime_type != 'image/png' for ref in refs):
                        raise ValueError('only PNG references are supported by the provider')
                    snapshots.append(create_snapshot(request, final_prompt=prompt,
                        reference_hashes=tuple(ref.sha256 for ref in refs), template_version=version))
                    assets.append([asdict(ref) for ref in refs])
                # Shield commit: cancellation cannot leave cleanup racing an in-flight DB transaction.
                future = asyncio.create_task(self.worker.run(lambda db: accept_batch(db, requests, snapshots, now_ms,
                    capacity=self.limits.max_unfinished, assets=assets)))
                try:
                    return await asyncio.shield(future)
                except asyncio.CancelledError:
                    await future
                    raise
            finally:
                await self._cleanup()
