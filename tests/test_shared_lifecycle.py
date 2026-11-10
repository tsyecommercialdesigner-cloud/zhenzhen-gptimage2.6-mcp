import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zhenzhen_gptimage.bootstrap.config import RuntimeConfig
from zhenzhen_gptimage.mcp_api.backend_control import request_stop
from zhenzhen_gptimage.mcp_api.discovery import read_endpoint
from zhenzhen_gptimage.mcp_api.local_ipc import connect, read_frame, write_frame
from zhenzhen_gptimage.mcp_api.shared_process import serve_owned_backend


@pytest.mark.asyncio
async def test_idle_exit_waits_for_connections_and_unfinished_tasks(tmp_path):
    state = {'outstanding': 1}
    class Worker:
        async def fetchone(self, query):
            return {'n': state['outstanding']}
    backend = SimpleNamespace(worker=Worker())
    config = RuntimeConfig(env_file=tmp_path / '.env', data_dir=tmp_path,
                           api_key='test-only', secret_source='test')
    task = asyncio.create_task(serve_owned_backend(config, tmp_path, backend, idle_seconds=.1))
    endpoint = None
    try:
        for _ in range(100):
            endpoint = read_endpoint(tmp_path)
            if endpoint:
                break
            await asyncio.sleep(.02)
        assert endpoint is not None
        reader, writer = await connect(endpoint, endpoint.identity)
        await write_frame(writer, {'op': 'hold'}, timeout=5)
        assert (await read_frame(reader, timeout=5))['status'] == 'held'
        await asyncio.sleep(1.2)
        assert not task.done()
        state['outstanding'] = 0
        await asyncio.sleep(1.2)
        assert not task.done()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(task, 4)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_management_stop_is_authenticated_and_orderly(tmp_path):
    class Worker:
        async def fetchone(self, query):
            return {'n': 0}
    config = RuntimeConfig(env_file=tmp_path / '.env', data_dir=tmp_path,
                           api_key='test-only', secret_source='test')
    task = asyncio.create_task(serve_owned_backend(config, tmp_path, SimpleNamespace(worker=Worker())))
    try:
        for _ in range(100):
            endpoint = read_endpoint(tmp_path)
            if endpoint:
                break
            await asyncio.sleep(.02)
        assert endpoint is not None
        assert await request_stop(endpoint, endpoint.identity)
        await asyncio.wait_for(task, 3)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
