import hashlib

import pytest

from zhenzhen_gptimage.artifacts.retention import PLAN_TTL_MS, RetentionService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.database import connect, initialize
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server
from fastmcp import Client


class Worker:
    def __init__(self, db): self.db = db
    async def run(self, fn): return fn(self.db)
    async def fetchone(self, sql, values=()): return self.db.execute(sql,values).fetchone()


def insert(db, root, name, created_at, status):
    content = name.encode()
    path = root / 'images' / (name + '.png')
    path.write_bytes(content)
    db.execute("""INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at)
        VALUES (?,?,'images','flare',32,32,'gpt-image-2.6-flare',?,?,'{}',?,?,?,?)""",
        (name, name, 'a'*64, 'b'*64, status, created_at, created_at, created_at+600000))
    db.execute('INSERT INTO image_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
        (name,0,str(path),hashlib.sha256(content).hexdigest(),'image/png',len(content),32,32,None,created_at))
    return path


@pytest.mark.asyncio
async def test_preview_filters_retains_history_and_skips_active(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    insert(db,tmp_path,'older',100,'succeeded')
    insert(db,tmp_path,'newer',200,'succeeded')
    insert(db,tmp_path,'pending',50,'recovery_pending')
    corrupt=insert(db,tmp_path,'corrupt',20,'succeeded');corrupt.write_bytes(b'changed')
    now=[1000]
    service=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:now[0])
    plan=await service.preview(keep_latest=1)
    assert [p['task_id'] for p in plan['items']]==['older']
    assert plan['count']==1 and plan['bytes']==len('older')
    assert {p['task_id'] for p in plan['skipped']}=={'pending','corrupt'}
    assert [p['task_id'] for p in (await service.preview(before_ms=200))['items']]==['older']
    assert db.execute('select count(*) from image_artifacts').fetchone()[0]==4
    now[0] += PLAN_TTL_MS
    with pytest.raises(ValueError,match='expired'): service.get_plan(plan['plan_id'])
    db.close()


@pytest.mark.asyncio
async def test_preview_rejects_bad_filters_and_managed_links(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'link',100,'succeeded')
    external=tmp_path/'outside.png';external.write_bytes(path.read_bytes());path.unlink()
    try: path.symlink_to(external)
    except OSError:
        db.close();pytest.skip('symbolic link unavailable')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    with pytest.raises(ValueError): await service.preview()
    with pytest.raises(ValueError): await service.preview(before_ms=100,keep_latest=1)
    plan=await service.preview(keep_latest=0)
    assert not plan['items'] and plan['skipped'][0]['reason']=='unavailable_or_unmanaged'
    db.close()


@pytest.mark.asyncio
async def test_mcp_preview_requires_one_filter_and_never_deletes(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',100,'succeeded')
    retention=RetentionService(Worker(db),tmp_path,TaskLocks())
    async with Client(create_server(ServiceBackend(Worker(db),None,retention=retention))) as client:
        invalid=await client.call_tool_mcp('preview_cleanup',{})
        assert invalid.isError
        response=await client.call_tool_mcp('preview_cleanup',{'keep_latest':0})
        assert not response.isError
        assert response.structuredContent['data']['items'][0]['task_id']=='old'
        assert path.exists()
    db.close()


@pytest.mark.asyncio
async def test_equal_timestamps_have_stable_order(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    insert(db,tmp_path,'alpha',100,'succeeded')
    insert(db,tmp_path,'beta',100,'succeeded')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    first=await service.preview(keep_latest=1)
    second=await service.preview(keep_latest=1)
    assert [p['task_id'] for p in first['items']] == ['alpha']
    assert first['items'] == second['items']
    db.close()


@pytest.mark.asyncio
async def test_bounded_plans_report_remaining_candidates(tmp_path,monkeypatch):
    import zhenzhen_gptimage.artifacts.retention as module
    monkeypatch.setattr(module,'MAX_CANDIDATES',2)
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    for i in range(5): insert(db,tmp_path,f'image{i}',i+1,'succeeded')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=1)
    assert plan['has_more'] and [i['task_id'] for i in plan['items']]==['image3','image2']
    assert plan['count']==2
    db.close()
