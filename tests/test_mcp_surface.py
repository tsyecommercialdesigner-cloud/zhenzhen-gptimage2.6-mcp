import json
import pytest
from jsonschema import Draft202012Validator
from fastmcp import Client
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS
from zhenzhen_gptimage.mcp_api.contract_guidance import describe_schema, add_conditional_constraints
from zhenzhen_gptimage.prompts.guidance import TOOL_EXAMPLES

def test_documented_examples_validate_without_provider():
    for key, example in TOOL_EXAMPLES.items():
        tool = 'generate_image' if key in {'reference', 'gif', 'svg'} else key
        TOOL_INPUTS[tool].model_validate(example)

@pytest.mark.parametrize('name,cases', [
    ('get_task', [{}, {'task_id':'t'}, {'idempotency_key':'k'}, {'task_id':None,'idempotency_key':'k'}, {'task_id':'t','idempotency_key':'k'}]),
    ('preview_cleanup', [{}, {'before':'2026-01-01T00:00:00Z'}, {'keep_latest':0}, {'before':None,'keep_latest':1}, {'before':'2026-01-01T00:00:00Z','keep_latest':1}]),
    ('generate_image', [{'request': {'idempotency_key':'k','family':'flare','width':1024,'height':1024, **extra}} for extra in ({}, {'prompt':'x'}, {'template_code':'t'}, {'prompt':None,'template_code':'t'}, {'prompt':'x','template_code':'t'})]),
])
def test_conditional_schema_matches_model(name, cases):
    schema = add_conditional_constraints(name, describe_schema(TOOL_INPUTS[name].model_json_schema()))
    for args in cases:
        try:
            TOOL_INPUTS[name].model_validate(args)
            accepted = True
        except ValueError:
            accepted = False
        if accepted:
            assert Draft202012Validator(schema).is_valid(args)

def test_schema_accepts_supported_generation_combinations():
    base = {'idempotency_key':'key', 'family':'flare'}
    samples = [
        {'prompt':'x','width':2048,'height':1024,'explicit_model':'gpt-image-2.6-flare-2k'},
        {'template_code':'sku','template_variables':{'item':'cup'},'width':1024,'height':1024},
        {'prompt':'x','channel':'chat'},
        {'prompt':'x','channel':'flux','width':1024,'height':1024},
        {'prompt':'x','output_format':'gif','size':'auto'},
        {'prompt':'x','output_format':'gif','width':512,'height':512,'execution_mode':'async'},
        {'prompt':'x','output_format':'svg','size':'auto'},
    ]
    schema = add_conditional_constraints('generate_image', describe_schema(TOOL_INPUTS['generate_image'].model_json_schema()))
    for sample in samples:
        args = {'request': {**base, **sample}}
        TOOL_INPUTS['generate_image'].model_validate(args)
        assert Draft202012Validator(schema).is_valid(args)

@pytest.mark.asyncio
async def test_invalid_arguments_are_sanitized_before_sdk_or_backend(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    class Backend:
        calls = 0
        async def call(self, name, args):
            self.calls += 1
            raise AssertionError('invalid request reached backend')
    backend = Backend()
    cases = [
        ('get_capabilities', {'SECRET_KEY_SENTINEL':'SECRET_VALUE_SENTINEL'}),
        ('get_image', {'task_id':['SECRET_VALUE_SENTINEL']}),
        ('get_image', {}),
        ('get_image', {'task_id':'t', 'image_index':99}),
        ('close_task', {'task_id':'t', 'expected_status':'not-a-status', 'reason':'x'}),
        ('generate_image', {'request': {'idempotency_key':'k','family':'flare','prompt':'SECRET_VALUE_SENTINEL','template_code':'x','width':1024,'height':1024}}),
        ('generate_batch', {'requests':[{'idempotency_key':'k','family':'flare','prompt':'SECRET_VALUE_SENTINEL','width':1024,'height':1024,'references':[{'local_path':'SECRET_PATH_SENTINEL','SECRET_KEY_SENTINEL':'x'}]}]}),
    ]
    async with Client(create_server(backend)) as client:
        for name, args in cases:
            result = await client.call_tool_mcp(name, args)
            assert result.isError and result.structuredContent['error']['code'] == 'INVALID_ARGUMENT'
            assert 'SECRET_' not in str(result)
        mutually_exclusive = await client.call_tool_mcp('generate_image', cases[-2][1])
        assert 'prompt' in mutually_exclusive.structuredContent['error']['message']
        assert 'template_code' in mutually_exclusive.structuredContent['error']['message']
    assert backend.calls == 0
    assert 'SECRET_' not in caplog.text

@pytest.mark.asyncio
async def test_dispatch_and_sdk_return_consistent_validation_errors():
    app = create_server()
    tool = await app.get_tool('get_task')
    direct = (await tool.fn()).to_mcp_result()
    async with Client(app) as client:
        protocol = await client.call_tool_mcp('get_task', {})
    assert direct.isError and protocol.isError
    assert direct.structuredContent == protocol.structuredContent

@pytest.mark.asyncio
async def test_discovery_and_fail_closed():
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == set(TOOL_INPUTS)
        for tool in tools:
            assert tool.inputSchema == add_conditional_constraints(tool.name, describe_schema(TOOL_INPUTS[tool.name].model_json_schema()))
            assert tool.description
            def check_descriptions(node):
                if isinstance(node, dict):
                    for prop in node.get('properties', {}).values():
                        assert prop.get('description')
                    for child in node.values():
                        check_descriptions(child)
                elif isinstance(node, list):
                    for child in node:
                        check_descriptions(child)
            check_descriptions(tool.inputSchema)
        generation = next(tool for tool in tools if tool.name == 'generate_image')
        for phrase in ('template_code', 'chat', 'flux', 'GIF', 'SVG', 'async', '幂等键'):
            assert phrase in generation.description
        unknown = await client.call_tool_mcp('get_capabilities', {'unexpected':'x'})
        assert unknown.isError
        result = await client.call_tool_mcp('get_task', {'task_id':'t'})
        assert result.isError and result.structuredContent['error']['code'] == 'CONFIG_ERROR'
        bad = await client.call_tool_mcp('get_task', {})
        assert bad.isError
        result = await client.call_tool_mcp('get_capabilities', {})
        assert not result.isError and result.structuredContent['data']['routing']['priority'] == ['images','flux','chat']
        resources = await client.list_resources()
        assert {str(r.uri) for r in resources} == {'gptimage://capabilities','gptimage://prompt-guide','gptimage://recovery-guide','gptimage://tool-guide'}
        resource = await client.read_resource('gptimage://capabilities')
        assert json.loads(resource[0].text) == result.structuredContent['data']
        assert '尺寸不可定制' in (await client.read_resource('gptimage://prompt-guide'))[0].text
        assert 'unknown' in (await client.read_resource('gptimage://recovery-guide'))[0].text
        assert 'generate_batch' in (await client.read_resource('gptimage://tool-guide'))[0].text
        prompts = await client.list_prompts()
        assert [p.name for p in prompts] == ['optimize_ecommerce_prompt']
        prompt = await client.get_prompt('optimize_ecommerce_prompt', {'requirement':'主图','product_facts':'蓝色','image_purpose':'电商'})
        assert prompt.messages and '不补造事实' in prompt.messages[0].content.text

@pytest.mark.asyncio
async def test_injected_backend_receives_validated_inputs_and_chat_warning():
    class Backend:
        async def call(self, name, args):
            assert name == 'generate_image' and args['request']['channel'] == 'chat'
            return {'ok':True,'data':{'task_id':'t'},'error':None,'warnings':[]}
    async with Client(create_server(Backend())) as client:
        result = await client.call_tool_mcp('generate_image', {'request':{'idempotency_key':'x','family':'flare','channel':'chat','prompt':'mug'}})
        assert not result.isError and result.structuredContent['warnings']

@pytest.mark.asyncio
async def test_unknown_submission_guidance_does_not_resubmit():
    from zhenzhen_gptimage.mcp_api.local_ipc import IPCOutcomeUnknown
    class Backend:
        calls = 0
        async def call(self, name, args):
            self.calls += 1
            raise IPCOutcomeUnknown('untrusted detail')
    backend = Backend()
    async with Client(create_server(backend)) as client:
        result = await client.call_tool_mcp('generate_image', TOOL_EXAMPLES['generate_image'])
        error = result.structuredContent['error']
        assert result.isError and error['code'] == 'SUBMISSION_UNKNOWN'
        assert '幂等键' in error['next_action'] and '不要重复提交' in error['next_action']
        assert backend.calls == 1

@pytest.mark.asyncio
async def test_stdio_discovery_and_fail_closed(tmp_path):
    from fastmcp.client.transports import PythonStdioTransport
    script = tmp_path / 'server.py'
    script.write_text("from zhenzhen_gptimage.mcp_api.server import create_server\ncreate_server().run(transport='stdio', show_banner=False)\n", encoding='utf-8')
    async with Client(PythonStdioTransport(script)) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == set(TOOL_INPUTS)
        generate = next(tool for tool in tools if tool.name == 'generate_image')
        assert 'request' in generate.inputSchema['properties'] and 'prompt' in generate.description
        request = generate.inputSchema['properties']['request']
        assert request['type'] == 'object'
        assert {'family', 'idempotency_key'} <= set(request['properties'])
        response = await client.call_tool_mcp('generate_image', {'request': {'idempotency_key':'a', 'family':'flare', 'prompt':'mug', 'width':1024, 'height':1024}})
        assert response.isError and response.structuredContent['error']['code'] == 'CONFIG_ERROR'
        bad = await client.call_tool_mcp('get_capabilities', {'SECRET_SENTINEL':'SECRET_SENTINEL'})
        assert bad.isError and bad.structuredContent['error']['code'] == 'INVALID_ARGUMENT'
        assert 'SECRET_SENTINEL' not in str(bad)

@pytest.mark.asyncio
async def test_text_only_hosts_receive_full_results_and_image_preview():
    class Backend:
        async def call(self, name, args):
            return {'ok': True, 'data': {'task_id': 't', 'images': [{'local_path': 'D:/图片/原件.png'}]},
                    'warnings': [], 'error': None, '_preview': b'preview-bytes'}
    async with Client(create_server(Backend())) as client:
        result = await client.call_tool_mcp('get_image', {'task_id': 't'})
        assert json.loads(result.content[0].text) == result.structuredContent
        assert result.structuredContent['data']['images'][0]['local_path'] == 'D:/图片/原件.png'
        assert '_preview' not in result.content[0].text
        assert result.content[1].type == 'image' and not result.isError
    async with Client(create_server()) as client:
        failure = await client.call_tool_mcp('get_task', {'task_id': 't'})
        assert failure.isError
        assert json.loads(failure.content[0].text) == failure.structuredContent
    class BrokenBackend:
        async def call(self, name, args):
            raise RuntimeError('sensitive-test-token')
    async with Client(create_server(BrokenBackend())) as client:
        failure = await client.call_tool_mcp('get_task', {'task_id': 't'})
        assert failure.isError and 'sensitive-test-token' not in failure.content[0].text
