"""Read a fixture created by the installed v0.1.1 release, not the worktree."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from zhenzhen_gptimage.bootstrap.config import load_config
from zhenzhen_gptimage.mcp_api.backend_control import request_stop
from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock
from zhenzhen_gptimage.mcp_api.local_ipc import RemoteBackend
from zhenzhen_gptimage.mcp_api.shared_launch import ensure_shared_backend

INSTALL = Path('D:/MCP/zhenzhen-gptimage2.6-mcp')
PYTHON = INSTALL / '.venv/Scripts/python.exe'

LEGACY_FIXTURE = r'''
import asyncio, hashlib, json, sys
from pathlib import Path
from importlib.metadata import version
from PIL import Image
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.repository.tasks import accept_batch
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.snapshot import create_snapshot
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput
from zhenzhen_gptimage.prompts.templates import save_template
assert version('zhenzhen-gptimage2-6-mcp') == '0.1.1'
root=Path(sys.argv[1]); root.mkdir(parents=True)
async def main():
    worker=DatabaseWorker(root/'state.sqlite3')
    request=GenerationRequest(idempotency_key='legacy',family='flare',prompt='cup',width=32,height=32)
    snapshot=create_snapshot(request,final_prompt='cup',reference_hashes=())
    _,ids=await worker.run(accept_batch,[request],[snapshot],1000)
    image=root/'old.png'; Image.new('RGB',(32,32),'blue').save(image); raw=image.read_bytes()
    await worker.run(lambda db:db.execute('INSERT INTO image_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
        (ids[0],0,str(image),hashlib.sha256(raw).hexdigest(),'image/png',len(raw),32,32,None,1000)))
    await worker.run(lambda db:db.execute("UPDATE tasks SET status='succeeded' WHERE task_id=?",(ids[0],)))
    await worker.run(save_template,SaveTemplateInput(code='legacy',content='Legacy',variables=[]),1000)
    await worker.close()
    print(json.dumps({'task_id':ids[0],'sha256':hashlib.sha256(raw).hexdigest()}))
asyncio.run(main())
'''


@pytest.mark.asyncio
@pytest.mark.skipif(not PYTHON.is_file(), reason='installed v0.1.1 is not available')
async def test_legacy_install_data_remains_queryable(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only')
    root = tmp_path / 'data'
    result = await asyncio.to_thread(subprocess.run, [str(PYTHON), '-c', LEGACY_FIXTURE, str(root)],
                                     capture_output=True, text=True, timeout=30, cwd=str(INSTALL))
    assert result.returncode == 0, result.stderr
    fixture = json.loads(result.stdout)
    config = load_config(tmp_path, root)
    endpoint = await asyncio.to_thread(ensure_shared_backend, config, tmp_path)
    try:
        backend = RemoteBackend(endpoint, endpoint.identity)
        task = await backend.call('get_task', {'task_id': fixture['task_id']})
        template = await backend.call('get_prompt_template', {'code': 'legacy'})
        image = await backend.call('get_image', {'task_id': fixture['task_id']})
        assert task['data']['status'] == 'succeeded'
        assert template['data']['content'] == 'Legacy'
        assert image['data']['sha256'] == fixture['sha256']
        assert hashlib.sha256((root / 'old.png').read_bytes()).hexdigest() == fixture['sha256']
    finally:
        await request_stop(endpoint, endpoint.identity)
        for _ in range(200):
            lock = InstanceLock(root)
            try:
                lock.acquire(); lock.release(); break
            except RuntimeError:
                await asyncio.sleep(.05)
        else:
            pytest.fail('backend did not release directory')


def test_incompatible_database_does_not_get_reinitialized(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only')
    root = tmp_path / 'data'
    root.mkdir()
    db = sqlite3.connect(root / 'state.sqlite3')
    db.execute('CREATE TABLE preserved (value TEXT)')
    db.execute("INSERT INTO preserved VALUES ('keep')")
    db.execute('PRAGMA user_version=999')
    db.commit(); db.close()
    config = load_config(tmp_path, root)
    with pytest.raises(TimeoutError):
        ensure_shared_backend(config, tmp_path, timeout=3)
    db = sqlite3.connect(root / 'state.sqlite3')
    try:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 999
        assert db.execute('SELECT value FROM preserved').fetchone()[0] == 'keep'
    finally:
        db.close()
