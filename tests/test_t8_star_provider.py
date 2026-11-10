import base64
import hashlib
import json
import ssl
import httpx
import pytest
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.models import MODELS
from zhenzhen_gptimage.generation.snapshot import create_snapshot
from zhenzhen_gptimage.providers.t8_star.client import (
    ProviderError, T8StarClient, build_request, parse_response, classify_exception,
    classify_http_status,
)

PNG = b'\x89PNG\r\n\x1a\nexample'
PNG_HASH = hashlib.sha256(PNG).hexdigest()

def snapshot(channel='images', *, with_image=False, family='flare', width=1024, height=1024):
    args = dict(idempotency_key='id', channel=channel, family=family, prompt='mug')
    if channel != 'chat': args.update(width=width, height=height)
    if with_image: args['references'] = [{'local_path':'not-uploaded.png'}]
    request = GenerationRequest(**args)
    return create_snapshot(request, final_prompt='mug', reference_hashes=(PNG_HASH,) if with_image else ())

def test_images_png_and_flux_mapping():
    path, data = build_request(snapshot(with_image=True), (PNG,))
    assert path == '/v1/images/generations'
    assert set(data) == {'model','prompt','size','image'}
    assert data['image'][0] == 'data:image/png;base64,' + base64.b64encode(PNG).decode()
    assert 'not-uploaded.png' not in json.dumps(data)
    path, data = build_request(snapshot('flux'))
    assert set(data) == {'model','prompt','size'}
    assert path == '/v1/images/generations'
    with pytest.raises(ValueError): build_request(snapshot(with_image=True).model_copy(update={'channel':'flux'}), (PNG,))
    with pytest.raises(ValueError): build_request(snapshot(with_image=True), (PNG+b'changed',))

def test_chat_text_and_image():
    path, body = build_request(snapshot('chat'))
    assert path == '/v1/chat/completions'
    assert body == {'model':'gpt-image-2.6-flare','messages':[{'role':'user','content':'mug'}],'stream':False}
    _, body = build_request(snapshot('chat',with_image=True), (PNG,))
    assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert 'size' not in body and 'tools' not in body

def test_result_parsing_and_redaction():
    result=parse_response('images',json.dumps({'data':[{'b64_json':'bad!', 'url':'https://files.test/i?token=private'}],'usage':{'total_tokens':1}}).encode())
    assert result.images[0].base64_invalid and result.images[0].url
    chat = parse_response('chat', b'{"choices":[{"message":{"content":"![a](https://example.com/i) [download](https://example.com/i) ![b](https://example.com/i)"}}]}')
    assert len(chat.images) == 1
    for raw in (b'{}', b'{"data":[]}', b'{"data":[{"b64_json":"!!!"}]}'):
        with pytest.raises(ProviderError, match='RESPONSE_INVALID'): parse_response('images', raw)
    with pytest.raises(ProviderError): parse_response('chat', b'{"choices":[{"message":{"content":"hello"}}]}')

def test_error_categories():
    for code in (400,401,403,422): assert classify_http_status(code).category == 'PROVIDER_REJECTED'
    for code in (429,500,503): assert classify_http_status(code).category == 'SUBMISSION_UNKNOWN'
    assert classify_exception(httpx.ConnectTimeout('x')).safe_retry
    assert not classify_exception(httpx.ReadTimeout('x')).safe_retry
    e = httpx.ConnectError('tls'); e.__cause__ = ssl.SSLError('cert')
    assert classify_exception(e).category == 'CONFIG_ERROR'

@pytest.mark.parametrize(('exc','category','retry'),[
    (httpx.ConnectError('offline'), 'CONNECT_NOT_SENT', True),
    (httpx.ConnectTimeout('timeout'), 'CONNECT_NOT_SENT', True),
    (httpx.PoolTimeout('busy'), 'CONNECT_NOT_SENT', True),
    (httpx.WriteTimeout('partial'), 'SUBMISSION_UNKNOWN', False),
    (httpx.ReadTimeout('response'), 'SUBMISSION_UNKNOWN', False),
    (httpx.RemoteProtocolError('broken'), 'SUBMISSION_UNKNOWN', False),
    (TimeoutError('total deadline'), 'SUBMISSION_UNKNOWN', False),
])
def test_error_categories_transport(exc, category, retry):
    result = classify_exception(exc)
    assert (result.category, result.safe_retry) == (category, retry)

@pytest.mark.parametrize('channel',['images','flux','chat'])
def test_rejects_foreign_model_and_oversized_prompt(channel):
    snap = snapshot(channel)
    with pytest.raises(ValueError): build_request(snap.model_copy(update={'resolved_model':'flux-dev'}))
    with pytest.raises(ValueError): build_request(snap.model_copy(update={'prompt':'a'*32769}))

def test_images_base64_priority_and_empty_behavior():
    result = parse_response('images', json.dumps({'data':[{'b64_json':base64.b64encode(PNG).decode(), 'url':'https://files.test/i'}]}).encode())
    assert result.images[0].data == PNG
    fallback = parse_response('images', json.dumps({'data':[{'b64_json':'', 'url':'https://files.test/i'}]}).encode())
    assert fallback.images[0].data is None and fallback.images[0].url == 'https://files.test/i'
    with pytest.raises(ProviderError): parse_response('images', b'{"data":[{"b64_json":""}]}')

@pytest.mark.parametrize('model', MODELS)
def test_flux_supports_only_the_six_routed_model_ids(model):
    family = 'sunburst' if 'sunburst' in model else 'flare'
    edge = 4096 if model.endswith('-4k') else 2048 if model.endswith('-2k') else 1024
    _, body = build_request(snapshot('flux', family=family, width=edge, height=1024))
    expected = 'gpt-image-2.6-flare' if model == 'gpt-image-2.6-flare-4k' else model
    assert body['model'] == expected and set(body) == {'model','prompt','size'}

@pytest.mark.parametrize('channel', ['images', 'flux'])
def test_flare_4k_wire_mapping_preserves_internal_model(channel):
    snap = snapshot(channel, family='flare', width=3840, height=2160)
    _, body = build_request(snap)
    assert snap.resolved_model == 'gpt-image-2.6-flare-4k'
    assert body['model'] == 'gpt-image-2.6-flare'
    assert body['size'] == '3840x2160'

@pytest.mark.asyncio
async def test_one_request_and_limited_response():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data':[{'url':'https://cdn.test/i'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = T8StarClient(client,'test-key')
        result = await provider.generate(snapshot(), remaining_seconds=3)
        assert parse_response('images',result).images[0].url == 'https://cdn.test/i'
        assert len(calls)==1 and calls[0].headers['authorization']=='Bearer test-key'
        assert 'async=' not in str(calls[0].url) and '/tasks/' not in str(calls[0].url)
        with pytest.raises(ProviderError, match='RESPONSE_INVALID'):
            await T8StarClient(client,'test-key',response_limit=4).generate(snapshot(), remaining_seconds=3)

@pytest.mark.asyncio
async def test_stream_counts_decompressed_bytes_and_sends_once():
    import gzip
    calls=[]; chunks=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=gzip.compress(b'A'*100), headers={'Content-Encoding':'gzip'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=T8StarClient(client,'test-key',response_limit=50)
        async def sink(data): chunks.append(data)
        with pytest.raises(ProviderError,match='RESPONSE_INVALID'):
            await provider.generate_stream(snapshot(),remaining_seconds=3,write_chunk=sink)
    assert len(calls)==1 and sum(map(len,chunks))<=50

@pytest.mark.asyncio
async def test_stream_forwards_chunks_without_internal_retry():
    calls=[]; chunks=[]
    class Streaming(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'first'
            yield b'second'
    def handler(request):
        calls.append(request)
        return httpx.Response(200,stream=Streaming())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def sink(data): chunks.append(data)
        await T8StarClient(client,'test-key').generate_stream(snapshot(),remaining_seconds=3,write_chunk=sink)
    assert chunks==[b'first',b'second'] and len(calls)==1
def test_new_format_wire_fields():
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot
    from zhenzhen_gptimage.providers.t8_star.client import build_request
    svg=GenerationRequest(idempotency_key='s',family='flare',width=1024,height=1024,prompt='icon',output_format='svg',svg_model='gpt-6-luna')
    path, body=build_request(create_snapshot(svg,final_prompt='icon',reference_hashes=()))
    assert path=='/v1/images/generations'
    assert body['output_format']=='svg' and body['svg']=={'model':'gpt-6-luna'} and body['n']==1
    gif=GenerationRequest(idempotency_key='g',family='flare',size='auto',prompt='ball',output_format='gif',frame_count=4,frame_duration_ms=120)
    _, body=build_request(create_snapshot(gif,final_prompt='ball',reference_hashes=()))
    assert 'size' not in body and 'aspect_ratio' not in body
    assert body['output_format']=='gif' and body['frame_count']==4 and body['frame_duration_ms']==120
    ratio=GenerationRequest(idempotency_key='r',family='flare',size='16:9',prompt='ball',output_format='gif')
    _, body=build_request(create_snapshot(ratio,final_prompt='ball',reference_hashes=()))
    assert body['aspect_ratio']=='16:9' and 'size' not in body
