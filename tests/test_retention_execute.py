import os
import asyncio
import threading
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_retention_preview import Worker, insert
from zhenzhen_gptimage.artifacts.retention import RetentionService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.database import connect, initialize
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.mcp_api.local_ipc import IPCServer, RemoteBackend, PROTOCOL_VERSION
from zhenzhen_gptimage.mcp_api.discovery import Endpoint
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_authorized_cleanup_rechecks_and_records(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    old=insert(db,tmp_path,'old',1,'succeeded')
    changed=insert(db,tmp_path,'changed',2,'succeeded')
    pending=insert(db,tmp_path,'pending',3,'recovery_pending')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0)
    with pytest.raises(ValueError,match='not authorized'):
        await service.execute(plan['plan_id'])
    assert old.exists() and changed.exists() and pending.exists()
    changed.write_bytes(b'changed since approval')
    await service.approve(plan['plan_id'])
    result=await service.execute(plan['plan_id'])
    assert {r['task_id']:r['status'] for r in result['results']} == {'old':'deleted','changed':'skipped'}
    assert not old.exists() and changed.exists() and pending.exists()
    assert db.execute('select count(*) from artifact_cleanup_status').fetchone()[0]==1
    assert db.execute('select count(*) from tasks').fetchone()[0]==3
    with pytest.raises(ValueError,match='consumed'):
        await service.execute(plan['plan_id'])
    db.close()


@pytest.mark.asyncio
async def test_reconcile_marks_unfinished_intent_uncertain(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    db.execute("""INSERT INTO artifact_cleanup_events VALUES
        ('event','old',0,?, ?,3,'manual','plan','intent','{}',1,1)""",(str(path),'a'*64))
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    await service.reconcile_intents()
    assert db.execute('select state from artifact_cleanup_events').fetchone()[0]=='uncertain'
    assert path.exists()
    db.close()


@pytest.mark.asyncio
async def test_mcp_approval_requires_host_acceptance(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    retention=RetentionService(Worker(db),tmp_path,TaskLocks())
    backend=ServiceBackend(Worker(db),None,retention=retention)
    plan=await retention.preview(keep_latest=0)
    seen=[]
    async def decline(message, response_type, params, context):
        seen.append(message)
        return ElicitResult(action='decline')
    async with Client(create_server(backend),elicitation_handler=decline) as client:
        result=await client.call_tool_mcp('authorize_cleanup',{'plan_id':plan['plan_id']})
        assert result.isError and not plan['approved']
        assert seen, result.structuredContent
        assert 'old' in seen[0] and 'image_index' in seen[0]
    async def accept(message, response_type, params, context): return {}
    async with Client(create_server(backend),elicitation_handler=accept) as client:
        result=await client.call_tool_mcp('authorize_cleanup',{'plan_id':plan['plan_id']})
        assert not result.isError and plan['approved']
    assert path.exists()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_two_clients_serialize_cleanup_and_export(tmp_path, monkeypatch):
    (tmp_path/'images').mkdir()
    destination=tmp_path/'workspace'; destination.mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    locks=TaskLocks(); worker=Worker(db)
    retention=RetentionService(worker,tmp_path,locks)
    backend=ServiceBackend(worker,None,SimpleNamespace(locks=locks),destination,retention)
    plan=await retention.preview(keep_latest=0)
    await retention.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    entered=threading.Event(); release=threading.Event()
    def delayed(root, item):
        entered.set()
        if not release.wait(5): raise TimeoutError('test release')
        original(root,item)
    monkeypatch.setattr(module,'remove_verified',delayed)
    ipc=IPCServer(backend,'test-token','test-identity');port=await ipc.start()
    endpoint=Endpoint(port=port,instance='test',protocol=PROTOCOL_VERSION,identity='test-identity',token='test-token')
    try:
        first_server=create_server(RemoteBackend(endpoint,endpoint.identity))
        second_server=create_server(RemoteBackend(endpoint,endpoint.identity))
        async with Client(first_server) as first, Client(second_server) as second:
            deletion=asyncio.create_task(first.call_tool_mcp('execute_cleanup',{'plan_id':plan['plan_id']}))
            assert await asyncio.to_thread(entered.wait,3)
            exporting=asyncio.create_task(second.call_tool_mcp('export_image',{'task_id':'old','destination':str(destination/'copy.png')}))
            await asyncio.sleep(.05)
            assert not exporting.done() and path.exists()
            release.set()
            result=await deletion
            assert result.structuredContent['data']['results'][0]['status']=='deleted'
            result=await exporting
            assert result.isError and result.structuredContent['error']['code']=='NOT_FOUND'
            assert not (destination/'copy.png').exists()
    finally:
        release.set()
        await ipc.close()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_export_finishes_before_concurrent_cleanup(tmp_path, monkeypatch):
    (tmp_path/'images').mkdir(); destination=tmp_path/'workspace';destination.mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    locks=TaskLocks();worker=Worker(db);retention=RetentionService(worker,tmp_path,locks)
    backend=ServiceBackend(worker,None,SimpleNamespace(locks=locks),destination,retention)
    plan=await retention.preview(keep_latest=0);await retention.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.export as module
    original=module.export_original;entered=threading.Event();release=threading.Event()
    def delayed(*args):
        entered.set()
        if not release.wait(5): raise TimeoutError('test release')
        return original(*args)
    monkeypatch.setattr(module,'export_original',delayed)
    ipc=IPCServer(backend,'test-token','test-identity');port=await ipc.start()
    endpoint=Endpoint(port=port,instance='test',protocol=PROTOCOL_VERSION,identity='test-identity',token='test-token')
    try:
        async with Client(create_server(RemoteBackend(endpoint,endpoint.identity))) as first, Client(create_server(RemoteBackend(endpoint,endpoint.identity))) as second:
            exporting=asyncio.create_task(first.call_tool_mcp('export_image',{'task_id':'old','destination':str(destination/'copy.png')}))
            assert await asyncio.to_thread(entered.wait,3)
            deletion=asyncio.create_task(second.call_tool_mcp('execute_cleanup',{'plan_id':plan['plan_id']}))
            await asyncio.sleep(.05)
            assert not deletion.done() and path.exists()
            release.set()
            assert not (await exporting).isError
            assert (await deletion).structuredContent['data']['results'][0]['status']=='deleted'
            assert not path.exists() and (destination/'copy.png').read_bytes()==b'old'
    finally:
        release.set();await ipc.close()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_cleanup_waits_for_inflight_image_read(tmp_path,monkeypatch):
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.bootstrap.config import Limits
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    worker=Worker(db);locks=TaskLocks()
    recovery=RecoveryService(worker,SimpleNamespace(limits=Limits()),tmp_path,locks)
    service=RetentionService(worker,tmp_path,locks)
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.recovery as module
    original=module._read_image;entered=threading.Event();release=threading.Event()
    def delayed(*args):
        entered.set()
        if not release.wait(5): raise TimeoutError('test release')
        return original(*args)
    monkeypatch.setattr(module,'_read_image',delayed)
    reading=asyncio.create_task(recovery.image('old',0,False))
    try:
        assert await asyncio.to_thread(entered.wait,3)
        deleting=asyncio.create_task(service.execute(plan['plan_id']))
        await asyncio.sleep(.05)
        assert not deleting.done() and path.exists()
        release.set()
        assert (await reading)[0]['available'] is True
        assert (await deleting)['results'][0]['status']=='deleted'
    finally:
        release.set()
        await asyncio.gather(reading,return_exceptions=True)
        db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
@pytest.mark.parametrize('remove_first,expected_state', [(False,'failed'),(True,'uncertain')])
async def test_restart_does_not_repeat_interrupted_deletion(tmp_path, monkeypatch, remove_first, expected_state):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    locks=TaskLocks();worker=Worker(db);service=RetentionService(worker,tmp_path,locks)
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    def interrupt(root,item):
        if remove_first: original(root,item)
        raise asyncio.CancelledError()
    monkeypatch.setattr(module,'remove_verified',interrupt)
    with pytest.raises(asyncio.CancelledError): await service.execute(plan['plan_id'])
    assert db.execute('select state from artifact_cleanup_events').fetchone()[0]=='intent'
    monkeypatch.setattr(module,'remove_verified',original)
    recovered=RetentionService(worker,tmp_path,locks)
    await recovered.reconcile_intents()
    assert db.execute('select state from artifact_cleanup_events').fetchone()[0]==expected_state
    assert path.exists() is (not remove_first)
    if not remove_first:
        assert (await recovered.preview(keep_latest=0))['count']==1
    assert db.execute('select count(*) from artifact_cleanup_status').fetchone()[0]==0
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_cleaned_original_has_explicit_history(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    insert(db,tmp_path,'old',1,'succeeded')
    locks=TaskLocks();worker=Worker(db);service=RetentionService(worker,tmp_path,locks)
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id']);await service.execute(plan['plan_id'])
    async def image(task_id,index,include_preview):
        row=dict(db.execute('select * from image_artifacts where task_id=?',(task_id,)).fetchone())
        row['available']=False
        return row,None
    backend=ServiceBackend(worker,None,SimpleNamespace(locks=locks,image=image),retention=service)
    result=await backend.call('get_image',{'task_id':'old','image_index':0})
    assert not result['ok'] and result['data']['cleaned'] is True
    task=await backend.call('get_task',{'task_id':'old'})
    assert task['data']['images'][0]['cleaned'] is True
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_partial_failure_does_not_delete_unverified_file(tmp_path, monkeypatch):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    first=insert(db,tmp_path,'first',1,'succeeded')
    second=insert(db,tmp_path,'second',2,'succeeded')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    def intermittent(root,item):
        if item['task_id']=='second': raise PermissionError('simulated access denial')
        return original(root,item)
    monkeypatch.setattr(module,'remove_verified',intermittent)
    result=await service.execute(plan['plan_id'])
    assert {r['task_id']:r['status'] for r in result['results']}=={'first':'deleted','second':'failed'}
    assert not first.exists() and second.exists()
    assert {tuple(row) for row in db.execute('select task_id,state from artifact_cleanup_events')} == {('first','deleted'),('second','failed')}
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows process-crash verification')
@pytest.mark.parametrize('phase,expected_state', [('before','failed'),('after','uncertain')])
async def test_process_crash_during_cleanup_is_reconciled(tmp_path, phase, expected_state):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded');db.close()
    script = '''
import asyncio, os, sys
from pathlib import Path
from zhenzhen_gptimage.repository.database import connect, initialize
from zhenzhen_gptimage.artifacts.retention import RetentionService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
import zhenzhen_gptimage.artifacts.retention as module
class Worker:
 def __init__(self,db): self.db=db
 async def run(self,fn): return fn(self.db)
 async def fetchone(self,sql,args=()): return self.db.execute(sql,args).fetchone()
async def main():
 root=Path(sys.argv[1]);db=connect(root/'state.sqlite3');initialize(db)
 service=RetentionService(Worker(db),root,TaskLocks())
 plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
 original=module.remove_verified
 def crash(root,item):
  if sys.argv[2]=='after': original(root,item)
  os._exit(91)
 module.remove_verified=crash
 await service.execute(plan['plan_id'])
asyncio.run(main())
'''
    result=await asyncio.to_thread(subprocess.run,[sys.executable,'-c',script,str(tmp_path),phase],capture_output=True,timeout=30)
    assert result.returncode==91, result.stderr.decode(errors='replace')
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    assert db.execute('select state from artifact_cleanup_events').fetchone()[0]=='intent'
    service=RetentionService(Worker(db),tmp_path,TaskLocks());await service.reconcile_intents()
    assert db.execute('select state from artifact_cleanup_events').fetchone()[0]==expected_state
    assert path.exists() is (phase=='before')
    assert db.execute('select idempotency_key from tasks').fetchone()[0]=='old'
    assert db.execute('select count(*) from artifact_cleanup_status').fetchone()[0]==0
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows verified file deletion')
async def test_terminal_approval_reviews_exact_plan(tmp_path, monkeypatch, capsys):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    path=insert(db,tmp_path,'old',1,'succeeded')
    worker=Worker(db);service=RetentionService(worker,tmp_path,TaskLocks())
    backend=ServiceBackend(worker,None,retention=service)
    plan=await service.preview(keep_latest=0)
    ipc=IPCServer(backend,'test-token','test-identity');port=await ipc.start()
    endpoint=Endpoint(port=port,instance='test',protocol=PROTOCOL_VERSION,identity='test-identity',token='test-token')
    import zhenzhen_gptimage.mcp_api.backend_control as control
    from zhenzhen_gptimage.mcp_api.startup_coordinator import Probe
    monkeypatch.setattr(control,'load_config',lambda *a,**k:SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(control,'probe_backend',lambda *a:Probe.READY)
    monkeypatch.setattr(control,'read_endpoint',lambda *a:endpoint)
    monkeypatch.setattr(control,'backend_identity',lambda *a:'test-identity')
    monkeypatch.setattr(sys,'argv',['backend_control','approve-cleanup','--plan-id',plan['plan_id']])
    monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(sys.stdout,'isatty',lambda:True)
    monkeypatch.setattr('builtins.input',lambda prompt:f"APPROVE {plan['plan_id']}")
    try:
        assert await asyncio.to_thread(control.main)==0
        shown=capsys.readouterr().out
        assert 'old' in shown and plan['plan_id'] in shown and plan['approved']
        result=await service.execute(plan['plan_id'])
        assert result['results'][0]['status']=='deleted' and not path.exists()
    finally:
        await ipc.close();db.close()
