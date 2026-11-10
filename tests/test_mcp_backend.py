import asyncio
import pytest
from fastmcp import Client
from zhenzhen_gptimage.bootstrap.config import RuntimeConfig
from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock, running_service
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.repository.worker import DatabaseWorker

@pytest.mark.asyncio
async def test_backend_templates_and_protocol(tmp_path):
    worker=DatabaseWorker(tmp_path/'data.sqlite')
    backend=ServiceBackend(worker,None)
    async with Client(create_server(backend)) as client:
        result=await client.call_tool('save_prompt_template',{'code':'sku','content':'Show {{item}}','variables':[{'name':'item','required':True}]})
        assert result.structured_content['ok']
        result=await client.call_tool('render_prompt_template',{'code':'sku','variables':{'item':'cup'}})
        assert result.structured_content['data']['prompt']=='Show cup'
        assert (await client.call_tool('get_prompt_template',{'code':'sku'})).structured_content['data']['version']==1
        assert len((await client.call_tool('list_prompt_templates',{})).structured_content['data']['items'])==1
        conflict=await client.call_tool_mcp('save_prompt_template',{'code':'sku','content':'Show {{item}}','variables':[{'name':'item','required':True}]})
        assert conflict.isError and conflict.structuredContent['error']['code']=='TEMPLATE_VERSION_CONFLICT'
        result=await client.call_tool('get_task',{'idempotency_key':'missing'},raise_on_error=False)
        assert result.is_error and result.structured_content['error']['code']=='NOT_FOUND'
    await worker.close()

@pytest.mark.asyncio
async def test_recovery_and_close_tools_return_real_state(tmp_path):
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot
    from zhenzhen_gptimage.repository.tasks import accept_batch
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    worker=DatabaseWorker(tmp_path/'test.db')
    r=GenerationRequest(idempotency_key='unknown',family='flare',prompt='mug',width=512,height=512)
    _,ids=await worker.run(accept_batch,[r],[create_snapshot(r,final_prompt='mug',reference_hashes=())],1000)
    await worker.run(lambda db:db.execute("UPDATE tasks SET status='unknown' WHERE task_id=?",(ids[0],)))
    materializer=ArtifactMaterializer(tmp_path)
    backend=ServiceBackend(worker,None,RecoveryService(worker,materializer,tmp_path,TaskLocks()))
    async with Client(create_server(backend)) as client:
        cannot=await client.call_tool_mcp('recover_task',{'task_id':ids[0]})
        assert cannot.isError and cannot.structuredContent['error']['code']=='STATE_CONFLICT'
        closed=await client.call_tool_mcp('close_task',{'task_id':ids[0],'expected_status':'unknown','reason':'done'})
        assert not closed.isError and closed.structuredContent['data']['status']=='closed'
        again=await client.call_tool_mcp('close_task',{'task_id':ids[0],'expected_status':'unknown','reason':'other'})
        assert not again.isError
        assert (await worker.fetchone('SELECT reason FROM closure_records WHERE task_id=?',(ids[0],)))[0]=='done'
    await materializer.close();await worker.close()

def test_instance_lock(tmp_path):
    first,second=InstanceLock(tmp_path),InstanceLock(tmp_path)
    first.acquire()
    with pytest.raises(RuntimeError,match='already in use'): second.acquire()
    first.release()
    second.acquire();second.release()

def test_lock_recovers_after_process_death(tmp_path):
    import os, subprocess, sys
    program = ('from pathlib import Path\nfrom zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock\n'
               'import sys,time\nl=InstanceLock(Path(sys.argv[1]));l.acquire();print("ready",flush=True);time.sleep(60)')
    # Windows venv launchers can spawn a separate interpreter; terminate the
    # real interpreter so this checks OS lock release on process death.
    env=os.environ.copy()
    env['PYTHONPATH']=str(__import__('pathlib').Path(__file__).resolve().parents[1]/'src')
    proc=subprocess.Popen([sys._base_executable,'-c',program,str(tmp_path)],stdout=subprocess.PIPE,text=True,env=env)
    try:
        assert proc.stdout.readline().strip() == 'ready'
        with pytest.raises(RuntimeError): InstanceLock(tmp_path).acquire()
        proc.terminate();proc.wait(timeout=10)
        lock=InstanceLock(tmp_path);lock.acquire();lock.release()
    finally:
        if proc.poll() is None: proc.kill();proc.wait()

@pytest.mark.asyncio
async def test_startup_and_shutdown_without_network(tmp_path):
    cfg=RuntimeConfig(env_file=tmp_path/'.env',data_dir=tmp_path,api_key='placeholder',secret_source='test')
    async with running_service(cfg) as backend:
        assert (await backend.call('list_tasks',{}))['data']['items']==[]
        with pytest.raises(RuntimeError,match='already in use'):
            async with running_service(cfg): pass
    async with running_service(cfg) as backend:
        assert (await backend.call('list_tasks',{}))['ok']

@pytest.mark.asyncio
async def test_stdio_real_entrypoint_with_local_key(tmp_path):
    from fastmcp.client.transports import PythonStdioTransport
    from zhenzhen_gptimage.mcp_api.backend_control import request_stop
    from zhenzhen_gptimage.mcp_api.discovery import read_endpoint
    config=tmp_path/'config';config.mkdir()
    (config/'.env').write_text('ZHENZHEN_GPTIMAGEGEN_API_KEY=placeholder\n')
    script=tmp_path/'server.py'
    script.write_text('import sys\nfrom zhenzhen_gptimage.mcp_api.main import main\nsys.argv=["server","--config-dir",'+repr(str(config))+',"--data-dir",'+repr(str(tmp_path/'data'))+']\nmain()\n',encoding='utf-8')
    async with Client(PythonStdioTransport(script, keep_alive=False)) as client:
        names={tool.name for tool in await client.list_tools()}
        assert 'accept_gif_size' in names and 'generate_image' in names
        result=await client.call_tool_mcp('list_tasks',{})
        assert not result.isError and result.structuredContent['data']['items']==[]
    endpoint = read_endpoint(tmp_path/'data')
    assert endpoint is not None
    assert await request_stop(endpoint, endpoint.identity)

@pytest.mark.asyncio
async def test_failed_task_queries_succeed_and_generation_failure_retains_id(tmp_path):
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot
    from zhenzhen_gptimage.repository.tasks import accept_batch
    worker=DatabaseWorker(tmp_path/'test.db')
    r=GenerationRequest(idempotency_key='k',family='flare',prompt='mug',width=512,height=512)
    snapshot=create_snapshot(r,final_prompt='mug',reference_hashes=())
    _,ids=await worker.run(accept_batch,[r],[snapshot],1000)
    await worker.run(lambda db: db.execute("UPDATE tasks SET status='failed',error_category='PROVIDER_REJECTED' WHERE task_id=?",(ids[0],)))
    class Generation:
        async def generate_image(self, request):
            return dict(await worker.fetchone('select * from tasks where task_id=?',(ids[0],)))
    async with Client(create_server(ServiceBackend(worker,Generation()))) as client:
        query=await client.call_tool_mcp('get_task',{'idempotency_key':'k'})
        assert not query.isError and query.structuredContent['data']['status']=='failed'
        result=await client.call_tool_mcp('generate_image',{'request':r.model_dump(exclude_none=True)})
        assert result.isError and result.structuredContent['data']['task_id']==ids[0]
        assert result.structuredContent['error']['task_id']==ids[0]
    await worker.close()

@pytest.mark.asyncio
async def test_image_preview_mcp_content_and_missing_file(tmp_path):
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot
    from zhenzhen_gptimage.repository.tasks import accept_batch
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    from PIL import Image
    import hashlib
    worker=DatabaseWorker(tmp_path/'test.db')
    r=GenerationRequest(idempotency_key='k',family='flare',prompt='mug',width=512,height=512)
    snapshot=create_snapshot(r,final_prompt='mug',reference_hashes=())
    _,ids=await worker.run(accept_batch,[r],[snapshot],1000)
    image=tmp_path/'image.png';Image.new('RGB',(2048,1024),'blue').save(image)
    payload=image.read_bytes()
    await worker.run(lambda db:db.execute('INSERT INTO image_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
        (ids[0],0,str(image),hashlib.sha256(payload).hexdigest(),'image/png',len(payload),2048,1024,None,1000)))
    materializer=ArtifactMaterializer(tmp_path)
    backend=ServiceBackend(worker,None,RecoveryService(worker,materializer,tmp_path,TaskLocks()))
    async with Client(create_server(backend)) as client:
        result=await client.call_tool_mcp('get_image',{'task_id':ids[0]})
        assert not result.isError and sum(item.type=='image' for item in result.content)==1
        image.unlink()
        result=await client.call_tool_mcp('get_image',{'task_id':ids[0]})
        assert result.isError and result.structuredContent['error']['code']=='ARTIFACT_UNAVAILABLE'
    await materializer.close();await worker.close()

@pytest.mark.asyncio
async def test_mock_generation_batch_through_mcp(tmp_path):
    import base64, json
    from io import BytesIO
    from PIL import Image
    from zhenzhen_gptimage.bootstrap.config import Limits
    from zhenzhen_gptimage.generation.admission import Admission
    from zhenzhen_gptimage.generation.service import GenerationService
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    from zhenzhen_gptimage.scheduler.engine import Scheduler
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.providers.t8_star.client import ProviderError
    data=BytesIO();Image.new('RGB',(512,512),'blue').save(data,format='PNG')
    raw=json.dumps({'data':[{'b64_json':base64.b64encode(data.getvalue()).decode()}]}).encode()
    class Provider:
        def __init__(self): self.calls=[]
        async def generate(self,snapshot,refs,*,remaining_seconds):
            self.calls.append(snapshot.prompt)
            if snapshot.prompt=='fail': raise ProviderError('PROVIDER_REJECTED',status=400)
            return raw
    worker=DatabaseWorker(tmp_path/'test.db');limits=Limits(free_disk_bytes=1)
    admission=Admission(worker,tmp_path,limits);materializer=ArtifactMaterializer(tmp_path,limits=limits)
    locks=TaskLocks();recovery=RecoveryService(worker,materializer,tmp_path,locks)
    provider=Provider();scheduler=Scheduler(worker,provider,tmp_path,materializer,task_locks=locks)
    backend=ServiceBackend(worker,GenerationService(admission,scheduler),recovery)
    async with Client(create_server(backend)) as client:
        request=lambda key,prompt:{'idempotency_key':key,'family':'flare','width':512,'height':512,'prompt':prompt}
        result=await client.call_tool_mcp('generate_batch',{'requests':[request('a','ok'),request('b','fail'),request('a','ok')]})
        assert not result.isError
        data=result.structuredContent['data']
        assert data['succeeded_count']==2 and data['failed_count']==1 and data['items'][2]['reused']
        assert provider.calls.count('ok')==1 and provider.calls.count('fail')==1
        assert sum(item.type=='image' for item in result.content)==1
        item=await client.call_tool_mcp('get_task',{'idempotency_key':'a'})
        assert item.structuredContent['data']['status']=='succeeded'
    await scheduler.close();await materializer.close();await worker.close()

@pytest.mark.asyncio
async def test_cancelled_host_can_query_same_idempotency_key(tmp_path):
    from zhenzhen_gptimage.bootstrap.config import Limits
    from zhenzhen_gptimage.generation.admission import Admission
    from zhenzhen_gptimage.generation.service import GenerationService
    from zhenzhen_gptimage.scheduler.engine import Scheduler
    class Provider:
        def __init__(self): self.started=asyncio.Event();self.finish=asyncio.Event();self.calls=0
        async def generate(self,snapshot,refs,*,remaining_seconds):
            self.calls+=1;self.started.set();await self.finish.wait();return b'{}'
    class Materializer:
        async def materialize(self,*a,**kw): return []
    worker=DatabaseWorker(tmp_path/'test.db');provider=Provider()
    scheduler=Scheduler(worker,provider,tmp_path,Materializer())
    backend=ServiceBackend(worker,GenerationService(Admission(worker,tmp_path,Limits(free_disk_bytes=1)),scheduler))
    async with Client(create_server(backend)) as client:
        call=asyncio.create_task(client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'lost','family':'flare','width':512,'height':512,'prompt':'cup'}}))
        await asyncio.wait_for(provider.started.wait(),3)
        call.cancel()
        with pytest.raises(asyncio.CancelledError): await call
        result=await client.call_tool_mcp('get_task',{'idempotency_key':'lost'})
        assert not result.isError and result.structuredContent['data']['idempotency_key']=='lost'
        assert provider.calls==1
        provider.finish.set()
        await scheduler.close()
    await worker.close()
