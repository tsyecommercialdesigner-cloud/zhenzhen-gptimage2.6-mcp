"""FastMCP surface; business logic is injected and missing handlers fail closed."""
from __future__ import annotations

import json
import base64
from typing import Any, Protocol
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolResult, TextContent, ImageContent
from pydantic import ValidationError

from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS
from zhenzhen_gptimage.generation.models import GenerationRequest, MODELS
from zhenzhen_gptimage.prompts.guidance import PROMPT_GUIDE, RECOVERY_GUIDE, optimize_ecommerce_prompt
from .local_ipc import IPCOutcomeUnknown


class Backend(Protocol):
    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ProtocolResult(ToolResult):
    """Preserve MCP isError along with structured content."""
    def __init__(self, value: dict[str, Any]):
        preview = value.pop('_preview', None)
        self._value = value
        content = [TextContent(type='text', text=json.dumps(value, ensure_ascii=False))]
        if preview is not None:
            content.append(ImageContent(type='image', data=base64.b64encode(preview).decode('ascii'), mimeType='image/jpeg'))
        super().__init__(content=content,
                         structured_content=value)

    def to_mcp_result(self):
        return CallToolResult(content=self.content, structuredContent=self.structured_content, isError=not self._value['ok'])


def _failure(code: str, message: str, action: str) -> dict[str, Any]:
    return {'ok': False, 'data': None, 'warnings': [],
            'error': {'code': code, 'message': message, 'retryable': False, 'next_action': action}}


def capabilities() -> dict[str, Any]:
    return {'models': list(MODELS), 'routing': {'priority': ['images', 'flux', 'chat'],
            'chat_size': '不可定制，供应商决定实际尺寸'},
            'limits': {'max_concurrency': 6, 'max_unfinished': 20, 'max_attempts': 3},
            'channels': {'images': 'default', 'flux': 'no_reference', 'chat': 'no_custom_size'},
            'formats': {'svg':'base flare only; original saved; preview may be unavailable',
                        'gif':'t8-star; original animation saved; preview is a still frame'},
            'async_generation': 'images channel, base flare GIF only; explicit execution_mode=async',
            'evidence': {'images_png_single_flare': 'verified', 'flux_target_models': 'pending',
                         'chat_basic': 'reference', 'chat_custom_size': 'blocked',
                         'svg_flare_luna_1024': 'provider_verified', 'gif_flare': 'provider_verified',
                         'other_svg_gif_combinations': 'not_verified'}}


def create_server(backend: Backend | None = None) -> FastMCP:
    app = FastMCP('zhenzhen-gptimage-2.6', strict_input_validation=True)

    async def dispatch(name: str, args: dict[str, Any]) -> ProtocolResult:
        try:
            # Functions using locals() include the closed-over dispatch function.
            args = {key: value for key, value in args.items() if key != 'dispatch'}
            validated = TOOL_INPUTS[name].model_validate(args)
        except ValidationError:
            return ProtocolResult(_failure('INVALID_ARGUMENT', '参数校验失败', '检查工具参数'))
        if name == 'get_capabilities' and backend is None:
            return ProtocolResult({'ok': True, 'data': capabilities(), 'warnings': [], 'error': None})
        if backend is None:
            return ProtocolResult(_failure('CONFIG_ERROR', '服务功能尚未接入', '完成服务组装后重试'))
        try:
            result = await backend.call(name, validated.model_dump(mode='json', exclude_none=True))
            if not isinstance(result, dict) or type(result.get('ok')) is not bool or 'data' not in result or 'error' not in result:
                raise ValueError('invalid backend result')
            if result['ok'] == (result['error'] is not None):
                raise ValueError('inconsistent backend result')
            result.setdefault('warnings', [])
            is_chat = (name == 'generate_image' and validated.request.channel == 'chat') or (
                name == 'generate_batch' and any(request.channel == 'chat' for request in validated.requests))
            if is_chat:
                warning = 'Chat Completions 生成图像的尺寸由供应商决定，无法定制'
                if warning not in result['warnings']: result['warnings'].append(warning)
            return ProtocolResult(result)
        except IPCOutcomeUnknown:
            return ProtocolResult(_failure('SUBMISSION_UNKNOWN', '调用结果未知', '使用原任务 ID 或幂等键查询；不要重复提交'))
        except Exception:
            return ProtocolResult(_failure('PERSISTENCE_ERROR', '服务执行失败', '检查本地日志和任务状态'))

    @app.tool
    async def get_capabilities(): return await dispatch('get_capabilities', {})
    @app.tool
    async def generate_image(request: GenerationRequest):
        """生成图片；结果中的 local_path 是保存的原件，Host 附件可能只是预览副本。支持本地图片链接的 Host 可使用原件路径展示静态图片。"""
        return await dispatch('generate_image', {'request': request})
    @app.tool
    async def generate_batch(requests: list[GenerationRequest]): return await dispatch('generate_batch', {'requests': requests})
    @app.tool
    async def get_task(task_id: str | None = None, idempotency_key: str | None = None): return await dispatch('get_task', locals())
    @app.tool
    async def list_tasks(status: str | None = None, batch_id: str | None = None, model: str | None = None,
                         created_from: str | None = None, created_to: str | None = None,
                         limit: int = 20, cursor: str | None = None): return await dispatch('list_tasks', locals())
    @app.tool
    async def get_image(task_id: str, image_index: int = 0, include_preview: bool = True):
        """查询已保存的原件和可选预览；local_path 指向原件，Host 附件可能只是预览副本。支持本地图片链接的 Host 可使用原件路径展示静态图片。"""
        return await dispatch('get_image', locals())
    @app.tool
    async def recover_task(task_id: str): return await dispatch('recover_task', locals())
    @app.tool
    async def accept_gif_size(task_id: str, sha256: str, width: int, height: int): return await dispatch('accept_gif_size', locals())
    @app.tool
    async def close_task(task_id: str, expected_status: str, reason: str): return await dispatch('close_task', locals())
    @app.tool
    async def save_prompt_template(code: str, content: str, variables: list[dict[str, Any]], expected_version: int | None = None):
        return await dispatch('save_prompt_template', locals())
    @app.tool
    async def get_prompt_template(code: str): return await dispatch('get_prompt_template', locals())
    @app.tool
    async def list_prompt_templates(query: str | None = None, limit: int = 20, cursor: str | None = None): return await dispatch('list_prompt_templates', locals())
    @app.tool
    async def render_prompt_template(code: str, variables: dict[str, str]): return await dispatch('render_prompt_template', locals())

    # FastMCP's function parser otherwise drops Pydantic contract constraints
    # on top-level parameters (limits, enums and additionalProperties). Keep
    # the advertised MCP input schemas aligned with the canonical contracts.
    registered = {
        'get_capabilities': get_capabilities, 'generate_image': generate_image,
        'generate_batch': generate_batch, 'get_task': get_task, 'list_tasks': list_tasks,
        'get_image': get_image, 'recover_task': recover_task, 'close_task': close_task,
        'accept_gif_size': accept_gif_size,
        'save_prompt_template': save_prompt_template, 'get_prompt_template': get_prompt_template,
        'list_prompt_templates': list_prompt_templates, 'render_prompt_template': render_prompt_template,
    }
    for name, tool in registered.items():
        tool.parameters = TOOL_INPUTS[name].model_json_schema()

    async def resource_value(uri, default):
        if backend is None:
            return default
        result = await backend.call('__resource__', {'uri': uri})
        if not result.get('ok') or not isinstance(result.get('data'), str):
            raise RuntimeError('resource unavailable')
        return result['data']

    @app.resource('gptimage://capabilities')
    async def capability_resource() -> str:
        return await resource_value('gptimage://capabilities', json.dumps(capabilities(), ensure_ascii=False))
    @app.resource('gptimage://prompt-guide')
    async def prompt_guide() -> str:
        return await resource_value('gptimage://prompt-guide', PROMPT_GUIDE)
    @app.resource('gptimage://recovery-guide')
    async def recovery_guide() -> str:
        return await resource_value('gptimage://recovery-guide', RECOVERY_GUIDE)

    @app.prompt(name='optimize_ecommerce_prompt')
    async def prompt(requirement: str, product_facts: str, image_purpose: str) -> str:
        if backend is None:
            return optimize_ecommerce_prompt(requirement, product_facts, image_purpose)
        result = await backend.call('__prompt__', {'requirement': requirement,
                                    'product_facts': product_facts, 'image_purpose': image_purpose})
        if not result.get('ok') or not isinstance(result.get('data'), str):
            raise RuntimeError('prompt unavailable')
        return result['data']
    return app
