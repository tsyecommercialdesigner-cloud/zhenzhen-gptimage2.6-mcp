"""Offline isolated install, old/new lock exclusion, upgrade and rollback."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from test_shared_legacy_compatibility import INSTALL, LEGACY_FIXTURE, PYTHON


def copy_project(source, target):
    target.mkdir()
    shutil.copytree(source / 'src', target / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock', '.python-version'):
        path = source / name
        if path.exists():
            shutil.copy2(path, target / name)


def sync_project(target):
    environment = os.environ.copy()
    environment.pop('UV_PROJECT_ENVIRONMENT', None)
    environment.pop('VIRTUAL_ENV', None)
    result = subprocess.run(['uv', 'sync', '--locked', '--offline', '--no-dev'], cwd=target,
                            capture_output=True, text=True, timeout=120, env=environment)
    assert result.returncode == 0, result.stderr


async def wait_for_directory_release(data_dir):
    from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock
    for _ in range(700):
        lock = InstanceLock(data_dir)
        try:
            lock.acquire(); lock.release(); return
        except RuntimeError:
            await asyncio.sleep(.05)
    pytest.fail('backend did not release the directory')


@pytest.mark.asyncio
@pytest.mark.skipif(not PYTHON.is_file(), reason='installed v0.1.1 is not available')
async def test_isolated_upgrade_and_rollback_preserve_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    old, new, config_dir = tmp_path / 'old', tmp_path / 'new', tmp_path / 'config'
    copy_project(INSTALL, old)
    copy_project(root, new)
    config_dir.mkdir()
    env_file = config_dir / '.env'
    env_file.write_text('ZHENZHEN_GPTIMAGEGEN_API_KEY=test-only\n', encoding='utf-8')
    env_hash = hashlib.sha256(env_file.read_bytes()).hexdigest()
    await asyncio.to_thread(sync_project, old)
    await asyncio.to_thread(sync_project, new)
    old_python, new_python = (project / '.venv/Scripts/python.exe' for project in (old, new))
    data_dir = tmp_path / 'data'
    fixture = await asyncio.to_thread(subprocess.run, [str(old_python), '-c', LEGACY_FIXTURE, str(data_dir)],
                                      capture_output=True, text=True, timeout=30, cwd=old)
    assert fixture.returncode == 0, fixture.stderr
    original = json.loads(fixture.stdout)
    args = ['-m', 'zhenzhen_gptimage.mcp_api.main', '--config-dir', str(config_dir), '--data-dir', str(data_dir)]
    async with Client(StdioTransport(str(old_python), args, cwd=str(old), keep_alive=False)) as client:
        assert (await client.call_tool_mcp('get_task', {'task_id': original['task_id']})).structuredContent['data']['status'] == 'succeeded'
        check = 'from pathlib import Path; from zhenzhen_gptimage.bootstrap.config import load_config; from zhenzhen_gptimage.mcp_api.shared_launch import ensure_shared_backend; import sys; c=Path(sys.argv[1]); d=Path(sys.argv[2]); ensure_shared_backend(load_config(c,d),c,timeout=2)'
        blocked = await asyncio.to_thread(subprocess.run, [str(new_python), '-c', check, str(config_dir), str(data_dir)],
                                          cwd=new, capture_output=True, text=True, timeout=15)
        assert blocked.returncode != 0 and 'already in use' in blocked.stderr
    await wait_for_directory_release(data_dir)
    async with Client(StdioTransport(str(new_python), args, cwd=str(new), keep_alive=False)) as client:
        image = await client.call_tool_mcp('get_image', {'task_id': original['task_id']})
        template = await client.call_tool_mcp('get_prompt_template', {'code': 'legacy'})
        assert not image.isError and image.structuredContent['data']['sha256'] == original['sha256']
        assert template.structuredContent['data']['content'] == 'Legacy'
    control = [str(new_python), '-m', 'zhenzhen_gptimage.mcp_api.backend_control', 'stop',
               '--config-dir', str(config_dir), '--data-dir', str(data_dir)]
    stopped = await asyncio.to_thread(subprocess.run, control, cwd=new, capture_output=True, text=True, timeout=20)
    assert stopped.returncode == 0, stopped.stderr
    # The control command acknowledges shutdown; poll the directory lock, not a PID.
    await wait_for_directory_release(data_dir)
    async with Client(StdioTransport(str(old_python), args, cwd=str(old), keep_alive=False)) as client:
        image = await client.call_tool_mcp('get_image', {'task_id': original['task_id']})
        template = await client.call_tool_mcp('get_prompt_template', {'code': 'legacy'})
        assert image.structuredContent['data']['sha256'] == original['sha256']
        assert template.structuredContent['data']['content'] == 'Legacy'
    assert hashlib.sha256(env_file.read_bytes()).hexdigest() == env_hash
    assert hashlib.sha256((data_dir / 'old.png').read_bytes()).hexdigest() == original['sha256']
