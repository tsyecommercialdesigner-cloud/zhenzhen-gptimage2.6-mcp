"""Real MCP stdio clients sharing one local backend; no provider calls."""
import asyncio
import hashlib
import json

import pytest
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from zhenzhen_gptimage.mcp_api.discovery import read_endpoint
from zhenzhen_gptimage.mcp_api.local_ipc import connect, read_frame, write_frame
from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS
from zhenzhen_gptimage.mcp_api.contract_guidance import describe_schema, add_conditional_constraints
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.snapshot import create_snapshot
from zhenzhen_gptimage.repository.tasks import accept_batch
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from PIL import Image


@pytest.mark.asyncio
async def test_two_stdio_processes_share_templates_and_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only-secret')
    (tmp_path / '.env').write_text('ZHENZHEN_GPTIMAGEGEN_API_KEY=test-only-secret\n', encoding='utf-8')
    root = tmp_path / 'data'
    root.mkdir()
    db = DatabaseWorker(root / 'state.sqlite3')
    request = GenerationRequest(idempotency_key='fixture', family='flare', prompt='cup', width=512, height=512)
    snapshot = create_snapshot(request, final_prompt='cup', reference_hashes=())
    _, ids = await db.run(accept_batch, [request], [snapshot], 1000)
    image = root / 'fixture.png'
    Image.new('RGB', (32, 32), 'blue').save(image)
    payload = image.read_bytes()
    await db.run(lambda conn: conn.execute('INSERT INTO image_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
        (ids[0], 0, str(image), hashlib.sha256(payload).hexdigest(), 'image/png', len(payload), 32, 32, None, 1000)))
    await db.run(lambda conn: conn.execute("UPDATE tasks SET status='succeeded' WHERE task_id=?", (ids[0],)))
    await db.close()
    script = tmp_path / 'run_server.py'
    script.write_text(
        'import sys\nfrom zhenzhen_gptimage.mcp_api.main import main\n'
        f'sys.argv = ["server", "--config-dir", {str(tmp_path)!r}, "--data-dir", {str(root)!r}]\n'
        'main()\n', encoding='utf-8')
    endpoint = None
    try:
        async with Client(PythonStdioTransport(script)) as first:
            async with Client(PythonStdioTransport(script)) as second:
                tools = await first.list_tools()
                assert {tool.name for tool in tools} == set(TOOL_INPUTS)
                assert all(tool.inputSchema == add_conditional_constraints(tool.name, describe_schema(TOOL_INPUTS[tool.name].model_json_schema())) for tool in tools)
                assert {tool.name for tool in tools} == {tool.name for tool in await second.list_tools()}
                caps = await first.call_tool_mcp('get_capabilities', {})
                assert json.loads((await first.read_resource('gptimage://capabilities'))[0].text) == caps.structuredContent['data']
                assert '尺寸不可定制' in (await second.read_resource('gptimage://prompt-guide'))[0].text
                assert 'unknown' in (await second.read_resource('gptimage://recovery-guide'))[0].text
                prompt = await second.get_prompt('optimize_ecommerce_prompt', {
                    'requirement': '主图', 'product_facts': '蓝色', 'image_purpose': '电商'})
                assert '不补造事实' in prompt.messages[0].content.text
                result = await second.call_tool_mcp('get_image', {'task_id': ids[0]})
                assert not result.isError and any(item.type == 'image' for item in result.content)
                assert json.loads(result.content[0].text) == result.structuredContent
                missing = await first.call_tool_mcp('get_task', {'task_id': 'missing'})
                assert missing.isError and missing.structuredContent['error']['code'] == 'NOT_FOUND'
                saved = await first.call_tool_mcp('save_prompt_template', {
                    'code': 'shared', 'content': 'Hello {{name}}',
                    'variables': [{'name': 'name', 'required': True}],
                })
                assert not saved.isError
                retrieved = await second.call_tool_mcp('get_prompt_template', {'code': 'shared'})
                assert not retrieved.isError
                assert retrieved.structuredContent['data']['content'] == 'Hello {{name}}'
                extra = await first.call_tool_mcp('save_prompt_template', {
                    'code': 'zzsecond', 'content': 'Second', 'variables': [],
                })
                assert not extra.isError
                page = await second.call_tool_mcp('list_prompt_templates', {'limit': 1})
                assert page.structuredContent['data']['items'][0]['code'] == 'shared'
                cursor = page.structuredContent['data']['next_cursor']
                assert cursor
                page2 = await first.call_tool_mcp('list_prompt_templates', {'limit': 1, 'cursor': cursor})
                assert page2.structuredContent['data']['items'][0]['code'] == 'zzsecond'
                endpoint = read_endpoint(root)
                assert endpoint is not None
    finally:
        if endpoint is not None:
            reader, writer = await connect(endpoint, endpoint.identity)
            try:
                await write_frame(writer, {'op': 'stop'}, timeout=5)
                await read_frame(reader, timeout=5)
            finally:
                writer.close()
                await writer.wait_closed()
            await asyncio.sleep(.3)
