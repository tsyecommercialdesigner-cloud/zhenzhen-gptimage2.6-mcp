import pytest
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput, TemplateVariable
from zhenzhen_gptimage.prompts.templates import save_template, get_template, render_template, list_templates, TemplateConflict
from zhenzhen_gptimage.repository.database import connect, initialize
from zhenzhen_gptimage.prompts.guidance import PROMPT_GUIDE, RECOVERY_GUIDE, optimize_ecommerce_prompt
from pydantic import ValidationError

def test_create_update_render_and_search(tmp_path):
    db=connect(tmp_path/'db'); initialize(db)
    var=TemplateVariable(name='product',required=True)
    create=SaveTemplateInput(code='A',content='Show {{product}}',variables=[var])
    row=save_template(db,create,1)
    assert render_template(row,{'product':'cup'})['prompt']=='Show cup'
    with pytest.raises(TemplateConflict): save_template(db,create,2)
    same=create.model_copy(update={'expected_version':1})
    assert save_template(db,same,2)['version']==1
    changed=same.model_copy(update={'content':'New {{product}}'})
    assert save_template(db,changed,3)['version']==2
    with pytest.raises(TemplateConflict): save_template(db,changed,4)
    assert get_template(db,'A')['version']==2
    for code in ('B','C'):
        save_template(db,SaveTemplateInput(code=code,content='text',variables=[]),3)
    page,cursor=list_templates(db,limit=1)
    assert page[0]['code']=='A' and list_templates(db,limit=1,cursor=cursor)[0][0]['code']=='B'
    with pytest.raises(ValueError): list_templates(db,query='changed',cursor=cursor)
    db.close()

def test_render_no_expression_and_limits(tmp_path):
    db=connect(tmp_path/'db');initialize(db)
    with pytest.raises(ValueError): save_template(db,SaveTemplateInput(code='a',content='{{x.__class__}}',variables=[]),1)
    row=save_template(db,SaveTemplateInput(code='b',content='{{x}}',variables=[TemplateVariable(name='x',required=True)]),1)
    with pytest.raises(ValueError): render_template(row,{})
    with pytest.raises(ValueError): render_template(row,{'x':'a','extra':'b'})
    with pytest.raises(ValueError): render_template(row,{'x':'中'*11000})
    db.close()

def test_invalid_template_code():
    with pytest.raises(ValidationError):
        SaveTemplateInput(code='bad code',content='x',variables=[])

def test_guidance_includes_unknown_facts_and_chat_limit():
    assert '不可定制' in PROMPT_GUIDE and '未知' in PROMPT_GUIDE
    assert 'unknown' in RECOVERY_GUIDE and 'recover_task' in RECOVERY_GUIDE
    assert '杯子' in optimize_ecommerce_prompt('展示杯子','材质未知','主图')
