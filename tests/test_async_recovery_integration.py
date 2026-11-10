import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from fastmcp import Client
from pydantic import ValidationError

from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.service import GenerationService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler
from zhenzhen_gptimage.providers.t8_star.client import ProviderError
from zhenzhen_gptimage.repository.tasks import StateConflict

def animation():
    output=BytesIO()
    frames=[Image.new('RGB',(512,512),color) for color in ('red','blue')]
    frames[0].save(output,format='GIF',save_all=True,append_images=frames[1:],duration=200,loop=0)
    return output.getvalue()

class Remote:
    def __init__(self):
        self.post_count=0; self.poll_count=0; self.entered=asyncio.Event(); self.release=asyncio.Event()
    async def submit_async(self,snapshot,*,remaining_seconds):
        self.post_count+=1; return 'remote-123'
    async def query_async(self,remote_id,*,remaining_seconds):
        assert remote_id=='remote-123'; self.poll_count+=1; self.entered.set(); await self.release.wait()
        return 'SUCCESS',json.dumps({'data':[{'b64_json':base64.b64encode(animation()).decode()}]}).encode()

@pytest.mark.asyncio
async def test_mcp_returns_queued_and_restart_recovers_same_remote_id(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db'); limits=Limits(free_disk_bytes=1)
    materializer=ArtifactMaterializer(tmp_path,limits=limits); locks=TaskLocks(); provider=Remote()
    scheduler=Scheduler(db,provider,tmp_path,materializer,task_locks=locks)
    recovery=RecoveryService(db,materializer,tmp_path,locks); recovery.scheduler=scheduler
    backend=ServiceBackend(db,GenerationService(Admission(db,tmp_path,limits),scheduler),recovery)
    try:
        async with Client(create_server(backend)) as client:
            req={'idempotency_key':'async','family':'flare','prompt':'ball','width':512,'height':512,'output_format':'gif','execution_mode':'async'}
            result=await client.call_tool_mcp('generate_image',{'request':req})
            assert not result.isError
            task_id=result.structuredContent['data']['task_id']
            await asyncio.wait_for(provider.entered.wait(),5)
            current=await client.call_tool_mcp('get_task',{'task_id':task_id})
            assert current.structuredContent['data']['remote_task']['remote_id']=='remote-123'
            await scheduler.close(grace_seconds=0)
            assert provider.post_count==1
            provider.release.set()
            await recovery.startup()
            scheduler2=Scheduler(db,provider,tmp_path,materializer,task_locks=locks);recovery.scheduler=scheduler2
            await scheduler2.resume()
            await asyncio.wait_for(scheduler2.inflight[task_id],5)
            row=await scheduler2._row(task_id)
            if row['status']=='unknown': row=await scheduler2.recover_remote(task_id)
            assert row['status']=='succeeded' and row['attempt_count']==1 and provider.post_count==1
            image=await db.fetchone('SELECT local_path FROM image_artifacts WHERE task_id=?',(task_id,))
            assert Path(image['local_path']).read_bytes()==animation()
            result=await client.call_tool_mcp('get_task',{'task_id':task_id})
            view=result.structuredContent['data']
            assert view['status']=='succeeded' and view['remote_task']['remote_status']=='SUCCESS'
            assert view['images'][0]['metadata']['frame_count']==2
            from zhenzhen_gptimage.generation.contracts import TaskView
            TaskView.model_validate(view)
            await scheduler2.close()
    finally:
        await scheduler.close(grace_seconds=0); await materializer.close(); await db.close()

def test_svg_rejects_unverified_models():
    GenerationRequest(idempotency_key='ok',family='flare',prompt='icon',width=1024,height=1024,output_format='svg')
    for options in ({'family':'sunburst','width':1024,'height':1024},{'family':'flare','width':1280,'height':768}):
        with pytest.raises(ValidationError):
            GenerationRequest(idempotency_key='bad',prompt='icon',output_format='svg',**options)

@pytest.mark.asyncio
async def test_unknown_submit_reserves_capacity_even_after_restart(tmp_path):
    class Uncertain(Remote):
        async def submit_async(self,snapshot,*,remaining_seconds):
            self.post_count+=1
            raise ProviderError('SUBMISSION_UNKNOWN')
    db=DatabaseWorker(tmp_path/'state.db');limits=Limits(free_disk_bytes=1)
    m=ArtifactMaterializer(tmp_path,limits=limits); provider=Uncertain(); locks=TaskLocks()
    scheduler=Scheduler(db,provider,tmp_path,m,concurrency=1,task_locks=locks)
    admission=Admission(db,tmp_path,limits)
    def request(key):
        return GenerationRequest(idempotency_key=key,family='flare',prompt='ball',width=512,height=512,output_format='gif',execution_mode='async')
    try:
        _,ids=await admission.submit([request('first'),request('second')],__import__('time').time_ns()//1_000_000)
        await asyncio.wait_for(scheduler.kick(ids[0]),5)
        assert (await scheduler._row(ids[0]))['status']=='unknown' and provider.post_count==1
        await scheduler.close(grace_seconds=0)
        scheduler=Scheduler(db,provider,tmp_path,m,concurrency=1,task_locks=locks)
        task=scheduler.kick(ids[1]); await asyncio.sleep(0.5)
        assert (await scheduler._row(ids[1]))['status']=='queued' and provider.post_count==1
        with pytest.raises(StateConflict): await scheduler.recover_remote(ids[0])
        await scheduler.close(grace_seconds=0)
        assert task.done() and provider.post_count==1
    finally:
        await scheduler.close(grace_seconds=0);await m.close();await db.close()

@pytest.mark.asyncio
async def test_async_remote_concurrency_never_exceeds_six(tmp_path):
    class Many(Remote):
        def __init__(self):
            super().__init__(); self.active=0; self.peak=0; self.six=asyncio.Event()
        async def submit_async(self,snapshot,*,remaining_seconds):
            self.post_count+=1; self.active+=1;self.peak=max(self.peak,self.active)
            if self.active==6:self.six.set()
            return f'remote-{self.post_count}'
        async def query_async(self,remote_id,*,remaining_seconds):
            await self.release.wait();self.active-=1
            return 'SUCCESS',json.dumps({'data':[{'b64_json':base64.b64encode(animation()).decode()}]}).encode()
    db=DatabaseWorker(tmp_path/'state.db');limits=Limits(free_disk_bytes=1)
    m=ArtifactMaterializer(tmp_path,limits=limits); provider=Many();s=Scheduler(db,provider,tmp_path,m)
    admission=Admission(db,tmp_path,limits)
    requests=[GenerationRequest(idempotency_key=str(i),family='flare',prompt='ball',width=512,height=512,output_format='gif',execution_mode='async') for i in range(8)]
    try:
        _,ids=await admission.submit(requests,__import__('time').time_ns()//1_000_000)
        tasks=[s.kick(i) for i in ids]
        await asyncio.wait_for(provider.six.wait(),5)
        await asyncio.sleep(0.2)
        assert provider.post_count==6 and provider.peak==6
        provider.release.set();await asyncio.wait_for(asyncio.gather(*tasks),10)
        assert provider.post_count==8 and provider.peak==6
        assert all([(await s._row(task_id))['status']=='succeeded' for task_id in ids])
    finally:
        await s.close(grace_seconds=0);await m.close();await db.close()

@pytest.mark.asyncio
async def test_async_deadline_retains_id_for_explicit_recovery(tmp_path):
    import time
    db=DatabaseWorker(tmp_path/'state.db');limits=Limits(free_disk_bytes=1)
    m=ArtifactMaterializer(tmp_path,limits=limits);provider=Remote();s=Scheduler(db,provider,tmp_path,m)
    admission=Admission(db,tmp_path,limits)
    req=GenerationRequest(idempotency_key='deadline',family='flare',prompt='ball',width=512,height=512,output_format='gif',execution_mode='async')
    try:
        _,ids=await admission.submit([req],time.time_ns()//1_000_000)
        now=time.time_ns()//1_000_000
        await db.run(lambda conn:conn.execute('UPDATE tasks SET created_at=?,deadline_at=? WHERE task_id=?',(now-599500,now+500,ids[0])))
        await asyncio.wait_for(s.kick(ids[0]),5)
        row=await s._row(ids[0]);assert row['status']=='unknown' and row['attempt_count']==1
        assert (await db.fetchone('SELECT remote_id FROM remote_tasks WHERE task_id=?',(ids[0],)))['remote_id']=='remote-123'
        provider.release.set(); row=await asyncio.wait_for(s.recover_remote(ids[0]),5)
        assert row['status']=='succeeded' and row['attempt_count']==1 and provider.post_count==1
    finally:
        await s.close(grace_seconds=0);await m.close();await db.close()

@pytest.mark.asyncio
async def test_process_restart_with_persisted_id_queries_without_submit(tmp_path):
    import time
    from zhenzhen_gptimage.repository.tasks import start_attempt,record_remote_task
    path=tmp_path/'state.db';limits=Limits(free_disk_bytes=1)
    db=DatabaseWorker(path);admission=Admission(db,tmp_path,limits)
    req=GenerationRequest(idempotency_key='crash',family='flare',prompt='ball',width=512,height=512,output_format='gif',execution_mode='async')
    now=time.time_ns()//1_000_000
    _,ids=await admission.submit([req],now)
    await db.run(start_attempt,ids[0],0,now+1)
    await db.run(record_remote_task,ids[0],1,'remote-123',now+2)
    await db.close()
    db=DatabaseWorker(path);locks=TaskLocks();m=ArtifactMaterializer(tmp_path,limits=limits)
    remote=Remote();remote.release.set();scheduler=Scheduler(db,remote,tmp_path,m,task_locks=locks)
    recovery=RecoveryService(db,m,tmp_path,locks)
    try:
        await recovery.startup();await scheduler.resume()
        await asyncio.wait_for(scheduler.inflight[ids[0]],5)
        row=await scheduler._row(ids[0])
        assert row['status']=='succeeded' and row['attempt_count']==1
        assert remote.post_count==0 and remote.poll_count==1
    finally:
        await scheduler.close(grace_seconds=0);await m.close();await db.close()
