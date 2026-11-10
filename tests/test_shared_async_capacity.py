"""Remote uncertainty and recovery across independent stdio frontends."""
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
from zhenzhen_gptimage.providers.t8_star.client import ProviderError
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler


def gif():
    data = BytesIO()
    frames = [Image.new('RGB', (512, 512), color) for color in ('red', 'blue')]
    frames[0].save(data, format='GIF', save_all=True, append_images=frames[1:], duration=200, loop=0)
    return data.getvalue()


class Provider:
    def __init__(self, unknown=False):
        self.unknown = unknown
        self.submissions = []
        self.polls = []
        self.poll_started = asyncio.Event()
        self.release = asyncio.Event()

    async def submit_async(self, snapshot, *, remaining_seconds):
        self.submissions.append(snapshot.prompt)
        if self.unknown:
            raise ProviderError('SUBMISSION_UNKNOWN')
        return 'remote-one'

    async def query_async(self, remote_id, *, remaining_seconds):
        self.polls.append(remote_id)
        self.poll_started.set()
        await self.release.wait()
        return 'SUCCESS', json.dumps({'data': [{'b64_json': base64.b64encode(gif()).decode()}]}).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize('unknown', [False, True])
async def test_remote_id_and_uncertain_submission_across_clients(tmp_path, unknown):
    worker = DatabaseWorker(tmp_path / 'state.sqlite3')
    limits = Limits(free_disk_bytes=1)
    materializer = ArtifactMaterializer(tmp_path, limits=limits)
    locks, provider = TaskLocks(), Provider(unknown)
    scheduler = Scheduler(worker, provider, tmp_path, materializer, concurrency=1, task_locks=locks)
    recovery = RecoveryService(worker, materializer, tmp_path, locks)
    recovery.scheduler = scheduler
    backend = ServiceBackend(worker, GenerationService(Admission(worker, tmp_path, limits), scheduler), recovery)
    ipc = IPCServer(backend, 'test-token', 'identity')
    port = await ipc.start()
    script = tmp_path / 'client_entry.py'
    script.write_text('from types import SimpleNamespace\n'
        'from zhenzhen_gptimage.mcp_api.server import create_server\n'
        'from zhenzhen_gptimage.mcp_api.local_ipc import RemoteBackend\n'
        f'create_server(RemoteBackend(SimpleNamespace(port={port}, token="test-token"), "identity")).run(transport="stdio", show_banner=False)\n', encoding='utf-8')
    base = {'family': 'flare', 'width': 512, 'height': 512, 'output_format': 'gif',
            'execution_mode': 'async'}
    try:
        async with AsyncExitStack() as stack:
            first = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            second = await stack.enter_async_context(Client(PythonStdioTransport(script)))
            response = await first.call_tool_mcp('generate_image', {'request': {
                **base, 'idempotency_key': 'one', 'prompt': 'first'}})
            task_id = response.structuredContent['data']['task_id']
            if unknown:
                for _ in range(200):
                    row = await scheduler._row(task_id)
                    if row['status'] == 'unknown':
                        break
                    await asyncio.sleep(.01)
                assert row['status'] == 'unknown'
                other = await second.call_tool_mcp('generate_image', {'request': {
                    **base, 'idempotency_key': 'two', 'prompt': 'second'}})
                await asyncio.sleep(.2)
                assert (await scheduler._row(other.structuredContent['data']['task_id']))['status'] == 'queued'
                assert provider.submissions == ['first']
            else:
                await asyncio.wait_for(provider.poll_started.wait(), 5)
                view = await second.call_tool_mcp('get_task', {'task_id': task_id})
                assert view.structuredContent['data']['remote_task']['remote_id'] == 'remote-one'
                await scheduler.close(grace_seconds=0)
                await recovery.startup()
                replacement = Scheduler(worker, provider, tmp_path, materializer, concurrency=1, task_locks=locks)
                backend.generation.scheduler = replacement
                recovery.scheduler = replacement
                scheduler = replacement
                provider.release.set()
                await scheduler.resume()
                await asyncio.wait_for(scheduler.inflight[task_id], 5)
                view = await second.call_tool_mcp('get_task', {'task_id': task_id})
                assert view.structuredContent['data']['status'] == 'succeeded'
                assert view.structuredContent['data']['attempt_count'] == 1
                assert provider.submissions == ['first'] and all(x == 'remote-one' for x in provider.polls)
    finally:
        provider.release.set()
        await ipc.close()
        await scheduler.close(grace_seconds=0)
        await materializer.close()
        await worker.close()
