import pytest
from fastmcp import Client
from zhenzhen_gptimage.mcp_api.server import create_server
from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS

@pytest.mark.asyncio
async def test_discovery_and_fail_closed():
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == set(TOOL_INPUTS)
        for tool in tools:
            assert tool.inputSchema == TOOL_INPUTS[tool.name].model_json_schema()
        unknown = await client.call_tool_mcp('get_capabilities', {'unexpected':'x'})
        assert unknown.isError
        result = await client.call_tool_mcp('get_task', {'task_id':'t'})
        assert result.isError and result.structuredContent['error']['code'] == 'CONFIG_ERROR'
        bad = await client.call_tool_mcp('get_task', {})
        assert bad.isError
        result = await client.call_tool_mcp('get_capabilities', {})
        assert not result.isError and result.structuredContent['data']['routing']['priority'] == ['images','flux','chat']
        resources = await client.list_resources()
        assert {str(r.uri) for r in resources} == {'gptimage://capabilities','gptimage://prompt-guide','gptimage://recovery-guide'}
        import json
        resource = await client.read_resource('gptimage://capabilities')
        assert json.loads(resource[0].text) == result.structuredContent['data']
        assert '尺寸不可定制' in (await client.read_resource('gptimage://prompt-guide'))[0].text
        assert 'unknown' in (await client.read_resource('gptimage://recovery-guide'))[0].text
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
async def test_stdio_discovery_and_fail_closed(tmp_path):
    from fastmcp.client.transports import PythonStdioTransport
    script = tmp_path / 'server.py'
    script.write_text("from zhenzhen_gptimage.mcp_api.server import create_server\ncreate_server().run(transport='stdio', show_banner=False)\n", encoding='utf-8')
    async with Client(PythonStdioTransport(script)) as client:
        assert {tool.name for tool in await client.list_tools()} == set(TOOL_INPUTS)
        response = await client.call_tool_mcp('generate_image', {'request': {'idempotency_key':'a', 'family':'flare', 'prompt':'mug', 'width':1024, 'height':1024}})
        assert response.isError and response.structuredContent['error']['code'] == 'CONFIG_ERROR'
