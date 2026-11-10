import pytest
from pydantic import ValidationError
from zhenzhen_gptimage.generation.models import GenerationRequest, CHAT_WARNING, validate_actual_dimensions
from zhenzhen_gptimage.generation.snapshot import create_snapshot, input_digest, resolve_existing_or_create, IdempotencyConflict

def req(**changes):
    return GenerationRequest.model_validate({'idempotency_key':'a', 'family':'flare', 'prompt':'mug', **changes})

@pytest.mark.parametrize(('edge','suffix'),[(1024,''),(1025,'-2k'),(2048,'-2k'),(2049,'-4k'),(4096,'-4k')])
def test_routing(edge,suffix):
    for channel in ('images','flux'):
        r=req(channel=channel,width=edge,height=512)
        assert r.resolved_model() == 'gpt-image-2.6-flare'+suffix
        assert r.model_copy().channel == channel

def test_chat_and_default():
    assert req(width=512,height=512).channel == 'images'
    r=req(channel='chat')
    assert r.resolved_model() == 'gpt-image-2.6-flare'
    assert r.warnings() == [CHAT_WARNING] and validate_actual_dimensions(r, 100, 200)
    assert req(channel='chat',explicit_model='gpt-image-2.6-flare-4k').resolved_model().endswith('-4k')

@pytest.mark.parametrize('changes',[{'width':4097,'height':2},{'width':2},{'channel':'chat','width':2}, {'width':2,'height':2,'explicit_model':'gpt-image-2.6-sunburst'}, {'width':2,'height':2,'unknown':1},{'width':2,'height':2,'template_code':'x'}, {'width':2,'height':2,'template_variables':{}}, {'channel':'flux','width':2,'height':2,'references':[{'local_path':'x'}]}])
def test_invalid(changes):
    with pytest.raises(ValidationError): req(**changes)

def test_snapshot_canonical_and_immutable():
    a=GenerationRequest(idempotency_key='a',family='flare',width=512,height=512,template_code='sku',template_variables={'x':'1','y':'2'})
    b=GenerationRequest(idempotency_key='b',family='flare',width=512,height=512,template_code='sku',template_variables={'y':'2','x':'1'})
    assert input_digest(a)==input_digest(b)
    snap=create_snapshot(a,final_prompt='old',reference_hashes=(),template_version=1)
    later=create_snapshot(b,final_prompt='new',reference_hashes=(),template_version=2)
    assert snap.prompt=='old' and snap.template_version==1 and snap.resolved_digest != later.resolved_digest
    with pytest.raises(ValidationError): snap.prompt='changed'

def test_reuse_never_reads_changed_input(tmp_path):
    image = tmp_path / 'reference.png'
    image.write_bytes(b'original')
    r = GenerationRequest(idempotency_key='key', family='flare', width=512, height=512,
                          template_code='sku', references=[{'local_path':str(image)}])
    old = create_snapshot(r, final_prompt='old template', template_version=1, reference_hashes=('a'*64,))
    image.write_bytes(b'changed')
    def forbidden():
        raise AssertionError('must not re-read mutable files or templates')
    found, reused = resolve_existing_or_create(r, existing=old, build=forbidden)
    assert reused and found is old and found.prompt == 'old template'
    altered = r.model_copy(update={'width':1024})
    with pytest.raises(IdempotencyConflict): resolve_existing_or_create(altered, existing=old, build=forbidden)

@pytest.mark.parametrize(('w','h'),[(768,512),(1024,512),(960,960)])
def test_gif_dimensions_from_contract(w,h):
    assert req(width=w,height=h,output_format='gif',frame_count=4,frame_duration_ms=120)

@pytest.mark.parametrize('changes',[
    {'width':1024,'height':1024,'output_format':'gif','frame_count':4},
    {'width':512,'height':512,'output_format':'svg'},
    {'width':768,'height':512,'output_format':'gif','frame_duration_ms':125},
    {'width':1024,'height':1024,'output_format':'svg','references':[{'local_path':'a'}]},
    {'width':1024,'height':1024,'output_format':'svg','mask_url':'https://example.test/mask.png'},
    {'width':1024,'height':1024,'output_format':'svg','markup_url':'https://example.test/markup.png'},
])
def test_new_format_invalid_inputs(changes):
    with pytest.raises(ValidationError): req(**changes)

def test_legacy_digest_uses_original_fields():
    from zhenzhen_gptimage.generation.snapshot import _digest
    r=req(width=1024,height=1024)
    fields=r.model_dump(exclude={'idempotency_key','provider','output_format','size','size_policy','frame_count','frame_duration_ms','svg_model','svg_reasoning_effort','execution_mode'},mode='json')
    assert input_digest(r)==_digest(fields)

def test_new_format_auto_size_has_no_fake_dimensions():
    r=req(output_format='gif',size='auto')
    assert r.width is None and r.height is None and r.resolved_model()=='gpt-image-2.6-flare'
    with pytest.raises(ValidationError): req(output_format='gif',size='auto',width=512,height=512)
    assert req(output_format='gif').size == 'auto'
    p=req(output_format='svg',size='1024x1024')
    assert (p.width,p.height,p.size)==(1024,1024,None)
    assert req(output_format='gif',width=512,height=1024,frame_count=4)

def test_new_format_snapshot_and_digest_freeze_parameters():
    r=req(output_format='gif',size='auto',frame_count=4,frame_duration_ms=120,size_policy='accept_actual')
    s=create_snapshot(r,final_prompt='mug',reference_hashes=())
    assert s.snapshot_version==2 and s.output_format=='gif' and s.size=='auto'
    assert s.frame_count==4 and s.size_policy=='accept_actual'
    assert input_digest(r)!=input_digest(r.model_copy(update={'frame_count':5}))
    restored=type(s).model_validate_json(s.model_dump_json())
    assert restored==s

@pytest.mark.parametrize('provider',['t8-star'])
def test_format_constraints_apply_before_any_provider_request(provider):
    assert req(provider=provider,output_format='gif',width=768,height=512,frame_count=4)
    with pytest.raises(ValidationError):
        req(provider=provider,output_format='gif',width=1024,height=1024,frame_count=4)
    with pytest.raises(ValidationError):
        req(provider=provider,output_format='svg',width=512,height=512)
