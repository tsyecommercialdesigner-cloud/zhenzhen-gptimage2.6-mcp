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
