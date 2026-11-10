from io import BytesIO
import pytest
from PIL import Image
from zhenzhen_gptimage.artifacts.formats import inspect_svg, inspect_gif
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer, ImageResultError, ImageDownloadError
import asyncio, base64, json, hashlib

def gif_bytes():
    out=BytesIO(); frames=[Image.new('RGB',(16,16),color) for color in ('red','blue')]
    frames[0].save(out,format='GIF',save_all=True,append_images=frames[1:],duration=[120,200],loop=0)
    return out.getvalue()

def test_gif_validates_all_frames_and_metadata():
    raw=gif_bytes();w,h,meta=inspect_gif(raw)
    assert (w,h)==(16,16) and meta=={'frame_count':2,'durations_ms':[120,200],'loop':0}
    with Image.open(BytesIO(raw)) as im:
        im.seek(0);first=im.convert('RGB').getpixel((0,0));im.seek(1);second=im.convert('RGB').getpixel((0,0))
        assert first!=second

def test_svg_valid_and_viewbox():
    raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><path d="M0 0" fill="red"/></svg>'
    assert inspect_svg(raw)==(100,80,{})
    accessible=b'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" role="img" aria-labelledby="title"><title id="title">Cup</title><path d="M0 0"/></svg>'
    assert inspect_svg(accessible)==(1024,1024,{})

@pytest.mark.parametrize('raw',[
    b'<!DOCTYPE svg [<!ENTITY x "x">]><svg width="2" height="2"/>',
    b'<svg width="2" height="2"><script/></svg>',
    b'<svg width="2" height="2"><path onload="x"/></svg>',
    b'<svg width="2" height="2"><path fill="url(http://example.com/a)"/></svg>',
    b'<svg width="2" height="2"><foreignObject/></svg>',
    b'<svg width="2" height="2"><image href="data:x"/></svg>',
])
def test_svg_rejects_active_and_external_content(raw):
    with pytest.raises(ValueError): inspect_svg(raw)

def test_gif_rejects_static_and_damaged():
    out=BytesIO();Image.new('RGB',(16,16)).save(out,format='GIF')
    with pytest.raises(ValueError): inspect_gif(out.getvalue())
    with pytest.raises((ValueError,OSError)): inspect_gif(gif_bytes()[:40])

def test_gif_rejects_more_than_sixteen_frames():
    out=BytesIO();frames=[Image.new('RGB',(16,16),(i*10,0,0)) for i in range(17)]
    frames[0].save(out,format='GIF',save_all=True,append_images=frames[1:],duration=100,loop=0)
    with pytest.raises(ValueError): inspect_gif(out.getvalue())

def test_svg_rejects_depth_and_bytes_limits():
    deep=('<svg width="10" height="10">'+'<g>'*129+'</g>'*129+'</svg>').encode()
    with pytest.raises(ValueError): inspect_svg(deep)
    with pytest.raises(ValueError): inspect_svg(b' '* (8*1024*1024+1))

@pytest.mark.asyncio
@pytest.mark.parametrize('fmt', ['gif','svg'])
async def test_materializer_saves_original_and_metadata(tmp_path,fmt):
    raw=gif_bytes() if fmt=='gif' else b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16"/></svg>'
    response=json.dumps({'data':[{'b64_json':base64.b64encode(raw).decode()}]}).encode()
    m=ArtifactMaterializer(tmp_path)
    try:
        imgs=await m.materialize('ab12',response,channel='images',expected_size=(16,16),deadline=asyncio.get_running_loop().time()+5,expected_format=fmt)
        assert __import__('pathlib').Path(imgs[0].local_path).read_bytes()==raw
        assert imgs[0].sha256==hashlib.sha256(raw).hexdigest()
        assert imgs[0].local_path.endswith('.'+fmt)
        if fmt=='gif': assert imgs[0].metadata['frame_count']==2
        with pytest.raises(ImageResultError):
            await m.materialize('ab13',response,channel='images',expected_size=(16,16),deadline=asyncio.get_running_loop().time()+5,expected_format='svg' if fmt=='gif' else 'gif')
    finally: await m.close()

@pytest.mark.asyncio
async def test_new_format_download_failure_never_publishes(tmp_path):
    import httpx
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(lambda request:httpx.Response(503)))
    try:
        raw=json.dumps({'data':[{'url':'https://example.test/output'}]}).encode()
        with pytest.raises(ImageDownloadError):
            await m.materialize('a123',raw,channel='images',expected_size=None,deadline=asyncio.get_running_loop().time()+5,expected_format='gif')
        assert not list(tmp_path.glob('images/*'))
    finally: await m.close()

@pytest.mark.asyncio
async def test_mcp_new_formats_and_explicit_mismatch_acceptance(tmp_path):
    import httpx
    from pathlib import Path
    from fastmcp import Client
    from zhenzhen_gptimage.bootstrap.config import Limits
    from zhenzhen_gptimage.repository.worker import DatabaseWorker
    from zhenzhen_gptimage.providers.t8_star.client import T8StarClient
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    from zhenzhen_gptimage.scheduler.engine import Scheduler
    from zhenzhen_gptimage.generation.admission import Admission
    from zhenzhen_gptimage.generation.service import GenerationService
    from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
    from zhenzhen_gptimage.mcp_api.server import create_server
    gif=gif_bytes();svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"><rect width="10" height="10"/></svg>'
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        raw=gif if body['output_format']=='gif' else svg
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(raw).decode()}]})
    http=httpx.AsyncClient(transport=httpx.MockTransport(handler)); db=DatabaseWorker(tmp_path/'state.db')
    limits=Limits(free_disk_bytes=1); m=ArtifactMaterializer(tmp_path,limits=limits)
    locks=TaskLocks(); s=Scheduler(db,T8StarClient(http,'test'),tmp_path,m,task_locks=locks)
    recovery=RecoveryService(db,m,tmp_path,locks); admission=Admission(db,tmp_path,limits,formats_enabled=True)
    backend=ServiceBackend(db,GenerationService(admission,s),recovery)
    try:
        async with Client(create_server(backend)) as client:
            result=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'svg','family':'flare','prompt':'icon','width':1024,'height':1024,'output_format':'svg'}})
            assert not result.isError
            img=result.structuredContent['data']['images'][0]
            assert Path(img['local_path']).read_bytes()==svg and calls[0]['svg']['model']=='gpt-6-luna'
            svg_task=result.structuredContent['data']['task_id']
            Path(img['local_path']).unlink()
            unavailable=await client.call_tool_mcp('get_image',{'task_id':svg_task})
            assert unavailable.isError and len(calls)==1
            result=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'gif','family':'flare','prompt':'bounce','width':512,'height':512,'output_format':'gif'}})
            assert result.isError
            task=result.structuredContent['data']; assert task['status']=='recovery_pending' and task['attempt_count']==1
            img=task['images'][0]; assert img['metadata']['frame_count']==2 and Path(img['local_path']).read_bytes()==gif
            recovered=await client.call_tool_mcp('recover_task',{'task_id':task['task_id']})
            assert recovered.structuredContent['data']['status']=='recovery_pending' and len(calls)==2
            args={'task_id':task['task_id'],'sha256':img['sha256'],'width':16,'height':16}
            Path(img['local_path']).write_bytes(b'tampered')
            assert (await client.call_tool_mcp('accept_gif_size',args)).isError
            Path(img['local_path']).write_bytes(gif)
            accepted=await client.call_tool_mcp('accept_gif_size',args)
            assert not accepted.isError and accepted.structuredContent['data']['status']=='succeeded'
            assert not (await client.call_tool_mcp('accept_gif_size',args)).isError
            assert len(calls)==2
            wrong=await client.call_tool_mcp('accept_gif_size',{**args,'width':17})
            assert wrong.isError
            auto=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'gif2','family':'flare','prompt':'bounce','width':512,'height':512,'output_format':'gif','size_policy':'accept_actual'}})
            assert not auto.isError and auto.structuredContent['data']['images'][0]['width']==16
            assert any('实际尺寸' in w for w in auto.structuredContent['warnings'])
            conflict=await client.call_tool_mcp('generate_image',{'request':{'idempotency_key':'gif2','family':'flare','prompt':'bounce','width':512,'height':512,'output_format':'gif','size_policy':'strict'}})
            assert conflict.isError and len(calls)==3
    finally:
        await s.close();await m.close();await http.aclose();await db.close()
