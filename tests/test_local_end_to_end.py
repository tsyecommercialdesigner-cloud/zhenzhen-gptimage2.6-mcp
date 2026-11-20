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

async def approve_recovery(message, response_type, params, context):
    from fastmcp.client.elicitation import ElicitResult
    return ElicitResult(action='accept')


@pytest.mark.asyncio
async def test_three_channels_full_local_mcp_flow(tmp_path):
    out=BytesIO(); Image.new('RGB',(32,32),'blue').save(out,'PNG'); image=out.getvalue()
    source=tmp_path/'input.png'; source.write_bytes(image)
    mismatched=BytesIO(); Image.new('RGB',(796,1024),'blue').save(mismatched,'PNG')
    calls=[]; download_errors={'remaining':3}
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            calls.append(('GET',self.path))
            assert 'authorization' not in self.headers
            if self.path=='/legacy-fixture':
                self.send_response(200); self.send_header('Content-Type','image/png'); self.end_headers(); self.wfile.write(mismatched.getvalue()); return
            if self.path=='/recover' and download_errors['remaining']:
                download_errors['remaining']-=1; self.send_response(503); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type','image/png'); self.end_headers(); self.wfile.write(image)
        def do_POST(self):
            calls.append(('POST',self.path)); data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if 'unknown' in str(data): self.send_response(500);self.end_headers();return
            if self.path=='/v1/chat/completions':
                body={'choices':[{'message':{'content':f'![image](http://127.0.0.1:{self.server.server_port}/recover)'}}]}
            elif data.get('prompt') == 'legacy-fixture':
                body={'data':[{'url':f'http://127.0.0.1:{self.server.server_port}/legacy-fixture'}]}
            else:
                if 'image' in data: assert data['image'][0].startswith('data:image/png;base64,')
                body={'data':[{'b64_json':base64.b64encode(mismatched.getvalue() if data.get('size') == '800x1024' else image).decode()}]}
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
        async with Client(create_server(backend), elicitation_handler=approve_recovery) as client:
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
            not_ready=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'optional-provider','family':'flare','provider':'seedance','width':32,'height':32,'prompt':'cup'}})
            assert not_ready.isError
            assert sum(method=='POST' for method,_ in calls)==4
            d05={'idempotency_key':'d05-fixture','family':'flare','prompt':'fixture','width':800,'height':1024}
            result=await client.call_tool_mcp('generate_image', {'request':d05})
            assert not result.isError and result.structuredContent['error'] is None
            assert any(w.startswith('SIZE_MISMATCH:') for w in result.structuredContent['warnings'])
            view=result.structuredContent['data']
            assert view['status']=='succeeded' and view['error_category'] is None
            assert view['size_mismatch']['code']=='SIZE_MISMATCH'
            assert view['size_mismatch']['requested']=={'width':800,'height':1024}
            actual=view['size_mismatch']['actual'][0]
            assert (actual['width'],actual['height'],actual['available'])==(796,1024,True)
            assert Path(view['images'][0]['local_path']).read_bytes()==mismatched.getvalue()
            args={'task_id':view['task_id']}
            queried=await client.call_tool_mcp('get_task',args)
            assert queried.structuredContent['data']['size_mismatch']==view['size_mismatch']
            assert (await client.call_tool_mcp('get_image',args)).structuredContent['data']['width']==796
            single_export=tmp_path/'mismatch-export.png'
            exported=await client.call_tool_mcp('export_image',{**args,'destination':str(single_export)})
            assert not exported.isError and single_export.read_bytes()==mismatched.getvalue()
            batch=await client.call_tool_mcp('generate_batch', {'requests':[d05,{**d05,'idempotency_key':'d05-batch'}]})
            assert not batch.isError
            combined=batch.structuredContent['data']
            assert (combined['succeeded_count'],combined['unresolved_count'],combined['failed_count'])==(2,0,0)
            assert combined['items'][0]['reused'] and combined['items'][0]['task']['size_mismatch']==view['size_mismatch']
            assert combined['items'][1]['task']['size_mismatch']['code']=='SIZE_MISMATCH'
            assert len(batch.structuredContent['warnings'])==2
            assert sum(method=='POST' for method,_ in calls)==6

            from zhenzhen_gptimage.artifacts.output import PublishedImage
            from zhenzhen_gptimage.repository.tasks import stage_static_size_mismatch
            staged = combined['items'][1]['task']
            staged_id = staged['task_id']
            image_row = staged['images'][0]
            previous_candidate = PublishedImage(**{k: image_row[k] for k in
                ('image_index','local_path','sha256','mime_type','bytes','width','height')}, revised_prompt=None)
            staged_row = await recovery._row(staged_id)
            def seed_previous_development_state(conn):
                conn.execute('DELETE FROM image_artifacts WHERE task_id=?',(staged_id,))
                conn.execute("UPDATE tasks SET status='materializing' WHERE task_id=?",(staged_id,))
                stage_static_size_mismatch(conn,staged_id,staged_row['revision'],[previous_candidate],staged_row['updated_at'])
            await db.run(seed_previous_development_state)
            before = len(calls)
            replayed = await client.call_tool_mcp('recover_task',{'task_id':staged_id})
            assert not replayed.isError and replayed.structuredContent['data']['status']=='succeeded'
            assert replayed.structuredContent['data']['size_mismatch']['code']=='SIZE_MISMATCH'
            assert len(calls)==before

            async def decline(message, response_type, params, context):
                from fastmcp.client.elicitation import ElicitResult
                return ElicitResult(action='decline')

            result=await client.call_tool_mcp('generate_image', {'request':{**d05,'idempotency_key':'legacy','prompt':'legacy-fixture'}})
            legacy=result.structuredContent['data']
            legacy_id=legacy['task_id']
            await db.run(lambda conn: (
                conn.execute('DELETE FROM image_artifacts WHERE task_id=?',(legacy_id,)),
                conn.execute("UPDATE tasks SET status='recovery_pending',error_category='ARTIFACT_UNAVAILABLE' WHERE task_id=?",(legacy_id,)),
            ))
            action={'task_id':legacy_id,'expected_status':'recovery_pending','reason':'fixture closure'}
            async with Client(create_server(backend), elicitation_handler=decline) as declining:
                assert (await declining.call_tool_mcp('close_task',action)).isError
            assert (await recovery._row(legacy_id))['status']=='recovery_pending'
            planned=await backend.call('__prepare_recovery__',{'action':'close_task','arguments':action})
            assert planned['ok']
            stale=planned['data']['plan_id']
            await db.run(lambda conn: conn.execute('UPDATE tasks SET revision=revision+1 WHERE task_id=?',(legacy_id,)))
            assert not (await backend.call('__execute_recovery__',{'plan_id':stale}))['ok']
            assert not (await client.call_tool_mcp('close_task',action)).isError
            assert (await client.call_tool_mcp('recover_task',{'task_id':legacy_id})).isError
            request={'task_id':legacy_id,'image_index':0}
            before=len(calls)
            inspected=await client.call_tool_mcp('inspect_closed_artifact',request)
            assert not inspected.isError
            candidate=inspected.structuredContent['data']
            assert candidate['evidence']=='legacy_unverified'
            destination=tmp_path/'legacy-export.png'
            copy={**request,'destination':str(destination),'sha256':candidate['sha256']}
            assert (await client.call_tool_mcp('export_closed_artifact',{**copy,'sha256':'0'*64})).isError
            assert not (await client.call_tool_mcp('export_closed_artifact',copy)).isError
            assert destination.read_bytes()==mismatched.getvalue()
            assert (await client.call_tool_mcp('export_closed_artifact',copy)).isError
            current=(await client.call_tool_mcp('get_task',{'task_id':legacy_id})).structuredContent['data']
            assert (current['status'],current['attempt_count'],current['idempotency_key'])==('closed',1,'legacy')
            local=Path(candidate['local_path'])
            local.write_bytes(b'broken')
            assert (await client.call_tool_mcp('inspect_closed_artifact',request)).isError
            local.unlink()
            assert (await client.call_tool_mcp('inspect_closed_artifact',request)).isError
            assert len(calls)==before
            sibling=tmp_path/'unmanaged.png'
            sibling.write_bytes(mismatched.getvalue())
            try:
                local.symlink_to(sibling)
            except OSError:
                pass
            else:
                assert (await client.call_tool_mcp('inspect_closed_artifact',request)).isError
                local.unlink()
            local.write_bytes(mismatched.getvalue())
            await db.run(lambda conn: (
                conn.execute('INSERT INTO image_artifacts(task_id,image_index,local_path,sha256,mime_type,bytes,width,height,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                             (legacy_id,0,str(sibling),candidate['sha256'],'image/png',len(mismatched.getvalue()),796,1024,1)),
            ))
            assert (await client.call_tool_mcp('inspect_closed_artifact',request)).isError
            await db.run(lambda conn: (
                conn.execute('UPDATE image_artifacts SET local_path=? WHERE task_id=?',(str(local),legacy_id)),
                conn.execute("INSERT INTO artifact_cleanup_events VALUES (?,?,?,?,?,?,?,NULL,'deleted',NULL,1,1)",
                             ('closed-cleanup',legacy_id,0,str(local),candidate['sha256'],len(mismatched.getvalue()),'manual')),
                conn.execute('INSERT INTO artifact_cleanup_status VALUES (?,?,?,?)',(legacy_id,0,1,'closed-cleanup')),
            ))
            assert (await client.call_tool_mcp('inspect_closed_artifact',request)).isError
            assert len(calls)==before


    finally:
        await scheduler.close(); await materializer.close(); await http_client.aclose(); await db.close()
        server.shutdown();server.server_close();thread.join()
