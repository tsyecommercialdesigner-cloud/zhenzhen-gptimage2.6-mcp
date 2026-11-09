"""End-to-end MCP, scheduler and HTTP transport without external network."""
import asyncio
import base64
import json
import http.server
import threading
from io import BytesIO
from pathlib import Path
import httpx
import pytest
from PIL import Image
from fastmcp import Client
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.service import GenerationService
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.providers.t8_star.client import T8StarClient
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler

@pytest.mark.asyncio
async def test_three_channels_full_local_mcp_flow(tmp_path):
    out=BytesIO(); Image.new('RGB',(32,32),'blue').save(out,'PNG'); image=out.getvalue()
    source=tmp_path/'input.png'; source.write_bytes(image)
    calls=[]; download_errors={'remaining':3}
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            calls.append(('GET',self.path))
            assert 'authorization' not in self.headers
            if self.path=='/recover' and download_errors['remaining']:
                download_errors['remaining']-=1; self.send_response(503); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type','image/png'); self.end_headers(); self.wfile.write(image)
        def do_POST(self):
            calls.append(('POST',self.path)); data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if 'unknown' in str(data): self.send_response(500);self.end_headers();return
            if self.path=='/v1/chat/completions':
                body={'choices':[{'message':{'content':f'![image](http://127.0.0.1:{self.server.server_port}/recover)'}}]}
            else:
                if 'image' in data: assert data['image'][0].startswith('data:image/png;base64,')
                body={'data':[{'b64_json':base64.b64encode(image).decode()}]}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(body).encode())
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    class LocalTransport(httpx.AsyncBaseTransport):
        def __init__(self): self.inner=httpx.AsyncHTTPTransport(retries=0)
        async def handle_async_request(self,request):
            url=request.url.copy_with(scheme='http',host='127.0.0.1',port=server.server_port)
            replacement=httpx.Request(request.method,url,headers=request.headers,content=await request.aread())
            return await self.inner.handle_async_request(replacement)
        async def aclose(self): await self.inner.aclose()
    transport=LocalTransport()
    http_client=httpx.AsyncClient(transport=transport)
    db=DatabaseWorker(tmp_path/'state.db'); limits=Limits(free_disk_bytes=1)
    provider=T8StarClient(http_client,'test-key')
    materializer=ArtifactMaterializer(tmp_path,limits=limits,transport=transport)
    locks=TaskLocks(); scheduler=Scheduler(db,provider,tmp_path,materializer,task_locks=locks)
    recovery=RecoveryService(db,materializer,tmp_path,locks)
    admission=Admission(db,tmp_path,limits)
    backend=ServiceBackend(db,GenerationService(admission,scheduler),recovery)
    try:
        async with Client(create_server(backend)) as client:
            saved=await client.call_tool_mcp('save_prompt_template',{'code':'sku','content':'Show {{name}}','variables':[{'name':'name','required':True}]})
            assert not saved.isError
            rendered=await client.call_tool_mcp('render_prompt_template',{'code':'sku','variables':{'name':'cup'}})
            assert rendered.structuredContent['data']['prompt']=='Show cup'
            batch=await client.call_tool_mcp('generate_batch',{'requests':[
                {'idempotency_key':'image','family':'flare','channel':'images','width':32,'height':32,'template_code':'sku','template_variables':{'name':'cup'},'references':[{'local_path':str(source.resolve())}]},
                {'idempotency_key':'flux','family':'flare','channel':'flux','width':32,'height':32,'prompt':'cup'},
                {'idempotency_key':'chat','family':'flare','channel':'chat','prompt':'cup'},
            ]})
            assert not batch.isError
            items=batch.structuredContent['data']['items']
            assert [i['task']['status'] for i in items]==['succeeded','succeeded','recovery_pending']
            chat=items[2]['task']['task_id']; first=items[0]['task']['task_id']
            query=await client.call_tool_mcp('get_task',{'task_id':first})
            assert query.structuredContent['data']['status']=='succeeded'
            assert Path(query.structuredContent['data']['images'][0]['local_path']).read_bytes()==image
            preview=await client.call_tool_mcp('get_image',{'task_id':first})
            assert not preview.isError and any(c.type=='image' for c in preview.content)
            recovered=await client.call_tool_mcp('recover_task',{'task_id':chat})
            assert not recovered.isError and recovered.structuredContent['data']['status']=='succeeded'
            assert Path(recovered.structuredContent['data']['images'][0]['local_path']).read_bytes()==image
            history=await client.call_tool_mcp('list_tasks',{})
            assert len(history.structuredContent['data']['items'])==3
            unknown=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'unknown','family':'flare','channel':'chat','prompt':'unknown'}})
            assert unknown.isError and unknown.structuredContent['data']['status']=='unknown'
            unknown_id=unknown.structuredContent['data']['task_id']
            closed=await client.call_tool_mcp('close_task',{'task_id':unknown_id,'expected_status':'unknown','reason':'reviewed'})
            assert not closed.isError and closed.structuredContent['data']['status']=='closed'
            assert sum(method=='POST' for method,_ in calls)==4
    finally:
        await scheduler.close(); await materializer.close(); await http_client.aclose(); await db.close()
        server.shutdown();server.server_close();thread.join()
