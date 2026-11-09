import pytest
from pydantic import ValidationError
from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS, Result, ErrorDetail, ErrorCode, TaskLookupInput, SaveTemplateInput

EXPECTED = {
    'get_capabilities': set(), 'generate_image': {'request'}, 'generate_batch': {'requests'},
    'get_task': {'task_id','idempotency_key'}, 'list_tasks': {'status','batch_id','model','created_from','created_to','limit','cursor'},
    'get_image': {'task_id','image_index','include_preview'}, 'recover_task': {'task_id'},
    'close_task': {'task_id','expected_status','reason'}, 'save_prompt_template': {'code','content','variables','expected_version'},
    'get_prompt_template': {'code'}, 'list_prompt_templates': {'query','limit','cursor'},
    'render_prompt_template': {'code','variables'},
}

def test_input_schema_matches_approved_signatures():
    assert set(TOOL_INPUTS) == set(EXPECTED)
    for name, model in TOOL_INPUTS.items():
        schema = model.model_json_schema()
        assert set(schema['properties']) == EXPECTED[name]
        assert schema['additionalProperties'] is False

def test_result_and_invalid_templates():
    assert Result[str](ok=True, data='ok').warnings == []
    error=ErrorDetail(code=ErrorCode.NOT_FOUND,message='missing',retryable=False,next_action='check')
    assert Result[str](ok=False,error=error).error.code == 'NOT_FOUND'
    with pytest.raises(ValidationError): Result[str](ok=True,error=error)
    with pytest.raises(ValidationError): TaskLookupInput()
    with pytest.raises(ValidationError): SaveTemplateInput(code='x',content='x',variables=[{'name':'a','required':True},{'name':'a','required':True}])
