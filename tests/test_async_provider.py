import json
import httpx
import pytest
from pydantic import ValidationError
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.snapshot import create_snapshot, input_digest
from zhenzhen_gptimage.providers.t8_star.client import T8StarClient, ProviderError, parse_async_status

def request(**kw):
    data=dict(idempotency_key='a',family='flare',width=512,height=512,prompt='ball',output_format='gif')
    data.update(kw)
    return GenerationRequest(**data)

def test_async_scope_and_fingerprints():
    sync=request(); explicit=request(execution_mode='sync'); async_req=request(execution_mode='async')
    assert input_digest(sync)==input_digest(explicit)!=input_digest(async_req)
    assert create_snapshot(async_req,final_prompt='ball',reference_hashes=()).execution_mode=='async'
    for params in (dict(family='sunburst'),dict(channel='flux'),dict(output_format='svg'),dict(width=2048,height=1024)):
        with pytest.raises(ValidationError): request(execution_mode='async',**params)

@pytest.mark.asyncio
async def test_async_wire_submission_and_query():
    calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='POST': return httpx.Response(200,json={'task_id':'remote-123'})
        return httpx.Response(200,json={'data':{'task_id':'remote-123','status':'SUCCESS','data':{'data':[{'url':'https://cdn.test/image.gif'}]}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client=T8StarClient(http,'secret')
        snap=create_snapshot(request(execution_mode='async'),final_prompt='ball',reference_hashes=())
        task_id=await client.submit_async(snap,remaining_seconds=10)
        status, result=await client.query_async(task_id,remaining_seconds=10)
    assert task_id=='remote-123' and status=='SUCCESS'
    assert json.loads(result)['data'][0]['url']=='https://cdn.test/image.gif'
    assert str(calls[0].url)=='https://ai.t8star.org/v1/images/generations?async=true'
    assert calls[1].url.path=='/v1/images/tasks/remote-123'
    assert [r.method for r in calls]==['POST','GET']

@pytest.mark.parametrize('body',[{}, {'data':{'task_id':'other','status':'SUCCESS'}}, {'data':{'task_id':'id','status':'SURPRISE'}}])
def test_async_unknown_response_fails_closed(body):
    with pytest.raises(ProviderError): parse_async_status(json.dumps(body).encode(),'id')
