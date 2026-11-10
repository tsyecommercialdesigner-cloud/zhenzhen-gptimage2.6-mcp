import hashlib
import os
import asyncio

import pytest

from zhenzhen_gptimage.artifacts.retention_auxiliary import collect_auxiliary
from zhenzhen_gptimage.artifacts.storage import write_response
from zhenzhen_gptimage.artifacts.retention import RETENTION_MS,RetentionService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.database import connect,initialize
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from test_retention_preview import Worker,insert


def test_only_registered_valid_companions_are_candidates(tmp_path):
    task_id='aaab'
    artifact=write_response(tmp_path,task_id,1,[b'provider payload'],max_bytes=1000)
    directory=tmp_path/'reference-staging';directory.mkdir()
    reference=directory/'known.asset';reference.write_bytes(b'input snapshot')
    unregistered=directory/'unregistered.asset';unregistered.write_bytes(b'keep')
    refs=[{'local_path':str(reference),'bytes':len(b'input snapshot'),
           'sha256':hashlib.sha256(b'input snapshot').hexdigest()}]
    items=collect_auxiliary(tmp_path,task_id,[artifact.local_path,artifact.local_path],refs,100)
    assert {item['kind'] for item in items}=={'response_body','response_manifest','reference_snapshot'}
    assert len(items)==3 and all(item['task_id']==task_id for item in items)
    assert str(unregistered) not in {item['local_path'] for item in items}
    assert reference.exists() and unregistered.exists()
    manifest=(tmp_path/'responses'/f'{task_id}.1.json');manifest.write_bytes(b'corrupt')
    items=collect_auxiliary(tmp_path,task_id,[artifact.local_path],refs,100)
    assert [item['kind'] for item in items]==['reference_snapshot']


def add_completed_materials(db,root,task_id='abc1'):
    image=insert(db,root,task_id,100,'succeeded')
    response=write_response(root,task_id,1,[b'provider payload'],max_bytes=1000)
    db.execute('UPDATE tasks SET response_ref=? WHERE task_id=?',(response.local_path,task_id))
    stage=root/'reference-staging';stage.mkdir(exist_ok=True)
    reference=stage/'known.asset';reference.write_bytes(b'input snapshot')
    digest=hashlib.sha256(reference.read_bytes()).hexdigest()
    db.execute('INSERT INTO reference_assets VALUES (?,?,?,?,?,?,?,?,?,?)',
        ('ref1',task_id,0,str(reference),'local_file',digest,'image/png',reference.stat().st_size,32,32))
    return image,root/'responses'/f'{task_id}.1.body',root/'responses'/f'{task_id}.1.json',reference


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='Windows handle deletion')
async def test_plan_discloses_and_removes_only_completed_managed_materials(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    image,body,manifest,reference=add_completed_materials(db,tmp_path)
    extra=tmp_path/'responses'/'unregistered.body';extra.write_bytes(b'keep')
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0)
    assert {item.get('kind','image') for item in plan['items']} == {'image','response_body','response_manifest','reference_snapshot'}
    assert plan['bytes']==sum(path.stat().st_size for path in (image,body,manifest,reference))
    await service.approve(plan['plan_id'])
    result=await service.execute(plan['plan_id'])
    assert all(item['status']=='deleted' for item in result['results'])
    assert all(not path.exists() for path in (image,body,manifest,reference)) and extra.exists()
    assert db.execute('select count(*) from auxiliary_cleanup_events where state=\'deleted\'').fetchone()[0]==3
    assert db.execute('select status from tasks where task_id=\'abc1\'').fetchone()[0]=='succeeded'
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='Windows handle deletion')
async def test_manifest_can_be_replanned_after_partial_response_cleanup(tmp_path,monkeypatch):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    image,body,manifest,reference=add_completed_materials(db,tmp_path)
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    def failure(root,item):
        if item.get('kind')=='response_manifest': raise PermissionError('test')
        return original(root,item)
    monkeypatch.setattr(module,'remove_verified',failure)
    result=await service.execute(plan['plan_id'])
    assert any(i.get('kind')=='response_manifest' and i['status']=='failed' for i in result['results'])
    assert not body.exists() and manifest.exists() and not image.exists() and not reference.exists()
    monkeypatch.setattr(module,'remove_verified',original)
    next_plan=await service.preview(keep_latest=0)
    assert [i['kind'] for i in next_plan['items']]==['response_manifest']
    await service.approve(next_plan['plan_id']);await service.execute(next_plan['plan_id'])
    assert not manifest.exists()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='Windows handle deletion')
async def test_automatic_cleans_companions_but_protects_shared_snapshots(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    image,body,manifest,reference=add_completed_materials(db,tmp_path)
    pending=insert(db,tmp_path,'abc2',101,'recovery_pending')
    db.execute('INSERT INTO reference_assets VALUES (?,?,?,?,?,?,?,?,?,?)',
        ('ref2','abc2',0,str(reference),'local_file',hashlib.sha256(reference.read_bytes()).hexdigest(),
         'image/png',reference.stat().st_size,32,32))
    service=RetentionService(Worker(db),tmp_path,TaskLocks(),lambda:RETENTION_MS+1000)
    await service.set_policy(True)
    result=await service.automatic_sweep()
    assert {i.get('kind','image') for i in result}=={'image','response_body','response_manifest'}
    assert not image.exists() and not body.exists() and not manifest.exists()
    assert pending.exists() and reference.exists()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='Windows handle deletion')
async def test_response_manifest_is_retained_when_body_cannot_be_deleted(tmp_path,monkeypatch):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    _,body,manifest,_=add_completed_materials(db,tmp_path)
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    def failure(root,item):
        if item.get('kind')=='response_body': raise PermissionError('test')
        return original(root,item)
    monkeypatch.setattr(module,'remove_verified',failure)
    result=await service.execute(plan['plan_id'])
    assert {i.get('kind'):i['status'] for i in result['results'] if i.get('kind')}['response_manifest']=='skipped'
    assert body.exists() and manifest.exists()
    db.close()


@pytest.mark.asyncio
async def test_auxiliaries_are_not_proposed_when_any_output_is_retained(tmp_path):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    _,body,manifest,reference=add_completed_materials(db,tmp_path)
    second=tmp_path/'images'/'second.png';second.write_bytes(b'second')
    db.execute('INSERT INTO image_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
        ('abc1',1,str(second),hashlib.sha256(b'second').hexdigest(),'image/png',6,32,32,None,200))
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=1)
    assert len(plan['items'])==1 and plan['items'][0]['image_index']==0
    assert all(i.get('kind') is None for i in plan['items'])
    assert body.exists() and manifest.exists() and reference.exists() and second.exists()
    db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='Windows handle deletion')
async def test_interrupted_auxiliary_deletion_is_not_replayed(tmp_path,monkeypatch):
    (tmp_path/'images').mkdir()
    db=connect(tmp_path/'state.sqlite3');initialize(db)
    _,body,manifest,_=add_completed_materials(db,tmp_path)
    service=RetentionService(Worker(db),tmp_path,TaskLocks())
    plan=await service.preview(keep_latest=0);await service.approve(plan['plan_id'])
    import zhenzhen_gptimage.artifacts.retention as module
    original=module.remove_verified
    def interrupted(root,item):
        original(root,item)
        if item.get('kind')=='response_body': raise asyncio.CancelledError()
    monkeypatch.setattr(module,'remove_verified',interrupted)
    with pytest.raises(asyncio.CancelledError): await service.execute(plan['plan_id'])
    assert not body.exists() and manifest.exists()
    monkeypatch.setattr(module,'remove_verified',original)
    restarted=RetentionService(Worker(db),tmp_path,TaskLocks());await restarted.reconcile_intents()
    assert db.execute('select state from auxiliary_cleanup_events').fetchone()[0]=='uncertain'
    next_plan=await restarted.preview(keep_latest=0)
    assert not next_plan['items'] and manifest.exists()
    history=await ServiceBackend(Worker(db),None,retention=restarted).call('get_task',{'task_id':'abc1'})
    assert history['data']['images'][0]['cleanup_uncertain'] is True
    db.close()
