"""Automatic cleanup while real scheduler and recovery operations are active."""
import asyncio
import base64
import json
import os
import time
from io import BytesIO

import pytest
from PIL import Image

from test_retention_preview import insert
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.artifacts.retention import RETENTION_MS, RetentionService
from zhenzhen_gptimage.artifacts.storage import write_response
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.tasks import start_attempt, transition
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='Windows handle deletion integration')
async def test_auto_sweep_during_real_submission_and_recovery(tmp_path):
    (tmp_path/'images').mkdir()
    worker=DatabaseWorker(tmp_path/'state.sqlite3')
    old=await worker.run(lambda db:insert(db,tmp_path,'old',1,'succeeded'))
    limits=Limits(free_disk_bytes=1)
    admission=Admission(worker,tmp_path,limits)
    locks=TaskLocks(); materializer=ArtifactMaterializer(tmp_path,limits=limits)
    output=BytesIO();Image.new('RGB',(32,32),'blue').save(output,'PNG')
    payload=json.dumps({'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]}).encode()
    submitted=asyncio.Event(); allow_submit=asyncio.Event()
    recovering=asyncio.Event(); allow_recovery=asyncio.Event()
    class Provider:
        calls=0
        async def generate(self,*args,**kwargs):
            self.calls+=1;submitted.set();await allow_submit.wait();return payload
    class BlockingRecoveryMaterializer:
        def __init__(self): self.limits=limits
        async def materialize(self,*args,**kwargs):
            recovering.set();await allow_recovery.wait()
            return await materializer.materialize(*args,**kwargs)
    provider=Provider()
    scheduler=Scheduler(worker,provider,tmp_path,materializer,task_locks=locks)
    recovery=RecoveryService(worker,BlockingRecoveryMaterializer(),tmp_path,locks)
    now=time.time_ns()//1_000_000
    requests=[GenerationRequest(idempotency_key=key,family='flare',width=32,height=32,prompt='cup')
              for key in ('submit','recover')]
    _,ids=await admission.submit(requests,now)
    submit_id,recover_id=ids
    await worker.run(lambda db:start_attempt(db,recover_id,0,now+1))
    response=write_response(tmp_path,recover_id,1,[payload],max_bytes=100000)
    await worker.run(lambda db:transition(db,recover_id,1,'materializing',now+2,reason='received',response_ref=response.local_path,attempt_certainty='response_received'))
    await worker.run(lambda db:transition(db,recover_id,2,'recovery_pending',now+3,reason='local_failure'))
    retention=RetentionService(worker,tmp_path,locks,lambda:now+RETENTION_MS+10)
    await retention.set_policy(True)
    running=asyncio.create_task(scheduler.wait(submit_id))
    recovering_task=asyncio.create_task(recovery.recover(recover_id))
    try:
        await asyncio.wait_for(asyncio.gather(submitted.wait(),recovering.wait()),5)
        result=await retention.automatic_sweep()
        assert result == [{'task_id':'old','image_index':0,'status':'deleted'}]
        assert not old.exists() and os.path.exists(response.local_path)
        assert (await scheduler._row(submit_id))['status']=='submitting'
        assert (await recovery._row(recover_id))['status']=='materializing'
        allow_submit.set();allow_recovery.set()
        assert (await running)['status']=='succeeded'
        assert (await recovering_task)['status']=='succeeded'
        assert provider.calls==1
    finally:
        allow_submit.set();allow_recovery.set()
        await asyncio.gather(running,recovering_task,return_exceptions=True)
        await scheduler.close();await materializer.close();await worker.close()
