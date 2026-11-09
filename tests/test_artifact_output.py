import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
import httpx
from PIL import Image
import pytest
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer, ImageResultError, ImageDownloadError
from zhenzhen_gptimage.artifacts.storage import ResourceLimitError
from zhenzhen_gptimage.bootstrap.config import Limits

def png(size=(8,8)):
    result=BytesIO(); Image.new('RGB',size,'blue').save(result,format='PNG'); return result.getvalue()

def raw(*images):
    return json.dumps({'data':list(images)}).encode()

@pytest.mark.asyncio
async def test_redirect_download_never_sends_auth_or_cookies(tmp_path):
    seen=[]
    def handler(request):
        seen.append((str(request.url),dict(request.headers)))
        if request.url.host == 'first.test':
            return httpx.Response(302,headers={'location':'https://second.test/image','set-cookie':'token=secret'},request=request)
        return httpx.Response(200,content=png(),request=request)
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(handler))
    try:
        result=await m.materialize('abcd',raw({'url':'https://first.test/image'}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
        assert Path(result[0].local_path).read_bytes()==png()
        assert len(seen)==2 and all('authorization' not in h and 'cookie' not in h for _,h in seen)
    finally: await m.close()

@pytest.mark.asyncio
async def test_three_attempts_and_redirect_limit(tmp_path):
    calls=[]
    def failing(request):
        calls.append(request)
        raise httpx.ConnectError('unavailable',request=request)
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(failing))
    try:
        with pytest.raises(ImageDownloadError):
            await m.materialize('abcd',raw({'url':'https://example.test/image'}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
    finally: await m.close()
    assert len(calls)==3

@pytest.mark.asyncio
async def test_redirect_loop_and_invalid_scheme(tmp_path):
    def redirect(request):
        return httpx.Response(302,headers={'location':'/next'},request=request)
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(redirect))
    try:
        with pytest.raises(ImageResultError, match='redirect'):
            await m.materialize('abcd',raw({'url':'https://example.test/image'}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
        with pytest.raises(ImageResultError, match='URL'):
            await m._download('http://user:password@example.test',asyncio.get_running_loop().time()+5)
    finally: await m.close()

@pytest.mark.asyncio
async def test_complete_validation_chat_and_dimension_mismatch(tmp_path):
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(lambda r: httpx.Response(200,content=png(),request=r)))
    try:
        encoded=base64.b64encode(png()).decode()
        with pytest.raises(ImageResultError) as exc:
            await m.materialize('abcd',raw({'b64_json':encoded}),channel='images',expected_size=(16,8),deadline=asyncio.get_running_loop().time()+5)
        assert len(exc.value.artifacts)==1 and Path(exc.value.artifacts[0].local_path).exists()
        with pytest.raises(ImageResultError) as repeated:
            await m.materialize('abcd',raw({'b64_json':encoded}),channel='images',expected_size=(16,8),deadline=asyncio.get_running_loop().time()+5)
        assert repeated.value.artifacts == exc.value.artifacts
        chat=json.dumps({'choices':[{'message':{'content':'![x](https://example.test/x)'}}]}).encode()
        result=await m.materialize('abce',chat,channel='chat',expected_size=None,deadline=asyncio.get_running_loop().time()+5)
        assert (result[0].width,result[0].height)==(8,8)
        with pytest.raises(ImageResultError):
            await m.materialize('abcf',raw({'b64_json':encoded},{'b64_json':base64.b64encode(b'bad').decode()}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
        assert not list((tmp_path/'images').glob('abcf.*'))
    finally: await m.close()

@pytest.mark.asyncio
async def test_limits_and_write_failure(tmp_path, monkeypatch):
    m=ArtifactMaterializer(tmp_path,limits=Limits(output_bytes=20,output_total_bytes=20),transport=httpx.MockTransport(lambda r: httpx.Response(200,content=png(),request=r)))
    try:
        with pytest.raises(ResourceLimitError):
            await m.materialize('abcd',raw({'url':'https://example.test/x'}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
    finally: await m.close()
    m=ArtifactMaterializer(tmp_path,transport=httpx.MockTransport(lambda r: httpx.Response(200,content=png(),request=r)))
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr('zhenzhen_gptimage.artifacts.output.os.link',fail)
    try:
        with pytest.raises(OSError):
            await m.materialize('abce',raw({'b64_json':base64.b64encode(png()).decode()}),channel='images',expected_size=(8,8),deadline=asyncio.get_running_loop().time()+5)
        assert not list((tmp_path/'images').glob('abce.*'))
    finally: await m.close()
