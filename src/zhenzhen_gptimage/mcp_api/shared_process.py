"""Owned backend process; the stdio entry point never writes its database."""
from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import version
from pathlib import Path
import secrets

from zhenzhen_gptimage.bootstrap.config import load_config
from .discovery import Endpoint, publish_endpoint
from .lifecycle import run_owned_backend
from .local_ipc import IPCServer, PROTOCOL_VERSION, configuration_identity


async def serve_owned_backend(config, config_dir: Path, backend, *, idle_seconds: float = 60):
    token = secrets.token_urlsafe(32)
    identity = configuration_identity(config, config_dir, token, version('zhenzhen-gptimage2-6-mcp'))
    server = IPCServer(backend, token, identity)
    port = await server.start()
    try:
        publish_endpoint(config.data_dir, Endpoint(port=port, instance=secrets.token_hex(16),
                         protocol=PROTOCOL_VERSION, identity=identity, token=token))
        idle_since = None
        while True:
            try:
                await asyncio.wait_for(server.stop_requested.wait(), timeout=1)
                break
            except TimeoutError:
                pass
            outstanding = await backend.worker.fetchone(
                "SELECT count(*) AS n FROM tasks WHERE status IN "
                "('queued','submitting','retry_wait','materializing','recovery_pending','unknown')"
            )
            if server.connections or server.tasks or outstanding['n']:
                idle_since = None
            elif idle_since is None:
                idle_since = asyncio.get_running_loop().time()
            elif asyncio.get_running_loop().time() - idle_since >= idle_seconds:
                break
    finally:
        await server.close()


def main():
    parser = argparse.ArgumentParser(description='Local image generation backend')
    parser.add_argument('--config-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    config = load_config(args.config_dir, args.data_dir, env_file=args.env_file)

    async def serve(backend):
        await serve_owned_backend(config, args.config_dir, backend)

    asyncio.run(run_owned_backend(config, serve))


if __name__ == '__main__':
    main()
