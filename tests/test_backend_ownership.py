"""Backend ownership must remain compatible with the existing directory lock."""
import subprocess
import sys

import pytest

from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock, run_owned_backend
from zhenzhen_gptimage.bootstrap.config import RuntimeConfig


@pytest.mark.asyncio
async def test_backend_callback_owns_lock_and_releases_after_failure(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from zhenzhen_gptimage.mcp_api import lifecycle

    @asynccontextmanager
    async def service(_config):
        lock = InstanceLock(tmp_path)
        lock.acquire()
        try:
            yield object()
        finally:
            lock.release()

    monkeypatch.setattr(lifecycle, 'running_service', service)

    async def serve(backend):
        assert backend is not None
        with pytest.raises(RuntimeError, match='already in use'):
            InstanceLock(tmp_path).acquire()
        raise ValueError('transport failure')

    with pytest.raises(ValueError, match='transport failure'):
        await run_owned_backend(None, serve)
    lock = InstanceLock(tmp_path)
    lock.acquire()
    lock.release()


def test_existing_owner_rejects_other_process_but_not_other_directory(tmp_path):
    lock = InstanceLock(tmp_path / 'shared')
    lock.acquire()
    code = (
        'import sys; from pathlib import Path; '
        'from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock; '
        'lock=InstanceLock(Path(sys.argv[1])); lock.acquire(); lock.release()'
    )
    try:
        occupied = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'shared')],
                                  capture_output=True, text=True, timeout=15)
        separate = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'other')],
                                  capture_output=True, text=True, timeout=15)
        assert occupied.returncode != 0
        assert 'data directory is already in use' in occupied.stderr
        assert separate.returncode == 0, separate.stderr
    finally:
        lock.release()


def test_owned_backend_process_blocks_legacy_process(tmp_path):
    root = tmp_path / 'data'
    code = '''
import asyncio, sys
from pathlib import Path
from zhenzhen_gptimage.bootstrap.config import RuntimeConfig
from zhenzhen_gptimage.mcp_api.lifecycle import run_owned_backend
config = RuntimeConfig(env_file=Path(sys.argv[1]) / '.env', data_dir=Path(sys.argv[1]),
                       api_key='test-only', secret_source='test')
async def serve(backend):
    print('ready', flush=True)
    await asyncio.to_thread(sys.stdin.readline)
asyncio.run(run_owned_backend(config, serve))
'''
    owner = subprocess.Popen([sys.executable, '-u', '-c', code, str(root)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert owner.stdout.readline().strip() == 'ready'
        legacy = subprocess.run([sys.executable, '-c',
            'import sys; from pathlib import Path; '
            'from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock; '
            'lock=InstanceLock(Path(sys.argv[1])); lock.acquire()', str(root)],
            capture_output=True, text=True, timeout=15)
        assert legacy.returncode != 0
        assert 'data directory is already in use' in legacy.stderr
    finally:
        owner.stdin.write('\n')
        owner.stdin.flush()
        owner.communicate(timeout=20)
    assert owner.returncode == 0


@pytest.mark.asyncio
async def test_real_backend_owner_blocks_legacy_lock_and_preserves_directory_isolation(tmp_path):
    config = RuntimeConfig(env_file=tmp_path / '.env', data_dir=tmp_path / 'data',
                           api_key='test-only', secret_source='test')
    other = InstanceLock(tmp_path / 'other')

    async def serve(backend):
        assert (await backend.call('list_tasks', {'limit': 20}))['ok'] is True
        with pytest.raises(RuntimeError, match='already in use'):
            InstanceLock(config.data_dir).acquire()
        other.acquire()
        other.release()

    await run_owned_backend(config, serve)
    lock = InstanceLock(config.data_dir)
    lock.acquire()
    lock.release()
    assert (config.data_dir / 'state.sqlite3').is_file()


@pytest.mark.asyncio
async def test_existing_legacy_owner_blocks_backend_startup(tmp_path):
    config = RuntimeConfig(env_file=tmp_path / '.env', data_dir=tmp_path / 'data',
                           api_key='test-only', secret_source='test')
    lock = InstanceLock(config.data_dir)
    lock.acquire()
    called = False

    async def serve(_backend):
        nonlocal called
        called = True

    try:
        with pytest.raises(RuntimeError, match='already in use'):
            await run_owned_backend(config, serve)
        assert not called
        assert not (config.data_dir / 'state.sqlite3').exists()
    finally:
        lock.release()
