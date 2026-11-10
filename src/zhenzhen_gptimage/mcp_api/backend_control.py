"""Inspect or gracefully stop the backend for one data directory."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from zhenzhen_gptimage.bootstrap.config import load_config
from .discovery import read_endpoint
from .local_ipc import connect, read_frame, write_frame
from .shared_launch import backend_identity, probe_backend
from .startup_coordinator import Probe


async def request_stop(endpoint, identity):
    reader, writer = await connect(endpoint, identity)
    try:
        await write_frame(writer, {'op': 'stop'}, timeout=5)
        return (await read_frame(reader, timeout=5)).get('status') == 'stopping'
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description='Inspect or stop the local image backend')
    parser.add_argument('action', choices=('status', 'stop'))
    parser.add_argument('--config-dir', type=Path, default=Path.cwd())
    parser.add_argument('--data-dir', type=Path, default=Path.cwd() / 'runtime-data')
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    config = load_config(args.config_dir, args.data_dir, env_file=args.env_file)
    status = probe_backend(config, args.config_dir)
    if status is Probe.INCOMPATIBLE:
        print(json.dumps({'status': 'incompatible'}))
        return 1
    if status is Probe.ABSENT:
        print(json.dumps({'status': 'not_available'}))
        return 0 if args.action == 'status' else 1
    if args.action == 'stop':
        endpoint = read_endpoint(config.data_dir)
        if endpoint is None:
            print(json.dumps({'status': 'not_available'}))
            return 1
        identity = backend_identity(config, args.config_dir, endpoint.token)
        if not asyncio.run(request_stop(endpoint, identity)):
            print(json.dumps({'status': 'stop_failed'}))
            return 1
        print(json.dumps({'status': 'stopping'}))
    else:
        print(json.dumps({'status': 'ready'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
