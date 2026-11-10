"""Authenticated, length-bounded loopback transport for a single backend."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import struct

MAX_FRAME = 4 * 1024 * 1024
HANDSHAKE_TIMEOUT = 5.0
PROTOCOL_VERSION = 1


class IPCError(RuntimeError):
    pass


class IPCIncompatible(IPCError):
    pass


class IPCOutcomeUnknown(IPCError):
    """A request may have been accepted; the caller must not replay it."""


def configuration_identity(config, config_dir, token: str, version: str) -> str:
    """Compare effective settings without publishing their secret values."""
    value = {
        'directory': str(config.data_dir.resolve()),
        'config_dir': str(config_dir.resolve()),
        'env_file': str(config.env_file.resolve()),
        'provider': config.provider,
        'base_url': config.base_url,
        'export_root': str(config.export_root) if config.export_root is not None else None,
        'limits': config.limits.model_dump(mode='json'),
        'api_key': config.api_key.get_secret_value(),
        'version': version,
        'protocol': PROTOCOL_VERSION,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hmac.new(token.encode('utf-8'), encoded, hashlib.sha256).hexdigest()


async def read_frame(reader: asyncio.StreamReader, *, timeout: float) -> dict:
    try:
        async with asyncio.timeout(timeout):
            size = struct.unpack('!I', await reader.readexactly(4))[0]
            if size == 0 or size > MAX_FRAME:
                raise IPCError('invalid IPC frame length')
            payload = await reader.readexactly(size)
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, asyncio.IncompleteReadError,
            TimeoutError, struct.error) as exc:
        raise IPCError('invalid or interrupted IPC frame') from exc
    if not isinstance(value, dict):
        raise IPCError('invalid IPC frame')
    return value


async def write_frame(writer: asyncio.StreamWriter, value: dict, *, timeout: float) -> None:
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(payload) > MAX_FRAME:
            raise IPCError('IPC frame exceeds limit')
        async with asyncio.timeout(timeout):
            writer.write(struct.pack('!I', len(payload)) + payload)
            await writer.drain()
    except (OSError, TimeoutError) as exc:
        raise IPCError('IPC connection closed') from exc


class IPCServer:
    def __init__(self, backend, token: str, identity: str, *, max_connections: int = 32):
        self.backend = backend
        self.token = token
        self.identity = identity
        self.max_connections = max_connections
        self.connections = 0
        self.tasks: set[asyncio.Task] = set()
        self.server = None
        self.closing = False
        self.stop_requested = asyncio.Event()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._accept, '127.0.0.1', 0, limit=MAX_FRAME + 4)
        return self.server.sockets[0].getsockname()[1]

    async def _accept(self, reader, writer):
        if self.closing or self.connections >= self.max_connections:
            writer.close()
            await writer.wait_closed()
            return
        self.connections += 1
        try:
            hello = await read_frame(reader, timeout=HANDSHAKE_TIMEOUT)
            token = hello.get('token')
            if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
                return
            if hello.get('protocol') != PROTOCOL_VERSION or hello.get('identity') != self.identity:
                await write_frame(writer, {'status': 'incompatible'}, timeout=HANDSHAKE_TIMEOUT)
                return
            await write_frame(writer, {'status': 'ready'}, timeout=HANDSHAKE_TIMEOUT)
            request = await read_frame(reader, timeout=HANDSHAKE_TIMEOUT)
            if request == {'op': 'ping'}:
                await write_frame(writer, {'status': 'ready'}, timeout=HANDSHAKE_TIMEOUT)
                return
            if request == {'op': 'stop'}:
                await write_frame(writer, {'status': 'stopping'}, timeout=HANDSHAKE_TIMEOUT)
                self.stop_requested.set()
                return
            if request == {'op': 'hold'}:
                await write_frame(writer, {'status': 'held'}, timeout=HANDSHAKE_TIMEOUT)
                # The idle connection represents a live stdio frontend. EOF
                # releases it; it does not cancel accepted business calls.
                await reader.read(1)
                return
            if request.get('op') in ('cleanup_plan', 'approve_cleanup'):
                plan_id = request.get('plan_id')
                if not isinstance(plan_id, str) or len(plan_id) != 32 or self.backend.retention is None:
                    raise IPCError('invalid cleanup plan')
                try:
                    if request['op'] == 'cleanup_plan':
                        plan = self.backend.retention.get_plan(plan_id)
                        await write_frame(writer, {'status': 'ok', 'plan': plan}, timeout=HANDSHAKE_TIMEOUT)
                    else:
                        await self.backend.retention.approve(plan_id)
                        await write_frame(writer, {'status': 'approved'}, timeout=HANDSHAKE_TIMEOUT)
                except ValueError:
                    await write_frame(writer, {'status': 'invalid_plan'}, timeout=HANDSHAKE_TIMEOUT)
                return
            if request == {'op': 'enable_auto_cleanup'}:
                if self.backend.retention is None:
                    raise IPCError('cleanup unavailable')
                policy = await self.backend.retention.set_policy(True)
                await write_frame(writer, {'status': 'enabled', 'policy':policy}, timeout=HANDSHAKE_TIMEOUT)
                return
            if (request.get('op') != 'call' or not isinstance(request.get('name'), str)
                    or not isinstance(request.get('args'), dict)):
                raise IPCError('invalid request')
            task = asyncio.create_task(self.backend.call(request['name'], request['args']))
            self.tasks.add(task)
            def finished(done):
                self.tasks.discard(done)
                if not done.cancelled():
                    done.exception()  # consume without logging sensitive arguments
            task.add_done_callback(finished)
            # EOF is not cancellation. Only an explicit MCP cancellation
            # frame cancels the waiting business coroutine, preserving the
            # scheduler's existing "no further attempts" cancellation rule.
            watcher = asyncio.create_task(read_frame(reader, timeout=610))
            try:
                done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    try:
                        signal = watcher.result()
                    except IPCError:
                        signal = None
                    if signal == {'op': 'cancel'} and not task.done():
                        task.cancel()
                result = await asyncio.shield(task)
            finally:
                if not watcher.done():
                    watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if isinstance(result.get('_preview'), bytes):
                result['_preview'] = {'base64': base64.b64encode(result['_preview']).decode('ascii')}
            await write_frame(writer, {'status': 'ok', 'result': result}, timeout=HANDSHAKE_TIMEOUT)
        except Exception:
            pass
        finally:
            self.connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def close(self):
        self.closing = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()


async def connect(endpoint, identity: str):
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', endpoint.port), HANDSHAKE_TIMEOUT)
        await write_frame(writer, {'token': endpoint.token, 'identity': identity,
                                   'protocol': PROTOCOL_VERSION}, timeout=HANDSHAKE_TIMEOUT)
        reply = await read_frame(reader, timeout=HANDSHAKE_TIMEOUT)
        if reply.get('status') == 'incompatible':
            raise IPCIncompatible('backend configuration or protocol is incompatible')
        if reply.get('status') != 'ready':
            raise IPCError('backend handshake failed')
        return reader, writer
    except BaseException:
        if 'writer' in locals():
            writer.close()
            await writer.wait_closed()
        raise


class RemoteBackend:
    def __init__(self, endpoint, identity: str):
        self.endpoint, self.identity = endpoint, identity

    async def call(self, name, arguments):
        reader, writer = await connect(self.endpoint, self.identity)
        try:
            # Once writing begins, an interruption cannot distinguish whether
            # the backend accepted the request. Never retry it automatically.
            try:
                await write_frame(writer, {'op': 'call', 'name': name, 'args': arguments}, timeout=HANDSHAKE_TIMEOUT)
                reply = await read_frame(reader, timeout=610)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(write_frame(writer, {'op': 'cancel'}, timeout=1))
                except (IPCError, OSError):
                    pass
                raise
            except IPCError as exc:
                raise IPCOutcomeUnknown('query the original task or idempotency key') from exc
            if reply.get('status') != 'ok' or not isinstance(reply.get('result'), dict):
                raise IPCOutcomeUnknown('query the original task or idempotency key')
            result = reply['result']
            if isinstance(result.get('_preview'), dict):
                result['_preview'] = base64.b64decode(result['_preview']['base64'], validate=True)
            return result
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
