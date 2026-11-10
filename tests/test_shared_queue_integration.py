"""Cross-process MCP queue evidence with a controlled, non-network provider."""
import asyncio
import base64
from contextlib import AsyncExitStack
from io import BytesIO
import json

import pytest
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from PIL import Image

from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.service import GenerationService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.local_ipc import IPCServer
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler
from zhenzhen_gptimage.providers.t8_star.client import ProviderError


@pytest.mark.asyncio
async def test_shared_capacity_idempotency_and_template_snapshot(tmp_path):
    release, six = asyncio.Event(), asyncio.Event()
    image = BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
    raw = json.dumps({'data': [{'b64_json': base64.b64encode(image.getvalue()).decode()}]}).encode()

    class Provider:
        active = peak = calls = 0
        async def generate(self, snapshot, refs, *, remaining_seconds):
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
            if self.active == 6:
                six.set()
            try:
                await release.wait()
                return raw
            finally:
                self.active -= 1

    worker = DatabaseWorker(tmp_path / 'state.sqlite3')
    limits = Limits(free_disk_bytes=1)
    materializer = ArtifactMaterializer(tmp_path, limits=limits)
    locks, provider = TaskLocks(), Provider()
    scheduler = Scheduler(worker, provider, tmp_path, materializer, task_locks=locks)
    recovery = RecoveryService(worker, materializer, tmp_path, locks)
    admission = Admission(worker, tmp_path, limits)
    backend = ServiceBackend(worker, GenerationService(admission, scheduler), recovery)
    ipc = IPCServer(backend, 'test-token', 'test-identity')
    port = await ipc.start()
    script = tmp_path / 'client_entry.py'
    script.write_text(
        'from types import SimpleNamespace\n'
        'from zhenzhen_gptimage.mcp_api.server import create_server\n'
        'from zhenzhen_gptimage.mcp_api.local_ipc import RemoteBackend\n'
        f'create_server(RemoteBackend(SimpleNamespace(port={port}, token="test-token"), "test-identity")).run(transport="stdio", show_banner=False)\n',
        encoding='utf-8')
    pending = []
    try:
        async with AsyncExitStack() as stack:
            first = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            second = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            saved = await first.call_tool_mcp('save_prompt_template', {
                'code': 'product', 'content': 'Old {{item}}',
                'variables': [{'name': 'item', 'required': True}]})
            assert not saved.isError
            request = {'idempotency_key': 'same', 'family': 'flare', 'width': 32, 'height': 32,
                       'template_code': 'product', 'template_variables': {'item': 'cup'}}
            pending = [asyncio.create_task(client.call_tool_mcp('generate_image', {'request': request}))
                       for client in (first, second)]
            for _ in range(200):
                row = await worker.fetchone("SELECT snapshot_json FROM tasks WHERE idempotency_key='same'")
                if row:
                    break
                await asyncio.sleep(.01)
            assert row is not None
            before = row['snapshot_json']
            changed = await second.call_tool_mcp('save_prompt_template', {
                'code': 'product', 'content': 'New {{item}}', 'expected_version': 1,
                'variables': [{'name': 'item', 'required': True}]})
            assert not changed.isError
            conflict = await first.call_tool_mcp('generate_image', {'request': {**request, 'width': 64}})
            assert conflict.isError and conflict.structuredContent['error']['code'] == 'IDEMPOTENCY_CONFLICT'
            batch = [{'idempotency_key': f'batch-{n}', 'family': 'flare', 'width': 32, 'height': 32,
                      'prompt': 'cup'} for n in range(19)]
            pending.append(asyncio.create_task(second.call_tool_mcp('generate_batch', {'requests': batch})))
            await asyncio.wait_for(six.wait(), 10)
            for _ in range(200):
                count = (await worker.fetchone('SELECT count(*) AS n FROM tasks'))['n']
                if count == 20:
                    break
                await asyncio.sleep(.01)
            assert count == 20 and provider.peak == 6
            overflow = await first.call_tool_mcp('generate_batch', {'requests': [
                {'idempotency_key': 'overflow-a', 'family': 'flare', 'width': 32, 'height': 32, 'prompt': 'x'},
                {'idempotency_key': 'overflow-b', 'family': 'flare', 'width': 32, 'height': 32, 'prompt': 'x'}]})
            assert overflow.isError and overflow.structuredContent['error']['code'] == 'QUEUE_FULL'
            assert (await worker.fetchone('SELECT count(*) AS n FROM tasks'))['n'] == 20
            assert (await worker.fetchone("SELECT snapshot_json FROM tasks WHERE idempotency_key='same'"))['snapshot_json'] == before
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*pending), 30)
            assert all(not result.isError for result in results)
            assert results[0].structuredContent['data']['task_id'] == results[1].structuredContent['data']['task_id']
            assert provider.calls == 20 and provider.peak == 6
    finally:
        release.set()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await ipc.close()
        await scheduler.close()
        await materializer.close()
        await worker.close()


@pytest.mark.asyncio
async def test_backoff_releases_shared_slot_for_another_client(tmp_path, monkeypatch):
    attempts = []
    failed = asyncio.Event()
    image = BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
    raw = json.dumps({'data': [{'b64_json': base64.b64encode(image.getvalue()).decode()}]}).encode()

    class Provider:
        async def generate(self, snapshot, refs, *, remaining_seconds):
            attempts.append(snapshot.prompt)
            if snapshot.prompt == 'first' and attempts.count('first') == 1:
                failed.set()
                raise ProviderError('CONNECT_NOT_SENT', safe_retry=True)
            return raw

    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.random.uniform', lambda a, b: .5)
    worker = DatabaseWorker(tmp_path / 'state.sqlite3')
    limits = Limits(free_disk_bytes=1)
    materializer = ArtifactMaterializer(tmp_path, limits=limits)
    locks = TaskLocks()
    scheduler = Scheduler(worker, Provider(), tmp_path, materializer, concurrency=1, task_locks=locks)
    recovery = RecoveryService(worker, materializer, tmp_path, locks)
    backend = ServiceBackend(worker, GenerationService(Admission(worker, tmp_path, limits), scheduler), recovery)
    ipc = IPCServer(backend, 'token', 'identity')
    port = await ipc.start()
    script = tmp_path / 'client.py'
    script.write_text('from types import SimpleNamespace\n'
        'from zhenzhen_gptimage.mcp_api.server import create_server\n'
        'from zhenzhen_gptimage.mcp_api.local_ipc import RemoteBackend\n'
        f'create_server(RemoteBackend(SimpleNamespace(port={port}, token="token"), "identity")).run(transport="stdio", show_banner=False)\n', encoding='utf-8')
    pending = None
    try:
        async with AsyncExitStack() as stack:
            first = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            second = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            def req(key):
                return {'request': {'idempotency_key': key, 'family': 'flare', 'width': 32,
                                    'height': 32, 'prompt': key}}
            pending = asyncio.create_task(first.call_tool_mcp('generate_image', req('first')))
            await asyncio.wait_for(failed.wait(), 5)
            other = await second.call_tool_mcp('generate_image', req('second'))
            result = await asyncio.wait_for(pending, 5)
            assert not other.isError and not result.isError
            assert attempts == ['first', 'second', 'first']
            assert result.structuredContent['data']['attempt_count'] == 2
    finally:
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await ipc.close()
        await scheduler.close()
        await materializer.close()
        await worker.close()
