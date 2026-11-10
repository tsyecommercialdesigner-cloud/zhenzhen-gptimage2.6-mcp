"""Inspect or gracefully stop the backend for one data directory."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
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


async def cleanup_control(endpoint, identity, op, plan_id):
    reader, writer = await connect(endpoint, identity)
    try:
        await write_frame(writer, {'op': op, 'plan_id': plan_id}, timeout=5)
        return await read_frame(reader, timeout=5)
    finally:
        writer.close()
        await writer.wait_closed()


async def enable_auto_control(endpoint, identity):
    reader, writer = await connect(endpoint, identity)
    try:
        await write_frame(writer, {'op':'enable_auto_cleanup'}, timeout=5)
        return await read_frame(reader, timeout=5)
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description='Inspect or control the local image backend')
    parser.add_argument('action', choices=('status', 'stop', 'approve-cleanup', 'enable-auto-cleanup'))
    parser.add_argument('--plan-id')
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
    if args.action == 'enable-auto-cleanup':
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print('Enabling requires an interactive local terminal.', file=sys.stderr)
            return 1
        endpoint = read_endpoint(config.data_dir)
        if endpoint is None:
            print('Backend unavailable.', file=sys.stderr)
            return 1
        print('This enables permanent deletion of eligible originals and their safe response files, manifests and reference snapshots older than 90 days while the backend runs.')
        if input('Type ENABLE 90 DAYS to confirm: ') != 'ENABLE 90 DAYS':
            print('Not enabled.')
            return 1
        identity = backend_identity(config, args.config_dir, endpoint.token)
        response = asyncio.run(enable_auto_control(endpoint, identity))
        if response.get('status') != 'enabled':
            print('Policy could not be enabled.', file=sys.stderr)
            return 1
        print(json.dumps(response['policy'], ensure_ascii=False))
        return 0
    if args.action == 'approve-cleanup':
        if not args.plan_id or not sys.stdin.isatty() or not sys.stdout.isatty():
            print('Approval requires a plan ID and an interactive local terminal.', file=sys.stderr)
            return 1
        endpoint = read_endpoint(config.data_dir)
        if endpoint is None:
            print('Backend unavailable.', file=sys.stderr)
            return 1
        identity = backend_identity(config, args.config_dir, endpoint.token)
        response = asyncio.run(cleanup_control(endpoint, identity, 'cleanup_plan', args.plan_id))
        if response.get('status') != 'ok':
            print('Plan is missing or expired.', file=sys.stderr)
            return 1
        print(json.dumps(response['plan'], ensure_ascii=False, indent=2))
        print('This permanently removes the listed managed originals and associated files. Review every item.')
        answer = input(f'Type APPROVE {args.plan_id} to authorize this plan: ')
        if answer != f'APPROVE {args.plan_id}':
            print('Not approved.')
            return 1
        response = asyncio.run(cleanup_control(endpoint, identity, 'approve_cleanup', args.plan_id))
        if response.get('status') != 'approved':
            print('Plan is missing or expired; nothing approved.', file=sys.stderr)
            return 1
        print('Approved. The MCP client may now execute this exact plan once.')
        return 0
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
