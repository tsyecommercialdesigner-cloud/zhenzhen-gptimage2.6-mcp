import asyncio
import json
from io import BytesIO
import pytest
from PIL import Image
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.artifacts.storage import write_response
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.tasks import start_attempt, transition, StateConflict
from zhenzhen_gptimage.repository.worker import DatabaseWorker

async def prepare(tmp_path, name):
    db = DatabaseWorker(tmp_path/'state.db')
    admission = Admission(db, tmp_path, Limits(free_disk_bytes=1))
    request = GenerationRequest(idempotency_key=name, family='flare', channel='chat', prompt='cup')
    _, ids = await admission.submit([request], 1000)
    await db.run(start_attempt, ids[0], 0, 1001)
    return db, ids[0]

def png():
    out = BytesIO(); Image.new('RGB',(2000,1000),'red').save(out,'PNG'); return out.getvalue()

@pytest.mark.asyncio
async def test_startup_recovers_complete_response_without_provider(tmp_path):
    import base64
    db, task = await prepare(tmp_path, 'one')
    raw = json.dumps({'data':[{'b64_json':base64.b64encode(png()).decode()}]}).encode()
    # chat wire responses use Markdown URLs, so use a deterministic test materializer here.
    artifact = write_response(tmp_path, task, 1, [raw], max_bytes=100000)
    # Simulate an abrupt process exit after response file publication and before DB registration.
    await db.close()
    db = DatabaseWorker(tmp_path/'state.db')
    class TestMaterializer:
        limits=Limits()
        async def materialize(self, task_id, response, **kwargs):
            from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
            m = ArtifactMaterializer(tmp_path)
            try: return await m.materialize(task_id, response, channel='images', expected_size=(2000,1000), deadline=asyncio.get_running_loop().time()+5)
            finally: await m.close()
    service=RecoveryService(db, TestMaterializer(),tmp_path,TaskLocks())
    await service.startup()
    row=await service._row(task)
    assert row['status']=='recovery_pending' and row['response_ref']==artifact.local_path
    recovered, concurrent=await asyncio.gather(service.recover(task), service.recover(task))
    assert recovered['status']=='succeeded' and recovered['attempt_count']==1
    assert concurrent['status']=='succeeded'
    view, preview=await service.image(task)
    assert view['available'] and len(preview)<=1024*1024
    with Image.open(BytesIO(preview)) as image: assert max(image.size)<=1024
    from pathlib import Path
    Path(view['local_path']).unlink()
    missing, preview=await service.image(task)
    assert not missing['available'] and preview is None
    await db.close()

@pytest.mark.asyncio
async def test_unknown_close_idempotent_and_missing_response(tmp_path):
    db, task=await prepare(tmp_path,'two')
    materializer=ArtifactMaterializer(tmp_path)
    service=RecoveryService(db,materializer,tmp_path,TaskLocks())
    await service.startup()
    assert (await service._row(task))['status']=='unknown'
    with pytest.raises(StateConflict): await service.recover(task)
    with pytest.raises(StateConflict): await service.close(task,'recovery_pending','wrong')
    results=await asyncio.gather(service.close(task,'unknown','first'), service.close(task,'unknown','second'))
    assert [r[1]['reason'] for r in results] == ['first','first']
    assert (await db.fetchone('SELECT count(*) FROM closure_records'))[0] == 1
    assert (await service._row(task))['status']=='closed'
    await materializer.close(); await db.close()

@pytest.mark.asyncio
async def test_close_waits_for_recover_and_detects_state_change(tmp_path):
    from types import SimpleNamespace
    db, task = await prepare(tmp_path, 'race')
    artifact=write_response(tmp_path,task,1,[b'{}'],max_bytes=100)
    await db.run(lambda conn: transition(conn,task,1,'materializing',1002,reason='received',response_ref=artifact.local_path,attempt_certainty='response_received'))
    await db.run(lambda conn: transition(conn,task,2,'recovery_pending',1003,reason='disk_failure'))
    started=asyncio.Event(); release=asyncio.Event()
    class Blocking:
        limits=Limits()
        async def materialize(self, *args, **kwargs):
            started.set(); await release.wait()
            return [SimpleNamespace(image_index=0, local_path=str(tmp_path/'x.png'),sha256='a'*64,mime_type='image/png',bytes=1,width=1,height=1,revised_prompt=None)]
    service=RecoveryService(db,Blocking(),tmp_path,TaskLocks())
    recovering=asyncio.create_task(service.recover(task))
    await started.wait()
    second=asyncio.create_task(service.recover(task))
    closing=asyncio.create_task(service.close(task,'recovery_pending','manual'))
    await asyncio.sleep(.02)
    assert not closing.done()
    release.set()
    assert (await recovering)['status']=='succeeded'
    assert (await second)['status']=='succeeded'
    with pytest.raises(StateConflict): await closing
    assert (await db.fetchone('select count(*) from closure_records'))[0] == 0
    await db.close()

@pytest.mark.asyncio
async def test_close_waits_for_active_scheduler(tmp_path):
    import time
    from types import SimpleNamespace
    from zhenzhen_gptimage.scheduler.engine import Scheduler
    db=DatabaseWorker(tmp_path/'active.db')
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    request=GenerationRequest(idempotency_key='active',family='flare',channel='chat',prompt='cup')
    _,ids=await admission.submit([request],time.time_ns()//1_000_000);task=ids[0]
    started=asyncio.Event();release=asyncio.Event()
    class Provider:
        async def generate(self,*args,**kwargs):
            started.set();await release.wait();return b'{}'
    class Materializer:
        limits=Limits()
        async def materialize(self,*args,**kwargs):
            return [SimpleNamespace(image_index=0,local_path=str(tmp_path/'x'),sha256='a'*64,mime_type='image/png',bytes=1,width=1,height=1,revised_prompt=None)]
    locks=TaskLocks(); materializer=Materializer()
    scheduler=Scheduler(db,Provider(),tmp_path,materializer,task_locks=locks)
    recovery=RecoveryService(db,materializer,tmp_path,locks)
    running=asyncio.create_task(scheduler.wait(task));await started.wait()
    closing=asyncio.create_task(recovery.close(task,'unknown','close'))
    await asyncio.sleep(.02);assert not closing.done()
    release.set();assert (await running)['status']=='succeeded'
    with pytest.raises(StateConflict): await closing
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_shutdown_cancels_recovery_and_retains_state(tmp_path):
    db, task = await prepare(tmp_path, 'shutdown')
    artifact=write_response(tmp_path,task,1,[b'{}'],max_bytes=100)
    await db.run(lambda conn: transition(conn,task,1,'materializing',1002,reason='received',response_ref=artifact.local_path,attempt_certainty='response_received'))
    await db.run(lambda conn: transition(conn,task,2,'recovery_pending',1003,reason='disk_failure'))
    started=asyncio.Event()
    class Blocking:
        limits=Limits()
        async def materialize(self,*args,**kwargs):
            started.set();await asyncio.Event().wait()
    service=RecoveryService(db,Blocking(),tmp_path,TaskLocks())
    task_wait=asyncio.create_task(service.recover(task));await started.wait()
    await service.shutdown(0)
    with pytest.raises(asyncio.CancelledError): await task_wait
    assert (await service._row(task))['status']=='recovery_pending'
    with pytest.raises(RuntimeError): await service.recover(task)
    await db.close()
