"""Stdio-side adapter to the owned shared backend."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from .local_ipc import RemoteBackend, connect, read_frame, write_frame
from .shared_launch import backend_identity, ensure_shared_backend


class SharedBackend:
    def __init__(self, config, config_dir: Path):
        self.config, self.config_dir = config, config_dir
        self.endpoint = None
        self._reader = self._writer = None
        self._lock = asyncio.Lock()

    async def _connect_if_needed(self):
        async with self._lock:
            endpoint = await asyncio.to_thread(ensure_shared_backend, self.config, self.config_dir)
            if (self.endpoint is not None and self.endpoint.instance == endpoint.instance
                    and self._writer is not None and not self._writer.is_closing()
                    and not self._reader.at_eof()):
                return
            await self._close_hold()
            identity = backend_identity(self.config, self.config_dir, endpoint.token)
            reader, writer = await connect(endpoint, identity)
            try:
                await write_frame(writer, {'op': 'hold'}, timeout=5)
                if (await read_frame(reader, timeout=5)).get('status') != 'held':
                    raise RuntimeError('backend hold failed')
            except BaseException:
                writer.close()
                await writer.wait_closed()
                raise
            self.endpoint, self._reader, self._writer = endpoint, reader, writer

    async def _close_hold(self):
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = self.endpoint = None

    async def call(self, name, arguments):
        await self._connect_if_needed()
        endpoint = self.endpoint
        return await RemoteBackend(endpoint, backend_identity(self.config, self.config_dir, endpoint.token)).call(name, arguments)

    async def close(self):
        async with self._lock:
            await self._close_hold()


@asynccontextmanager
async def shared_backend(config, config_dir: Path):
    backend = SharedBackend(config, config_dir)
    try:
        await backend._connect_if_needed()
        yield backend
    finally:
        await backend.close()
