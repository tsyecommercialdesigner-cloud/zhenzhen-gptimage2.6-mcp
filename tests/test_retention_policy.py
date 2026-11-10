import os
import asyncio
import threading

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from test_retention_preview import Worker, insert
from zhenzhen_gptimage.artifacts.retention import RETENTION_MS, RetentionService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.repository.database import connect, initialize


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_auto_default_disabled_strict_age_and_persistence(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    now=RETENTION_MS+1000
    old=insert(db,tmp_path,'old',999,'succeeded')
    boundary=insert(db,tmp_path,'boundary',1000,'succeeded')
    pending=insert(db,tmp_path,'pending',999,'recovery_pending')
    service=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:now)
    assert not (await service.policy())['enabled']
    assert await service.automatic_sweep()==[] and old.exists()
    await service.set_policy(True)
    recreated=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:now)
    assert (await recreated.policy())['enabled']
    result=await recreated.automatic_sweep()
    assert result==[{'task_id':'old','image_index':0,'status':'deleted'}]
    assert not old.exists() and boundary.exists() and pending.exists()
    assert db.execute('select trigger_kind from artifact_cleanup_events').fetchone()[0]=='automatic'
    await recreated.set_policy(False)
    later=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:now+1)
    assert not (await later.policy())['enabled']
    await later.automatic_sweep()
    assert boundary.exists()
    db.close()


@pytest.mark.asyncio
async def test_enabling_requires_host_user_confirmation(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    backend=ServiceBackend(Worker(db),None,retention=service)
    async def decline(message,response_type,params,context):
        assert '90' in message
        return ElicitResult(action='decline')
    async with Client(create_server(backend),elicitation_handler=decline) as client:
        result=await client.call_tool_mcp('set_retention_policy',{'enabled':True})
        assert result.isError and not (await service.policy())['enabled']
    async def accept(message,response_type,params,context): return {}
    async with Client(create_server(backend),elicitation_handler=accept) as client:
        result=await client.call_tool_mcp('set_retention_policy',{'enabled':True})
        assert not result.isError and (await service.policy())['enabled']
        result=await client.call_tool_mcp('set_retention_policy',{'enabled':False})
        assert not result.isError and not (await service.policy())['enabled']
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_disabling_waits_for_inflight_and_stops_next_removal(tmp_path, monkeypatch):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    first=insert(db,tmp_path,'first',1,'succeeded')
    second=insert(db,tmp_path,'second',2,'succeeded')
    service=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:RETENTION_MS+1000)
    await service.set_policy(True)
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified;entered=threading.Event();release=threading.Event()
    def delayed(root,item):
        entered.set()
        if not release.wait(5): raise TimeoutError('test release')
        original(root,item)
    monkeypatch.setattr(module,'remove_verified',delayed)
    sweep=asyncio.create_task(service.automatic_sweep())
    assert await asyncio.to_thread(entered.wait,3)
    disable=asyncio.create_task(service.set_policy(False))
    await asyncio.sleep(.05)
    assert not disable.done() and first.exists() and second.exists()
    release.set()
    await disable;result=await sweep
    assert len(result)==1 and not first.exists() and second.exists()
    assert not (await service.policy())['enabled']
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_automatic_waits_for_export_task_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace
    (tmp_path/'images').mkdir();output=tmp_path/'output';output.mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    original_file=insert(db,tmp_path,'old',1,'succeeded')
    worker=Worker(db);locks=TaskLocks();service=RetentionService(worker,tmp_path,locks,lambda:RETENTION_MS+1000)
    backend=ServiceBackend(worker,None,SimpleNamespace(locks=locks),output,service)
    await service.set_policy(True)
    import zhenzhen_gptimage.artifacts.export as module
    export=module.export_original;entered=threading.Event();release=threading.Event()
    def delayed(*args):
        entered.set()
        if not release.wait(5): raise TimeoutError('test release')
        return export(*args)
    monkeypatch.setattr(module,'export_original',delayed)
    task=asyncio.create_task(backend.call('export_image',{'task_id':'old','destination':str(output/'copy.png')}))
    assert await asyncio.to_thread(entered.wait,3)
    sweep=asyncio.create_task(service.automatic_sweep())
    await asyncio.sleep(.05)
    assert not sweep.done() and original_file.exists()
    release.set()
    assert (await task)['ok']
    assert (await sweep)[0]['status']=='deleted'
    assert not original_file.exists() and (output/'copy.png').read_bytes()==b'old'
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_automatic_rechecks_task_after_recovery_transition(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    queued=insert(db,tmp_path,'queued',1,'submitting')
    locks=TaskLocks();service=RetentionService(Worker(db),tmp_path,locks,lambda:RETENTION_MS+1000)
    await service.set_policy(True)
    async with locks.hold('old'):
        sweep=asyncio.create_task(service.automatic_sweep())
        await asyncio.sleep(.1)
        db.execute("UPDATE tasks SET status='recovery_pending' WHERE task_id='old'")
    results=await sweep
    assert results[0]['status']=='skipped'
    assert path.exists() and queued.exists()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_running_background_loop_only_cleans_when_enabled(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    service=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:RETENTION_MS+1000)
    loop=asyncio.create_task(service.automatic_loop(interval_seconds=.02))
    try:
        await asyncio.sleep(.08)
        assert path.exists()
        await service.set_policy(True)
        for _ in range(100):
            if not path.exists(): break
            await asyncio.sleep(.02)
        assert not path.exists()
    finally:
        loop.cancel();await asyncio.gather(loop,return_exceptions=True)
        db.close()
