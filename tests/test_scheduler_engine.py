import asyncio
import json
from types import SimpleNamespace
import pytest
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.providers.t8_star.client import ProviderError
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler, _now_ms
from zhenzhen_gptimage.prompts.templates import save_template
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput

def request(key, channel='images'):
    return GenerationRequest(idempotency_key=key, family='flare', channel=channel,
        width=None if channel=='chat' else 512,height=None if channel=='chat' else 512,prompt='cup')

class Provider:
    def __init__(self, failures=0): self.failures=failures; self.active=0; self.peak=0; self.calls=[]
    async def generate(self, snapshot, references, *, remaining_seconds):
        self.calls.append((snapshot.channel,snapshot.resolved_model))
        if self.failures:
            self.failures-=1
            raise ProviderError('CONNECT_NOT_SENT',safe_retry=True)
        self.active+=1; self.peak=max(self.peak,self.active)
        await asyncio.sleep(.03)
        self.active-=1
        return json.dumps({'data':[{'url':'https://example.test/image'}]}).encode()

class Materializer:
    async def materialize(self, task_id, raw, *, channel, expected_size, deadline):
        return [SimpleImage(task_id)]

def SimpleImage(task_id):
    return SimpleNamespace(image_index=0, local_path=task_id+'.png', sha256='a'*64,
        mime_type='image/png', bytes=10, width=512,height=512,revised_prompt=None)

def test_retry_delay_bounds_and_retry_after(monkeypatch):
    from zhenzhen_gptimage.scheduler.engine import retry_delay
    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.random.uniform',lambda a,b:a)
    assert retry_delay(1)==1 and retry_delay(2)==2 and retry_delay(1,4)==4
    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.random.uniform',lambda a,b:b)
    assert retry_delay(1)==2 and retry_delay(2)==4 and retry_delay(2,False)==4
    with pytest.raises(ValueError): retry_delay(3)

@pytest.mark.asyncio
async def test_shared_wait_and_bounded_concurrency(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db')
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _, ids=await admission.submit([request(str(n)) for n in range(10)],_now_ms())
    class BarrierProvider(Provider):
        def __init__(self):
            super().__init__()
            self.ready = asyncio.Event()
        async def generate(self, snapshot, references, *, remaining_seconds):
            self.calls.append((snapshot.channel, snapshot.resolved_model))
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 6:
                self.ready.set()
            await asyncio.wait_for(self.ready.wait(), 3)
            self.active -= 1
            return json.dumps({'data':[{'url':'https://example.test/image'}]}).encode()
    provider=BarrierProvider(); scheduler=Scheduler(db,provider,tmp_path,Materializer(),concurrency=6)
    results=await asyncio.gather(*(scheduler.wait(task) for task in ids),scheduler.wait(ids[0]))
    assert all(r['status']=='succeeded' for r in results)
    assert provider.peak==6 and len(provider.calls)==10
    await scheduler.close(); await db.close()

@pytest.mark.asyncio
async def test_retry_uses_same_channel_and_snapshot(tmp_path,monkeypatch):
    db=DatabaseWorker(tmp_path/'state.db')
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _, ids=await admission.submit([request('one','chat')],_now_ms())
    provider=Provider(failures=2); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.random.uniform',lambda a,b: 0.001)
    result=await scheduler.wait(ids[0])
    assert result['status']=='succeeded' and result['attempt_count']==3
    assert provider.calls==[('chat','gpt-image-2.6-flare')]*3
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_retry_backoff_releases_single_concurrency_slot(tmp_path, monkeypatch):
    class FirstFails(Provider):
        async def generate(self, snapshot, references, *, remaining_seconds):
            self.calls.append(snapshot.prompt)
            if snapshot.prompt == 'first' and self.calls.count('first') == 1:
                raise ProviderError('CONNECT_NOT_SENT',safe_retry=True)
            return json.dumps({'data':[{'url':'https://example.test/image'}]}).encode()
    db=DatabaseWorker(tmp_path/'state.db');admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    a=request('first').model_copy(update={'prompt':'first'})
    b=request('second').model_copy(update={'prompt':'second'})
    _,ids=await admission.submit([a,b],_now_ms())
    provider=FirstFails();scheduler=Scheduler(db,provider,tmp_path,Materializer(),concurrency=1)
    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.random.uniform',lambda a,b: .2)
    await asyncio.gather(*(scheduler.wait(i) for i in ids))
    assert provider.calls == ['first','second','first']
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_admission_reuses_old_template_and_image(tmp_path):
    from PIL import Image
    db=DatabaseWorker(tmp_path/'state.db')
    source=(tmp_path/'input.png').resolve()
    Image.new('RGB',(10,10),'blue').save(source)
    await db.run(save_template,SaveTemplateInput(code='sku',content='old {{item}}',variables=[{'name':'item','required':True}]),_now_ms())
    r=GenerationRequest(idempotency_key='stable',family='flare',width=512,height=512,
        template_code='sku',template_variables={'item':'cup'},references=[{'local_path':str(source)}])
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([r],_now_ms())
    before=await db.fetchone('select snapshot_json from tasks where task_id=?',(ids[0],))
    await db.run(save_template,SaveTemplateInput(code='sku',content='new {{item}}',variables=[{'name':'item','required':True}],expected_version=1),_now_ms())
    source.unlink()
    _,reused=await admission.submit([r],_now_ms())
    after=await db.fetchone('select snapshot_json from tasks where task_id=?',(ids[0],))
    assert ids==reused and before[0]==after[0] and 'old cup' in after[0]
    path=await db.fetchone('select local_path from reference_assets where task_id=?',(ids[0],))
    assert __import__('pathlib').Path(path[0]).exists()
    await db.close()

@pytest.mark.asyncio
async def test_admission_rejects_low_disk_without_losing_references(tmp_path, monkeypatch):
    from PIL import Image
    from zhenzhen_gptimage.artifacts.storage import ResourceLimitError
    db=DatabaseWorker(tmp_path/'state.db')
    source=(tmp_path/'input.png').resolve()
    Image.new('RGB',(10,10),'blue').save(source)
    r=GenerationRequest(idempotency_key='stable',family='flare',width=512,height=512,
        prompt='cup',references=[{'local_path':str(source)}])
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([r],_now_ms())
    path=await db.fetchone('select local_path from reference_assets where task_id=?',(ids[0],))
    def no_space(*args): raise ResourceLimitError('insufficient disk space')
    monkeypatch.setattr('zhenzhen_gptimage.generation.admission.check_disk_budget',no_space)
    with pytest.raises(ResourceLimitError): await admission.submit([request('new')],_now_ms())
    assert (await db.fetchone('select count(*) from tasks'))[0]==1
    assert __import__('pathlib').Path(path[0]).exists()
    await db.close()

@pytest.mark.asyncio
async def test_deadline_waiting_for_slot(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db')
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('deadline')],_now_ms()-599950)
    scheduler=Scheduler(db,Provider(),tmp_path,Materializer(),concurrency=1)
    await scheduler.semaphore.acquire()
    result=await asyncio.wait_for(scheduler.wait(ids[0]),1)
    assert result['status']=='expired' and result['attempt_count']==0
    scheduler.semaphore.release()
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_unknown_error_never_retries(tmp_path):
    class UnknownProvider(Provider):
        async def generate(self,*args,**kwargs):
            self.calls.append('sent')
            raise ProviderError('SUBMISSION_UNKNOWN')
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('unknown')],_now_ms())
    provider=UnknownProvider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    result=await scheduler.wait(ids[0])
    assert result['status']=='unknown' and len(provider.calls)==1
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_cancelled_waiter_prevents_new_attempt(tmp_path):
    class Blocked(Provider):
        def __init__(self): super().__init__(); self.entered=asyncio.Event(); self.release=asyncio.Event()
        async def generate(self,*args,**kwargs):
            self.calls.append('attempt'); self.entered.set(); await self.release.wait()
            raise ProviderError('CONNECT_NOT_SENT',safe_retry=True)
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('cancel')],_now_ms())
    provider=Blocked(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    waiter=asyncio.create_task(scheduler.wait(ids[0])); await provider.entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError): await waiter
    provider.release.set()
    await scheduler.inflight[ids[0]]
    assert len(provider.calls)==1
    row=await scheduler._row(ids[0]); assert row['status']=='failed'
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_cancelled_waiter_while_waiting_for_slot_does_not_send(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('cancel-queued')],_now_ms())
    provider=Provider(); scheduler=Scheduler(db,provider,tmp_path,Materializer(),concurrency=1)
    await scheduler.semaphore.acquire()
    waiter=asyncio.create_task(scheduler.wait(ids[0]))
    await asyncio.sleep(.02)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError): await waiter
    scheduler.semaphore.release()
    await scheduler.inflight[ids[0]]
    assert not provider.calls and (await scheduler._row(ids[0]))['status']=='cancelled'
    await scheduler.close(); await db.close()

@pytest.mark.asyncio
async def test_task_lock_waiters_and_cancellation_do_not_leak_or_overlap():
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    locks=TaskLocks(); entered=asyncio.Event(); release=asyncio.Event(); order=[]
    async def first():
        async with locks.hold('task'):
            order.append('first'); entered.set(); await release.wait()
    async def other():
        async with locks.hold('task'): order.append('second')
    a=asyncio.create_task(first());await entered.wait()
    b=asyncio.create_task(other());c=asyncio.create_task(other());await asyncio.sleep(0)
    b.cancel()
    with pytest.raises(asyncio.CancelledError): await b
    release.set();await asyncio.gather(a,c)
    assert order==['first','second'] and not locks._locks and not locks._users

@pytest.mark.asyncio
async def test_actual_materializer_and_persistence(tmp_path):
    from io import BytesIO
    from PIL import Image
    import httpx
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    output=BytesIO(); Image.new('RGB',(512,512),'blue').save(output,format='PNG')
    transport=httpx.MockTransport(lambda req: httpx.Response(200,content=output.getvalue(),headers={'Content-Type':'image/png'}))
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('actual')],_now_ms())
    materializer=ArtifactMaterializer(tmp_path,transport=transport)
    scheduler=Scheduler(db,Provider(),tmp_path,materializer)
    row=await scheduler.wait(ids[0])
    assert row['status']=='succeeded' and __import__('pathlib').Path(row['response_ref']).exists()
    image=await db.fetchone('select local_path,width,height from image_artifacts where task_id=?',(ids[0],))
    assert image[1:]==(512,512) and __import__('pathlib').Path(image[0]).exists()
    await scheduler.close(); await materializer.close(); await db.close()

@pytest.mark.asyncio
async def test_http_stream_is_persisted_before_materialization(tmp_path):
    import httpx
    from zhenzhen_gptimage.providers.t8_star.client import T8StarClient
    from zhenzhen_gptimage.artifacts.storage import inspect_response
    body=json.dumps({'data':[{'url':'https://example.test/image'}]}).encode()
    seen=[]
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(0,len(body),5):
                seen.append('chunk')
                yield body[i:i+5]
    async def handler(request):
        assert request.headers['authorization'] == 'Bearer test'
        return httpx.Response(200,stream=Chunks())
    class InspectMaterializer(Materializer):
        async def materialize(self, task_id, raw, **kwargs):
            assert raw == body
            assert inspect_response(tmp_path,task_id,1) is not None
            return await super().materialize(task_id,raw,**kwargs)
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('stream')],_now_ms())
    scheduler=Scheduler(db,T8StarClient(client,'test'),tmp_path,InspectMaterializer())
    row=await scheduler.wait(ids[0])
    assert row['status']=='succeeded' and len(seen)>1
    await scheduler.close();await db.close();await client.aclose()

@pytest.mark.asyncio
async def test_retry_after_past_deadline_prevents_new_attempt(tmp_path):
    class RetryAfterProvider(Provider):
        async def generate(self,*args,**kwargs):
            self.calls.append('attempt')
            exc=ProviderError('NOT_ACCEPTED',safe_retry=True)
            exc.retry_after_seconds=601
            raise exc
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('after')],_now_ms())
    provider=RetryAfterProvider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    row=await scheduler.wait(ids[0])
    assert row['status']=='failed' and row['attempt_count']==1 and len(provider.calls)==1
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_close_during_submission_records_unknown(tmp_path):
    class BlockingProvider(Provider):
        def __init__(self): super().__init__(); self.started=asyncio.Event()
        async def generate(self,*args,**kwargs):
            self.started.set()
            await asyncio.Event().wait()
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('close')],_now_ms())
    provider=BlockingProvider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    scheduler.kick(ids[0]); await provider.started.wait()
    await scheduler.close(grace_seconds=0)
    row=await scheduler._row(ids[0])
    assert row['status']=='unknown' and row['attempt_count']==1
    await db.close()

@pytest.mark.asyncio
async def test_admission_stop_rejects_new_and_waits_for_existing_holder(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    await admission.lock.acquire()
    stop=asyncio.create_task(admission.stop())
    await asyncio.sleep(0)
    assert not stop.done()
    with pytest.raises(RuntimeError,match='stopping'):
        await admission.submit([request('after-stop')],_now_ms())
    admission.lock.release(); await stop
    assert (await db.fetchone('select count(*) from tasks'))[0] == 0
    await db.close()

@pytest.mark.asyncio
async def test_close_clamps_grace_to_30_and_marks_sent_unknown(tmp_path, monkeypatch):
    class BlockingProvider(Provider):
        def __init__(self): super().__init__(); self.started=asyncio.Event()
        async def generate(self,*args,**kwargs):
            self.started.set(); await asyncio.Event().wait()
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('close-bound')],_now_ms())
    provider=BlockingProvider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    scheduler.kick(ids[0]); await provider.started.wait()
    actual_wait=asyncio.wait; recorded=[]
    async def controlled_wait(tasks, *, timeout):
        recorded.append(timeout)
        return await actual_wait(tasks,timeout=0)
    monkeypatch.setattr('zhenzhen_gptimage.scheduler.engine.asyncio.wait',controlled_wait)
    await scheduler.close(grace_seconds=90)
    assert recorded == [30] and (await scheduler._row(ids[0]))['status']=='unknown'
    with pytest.raises(RuntimeError,match='closing'): scheduler.kick(ids[0])
    await db.close()

@pytest.mark.asyncio
async def test_materialization_error_keeps_response_for_recovery(tmp_path):
    class Broken:
        async def materialize(self,*args,**kwargs): raise OSError('disk full')
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('broken')],_now_ms())
    provider=Provider(); scheduler=Scheduler(db,provider,tmp_path,Broken())
    row=await scheduler.wait(ids[0])
    assert row['status']=='recovery_pending' and row['response_ref'] and len(provider.calls)==1
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_success_status_without_image_is_recoverable_and_never_retried(tmp_path):
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    class EmptyProvider(Provider):
        async def generate(self,*args,**kwargs):
            self.calls.append('sent')
            return b'{"data":[]}'
    db=DatabaseWorker(tmp_path/'state.db');admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('no-image')],_now_ms())
    provider=EmptyProvider(); materializer=ArtifactMaterializer(tmp_path)
    scheduler=Scheduler(db,provider,tmp_path,materializer)
    row=await scheduler.wait(ids[0])
    assert row['status']=='recovery_pending' and row['response_ref'] and len(provider.calls)==1
    await scheduler.close();await materializer.close();await db.close()

@pytest.mark.asyncio
async def test_batch_service_preserves_order_and_reuses_duplicate(tmp_path):
    from zhenzhen_gptimage.generation.service import GenerationService
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    provider=Provider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    batch,rows=await GenerationService(admission,scheduler).generate_batch([request('a'),request('b'),request('a')])
    assert batch and [row['idempotency_key'] for row in rows]==['a','b','a']
    assert rows[0]['task_id']==rows[2]['task_id'] and len(provider.calls)==2
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_batch_service_returns_mixed_outcomes_in_input_order(tmp_path):
    from zhenzhen_gptimage.generation.service import GenerationService
    class Mixed(Provider):
        async def generate(self, snapshot, references, *, remaining_seconds):
            if snapshot.prompt=='bad': raise ProviderError('PROVIDER_REJECTED',status=400)
            return await super().generate(snapshot,references,remaining_seconds=remaining_seconds)
    db=DatabaseWorker(tmp_path/'state.db');admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    scheduler=Scheduler(db,Mixed(),tmp_path,Materializer())
    good=request('good'); bad=request('bad').model_copy(update={'prompt':'bad'})
    _,rows=await GenerationService(admission,scheduler).generate_batch([bad,good])
    assert [r['status'] for r in rows]==['failed','succeeded']
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_resume_keeps_original_deadline(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('restart')],_now_ms()-601000)
    provider=Provider(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    await scheduler.resume()
    await asyncio.gather(*scheduler.inflight.values())
    row=await scheduler._row(ids[0])
    assert row['status']=='expired' and not provider.calls
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_inflight_total_deadline_is_unknown(tmp_path):
    class Slow(Provider):
        async def generate(self,*args,**kwargs):
            self.calls.append('sent')
            while True:
                await asyncio.sleep(.01)
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('slow')],_now_ms()-599850)
    provider=Slow(); scheduler=Scheduler(db,provider,tmp_path,Materializer())
    row=await asyncio.wait_for(scheduler.wait(ids[0]),1)
    assert row['status']=='unknown' and len(provider.calls)==1
    await scheduler.close();await db.close()

@pytest.mark.asyncio
async def test_real_httpx_stream_continuous_data_cannot_extend_deadline(tmp_path):
    import httpx
    from zhenzhen_gptimage.providers.t8_star.client import T8StarClient
    from zhenzhen_gptimage.artifacts.storage import inspect_response
    calls=[]
    class Continuous(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.02)
                yield b'x'
    async def handler(request):
        calls.append(request)
        return httpx.Response(200,stream=Continuous())
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    db=DatabaseWorker(tmp_path/'state.db');admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    _,ids=await admission.submit([request('stream-timeout')],_now_ms()-599750)
    scheduler=Scheduler(db,T8StarClient(client,'test'),tmp_path,Materializer())
    row=await asyncio.wait_for(scheduler.wait(ids[0]),2)
    assert row['status']=='unknown' and row['attempt_count']==1 and len(calls)==1
    assert inspect_response(tmp_path,ids[0],1) is None
    await scheduler.close();await db.close();await client.aclose()
