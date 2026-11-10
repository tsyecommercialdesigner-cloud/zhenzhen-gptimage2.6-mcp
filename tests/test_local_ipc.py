import asyncio
import struct
from types import SimpleNamespace

import pytest

from zhenzhen_gptimage.mcp_api.local_ipc import (
    IPCError, IPCIncompatible, IPCOutcomeUnknown, IPCServer, RemoteBackend, connect, read_frame,
    write_frame, HANDSHAKE_TIMEOUT, MAX_FRAME, configuration_identity,
)
from zhenzhen_gptimage.bootstrap.config import RuntimeConfig


class FakeBackend:
    def __init__(self):
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        return {'ok': True, 'data': args, 'error': None, 'warnings': [], '_preview': b'preview'}


def test_configuration_identity_changes_without_revealing_secrets(tmp_path):
    first = RuntimeConfig(data_dir=tmp_path, env_file=tmp_path / '.env',
                          api_key='test-secret-one', secret_source='test')
    second = RuntimeConfig(data_dir=tmp_path, env_file=tmp_path / '.env',
                           api_key='test-secret-two', secret_source='test')
    left = configuration_identity(first, tmp_path, 'random-token', '0.1.1')
    right = configuration_identity(second, tmp_path, 'random-token', '0.1.1')
    assert left != right
    assert 'test-secret' not in left + right
    assert left != configuration_identity(first, tmp_path, 'random-token', '0.1.2')


@pytest.mark.asyncio
async def test_authenticated_transport_preserves_result_and_binary_preview():
    backend = FakeBackend()
    server = IPCServer(backend, 'secret-token', 'configuration')
    port = await server.start()
    endpoint = SimpleNamespace(port=port, token='secret-token')
    try:
        result = await RemoteBackend(endpoint, 'configuration').call('example', {'value': 'yes'})
        assert result['_preview'] == b'preview'
        assert result['data'] == {'value': 'yes'}
        assert backend.calls == [('example', {'value': 'yes'})]
        with pytest.raises(IPCIncompatible):
            await connect(endpoint, 'other-config')
        with pytest.raises(IPCError):
            await connect(SimpleNamespace(port=port, token='incorrect'), 'configuration')
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_absent_token_never_reaches_backend():
    backend = FakeBackend()
    server = IPCServer(backend, 'secret-token', 'configuration')
    port = await server.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        await write_frame(writer, {'identity': 'configuration', 'protocol': 1}, timeout=HANDSHAKE_TIMEOUT)
        with pytest.raises(IPCError):
            await read_frame(reader, timeout=HANDSHAKE_TIMEOUT)
        writer.close()
        await writer.wait_closed()
        assert backend.calls == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_protocol_mismatch_is_rejected_without_logging_token(capsys):
    backend = FakeBackend()
    server = IPCServer(backend, 'private-token-value', 'configuration')
    port = await server.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        await write_frame(writer, {'identity': 'configuration', 'protocol': 999,
                                   'token': 'private-token-value'}, timeout=5)
        assert (await read_frame(reader, timeout=5))['status'] == 'incompatible'
        writer.close()
        await writer.wait_closed()
        assert not backend.calls
        output = capsys.readouterr()
        assert 'private-token-value' not in output.out + output.err
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_accepted_backend_call():
    accepted, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowBackend:
        async def call(self, name, args):
            accepted.set()
            await release.wait()
            finished.set()
            return {'ok': True, 'data': {}, 'error': None}

    server = IPCServer(SlowBackend(), 'secret-token', 'configuration')
    port = await server.start()
    try:
        reader, writer = await connect(SimpleNamespace(port=port, token='secret-token'), 'configuration')
        await write_frame(writer, {'op': 'call', 'name': 'generate_image', 'args': {}}, timeout=5)
        await asyncio.wait_for(accepted.wait(), 2)
        writer.close()
        await writer.wait_closed()
        release.set()
        await asyncio.wait_for(finished.wait(), 2)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_explicit_cancel_reaches_waiting_business_call():
    started, cancelled = asyncio.Event(), asyncio.Event()

    class SlowBackend:
        async def call(self, name, args):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    server = IPCServer(SlowBackend(), 'token', 'configuration')
    port = await server.start()
    call = asyncio.create_task(RemoteBackend(SimpleNamespace(port=port, token='token'),
                                             'configuration').call('generate_image', {}))
    try:
        await asyncio.wait_for(started.wait(), 2)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(cancelled.wait(), 2)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_oversized_and_incomplete_frames_are_rejected():
    backend = FakeBackend()
    server = IPCServer(backend, 'token', 'configuration')
    port = await server.start()
    try:
        for payload in (struct.pack('!I', MAX_FRAME + 1), struct.pack('!I', 10) + b'{}'):
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(payload)
            await writer.drain()
            if len(payload) > 4:
                writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 2) == b''
            writer.close()
            await writer.wait_closed()
        assert backend.calls == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_connection_limit_rejects_extra_client():
    backend = FakeBackend()
    server = IPCServer(backend, 'token', 'configuration', max_connections=1)
    port = await server.start()
    first = second = None
    try:
        reader, first = await connect(SimpleNamespace(port=port, token='token'), 'configuration')
        await write_frame(first, {'op': 'hold'}, timeout=5)
        assert (await read_frame(reader, timeout=5))['status'] == 'held'
        second_reader, second = await asyncio.open_connection('127.0.0.1', port)
        assert await asyncio.wait_for(second_reader.read(), 2) == b''
    finally:
        for writer in (first, second):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_idle_unauthenticated_connection_times_out(monkeypatch):
    import zhenzhen_gptimage.mcp_api.local_ipc as ipc
    monkeypatch.setattr(ipc, 'HANDSHAKE_TIMEOUT', .1)
    server = IPCServer(FakeBackend(), 'token', 'configuration')
    port = await server.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        assert await asyncio.wait_for(reader.read(), 2) == b''
        writer.close()
        await writer.wait_closed()
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,expected', [('before_accept', 0), ('after_accept', 1), ('before_response', 1)])
async def test_interrupted_calls_are_never_replayed(stage, expected):
    submissions = []

    async def peer(reader, writer):
        try:
            await read_frame(reader, timeout=5)
            await write_frame(writer, {'status': 'ready'}, timeout=5)
            if stage == 'before_accept':
                return
            request = await read_frame(reader, timeout=5)
            submissions.append(request['args']['request']['idempotency_key'])
            if stage == 'before_response':
                await asyncio.sleep(.01)  # emulate completed work before dropping the reply
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(IPCOutcomeUnknown):
            await RemoteBackend(SimpleNamespace(port=port, token='token'), 'config').call(
                'generate_image', {'request': {'idempotency_key': 'one'}})
        await asyncio.sleep(.05)
        assert len(submissions) == expected
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_disconnected_generation_is_queryable_without_resubmission(tmp_path):
    import base64
    import json
    from io import BytesIO
    from PIL import Image
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.bootstrap.config import Limits
    from zhenzhen_gptimage.generation.admission import Admission
    from zhenzhen_gptimage.generation.service import GenerationService
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
    from zhenzhen_gptimage.repository.worker import DatabaseWorker
    from zhenzhen_gptimage.scheduler.engine import Scheduler

    started, release = asyncio.Event(), asyncio.Event()
    raw = BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(raw, 'PNG')
    class Provider:
        calls = 0
        async def generate(self, snapshot, refs, *, remaining_seconds):
            self.calls += 1
            started.set()
            await release.wait()
            return json.dumps({'data': [{'b64_json': base64.b64encode(raw.getvalue()).decode()}]}).encode()

    worker = DatabaseWorker(tmp_path / 'state.sqlite3')
    limits = Limits(free_disk_bytes=1)
    materializer = ArtifactMaterializer(tmp_path, limits=limits)
    locks, provider = TaskLocks(), Provider()
    scheduler = Scheduler(worker, provider, tmp_path, materializer, task_locks=locks)
    recovery = RecoveryService(worker, materializer, tmp_path, locks)
    admission = Admission(worker, tmp_path, limits)
    backend = ServiceBackend(worker, GenerationService(admission, scheduler), recovery)
    server = IPCServer(backend, 'token', 'config')
    port = await server.start()
    endpoint = SimpleNamespace(port=port, token='token')
    try:
        reader, writer = await connect(endpoint, 'config')
        await write_frame(writer, {'op': 'call', 'name': 'generate_image', 'args': {'request': {
            'idempotency_key': 'only-once', 'family': 'flare', 'prompt': 'cup', 'width': 32, 'height': 32}}}, timeout=5)
        await asyncio.wait_for(started.wait(), 5)
        writer.close()
        await writer.wait_closed()
        release.set()
        await asyncio.wait_for(asyncio.gather(*list(server.tasks)), 5)
        result = await RemoteBackend(endpoint, 'config').call('get_task', {'idempotency_key': 'only-once'})
        assert result['data']['status'] == 'succeeded'
        assert provider.calls == 1
    finally:
        release.set()
        await server.close()
        await scheduler.close()
        await materializer.close()
        await worker.close()
