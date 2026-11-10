"""FastMCP surface; business logic is injected and missing handlers fail closed."""
from __future__ import annotations

import json
import base64
from typing import Any, Protocol
from fastmcp import FastMCP, Context
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
    async def export_image(task_id: str, destination: str, image_index: int = 0):
        """复制已登记原件至用户指定的本机绝对文件路径，不覆盖已有文件。"""
        return await dispatch('export_image', locals())
    @app.tool
    async def preview_cleanup(before: str | None = None, keep_latest: int | None = None):
        """预览清理计划，不删除文件；before 为带时区的 ISO 日期时间。"""
        return await dispatch('preview_cleanup', locals())
    @app.tool
    async def execute_cleanup(plan_id: str):
        """执行已由用户在本机批准的预览计划；没有批准时不删除。"""
        return await dispatch('execute_cleanup', locals())
    @app.tool
    async def authorize_cleanup(plan_id: str, ctx: Context):
        """向支持交互确认的 Host 展示清理清单并请求用户授权，不删除文件。"""
        try:
            validated = TOOL_INPUTS['authorize_cleanup'].model_validate({'plan_id':plan_id})
            if backend is None:
                return ProtocolResult(_failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置'))
            result = await backend.call('__cleanup_plan__', {'plan_id':validated.plan_id})
            if not result.get('ok'):
                return ProtocolResult(result)
            plan = result['data']
            items = [{'kind':i.get('kind','image'),'task_id':i['task_id'],'image_index':i['image_index'],'local_path':i['local_path'],
                      'bytes':i['bytes'],'sha256':i['sha256']} for i in plan['items']]
            message = ('是否永久删除以下托管原件及列出的关联文件？确认只授权此计划，工作区导出副本不会删除。\n' +
                       json.dumps({'plan_id':plan_id,'expires_at':plan['expires_at'],
                                   'count':plan['count'],'bytes':plan['bytes'],'items':items},ensure_ascii=False))
            if len(message.encode('utf-8')) > 16000:
                return ProtocolResult(_failure('RESOURCE_LIMIT','清单过长，无法完整显示交互确认','使用本机 approve-cleanup 命令审核'))
            try:
                response = await ctx.elicit(message)
            except Exception:
                return ProtocolResult(_failure('CONFIG_ERROR','当前 Host 不支持用户交互确认','使用本机 approve-cleanup 命令审核'))
            if response.action != 'accept':
                return ProtocolResult(_failure('STATE_CONFLICT','用户未批准清理','重新预览后再申请授权'))
            return ProtocolResult(await backend.call('__approve_cleanup__', {'plan_id':plan_id}))
        except (ValidationError, ValueError, KeyError):
            return ProtocolResult(_failure('INVALID_ARGUMENT','清理计划无效或已过期','重新预览'))
    @app.tool
    async def get_retention_policy():
        """查询 90 天自动清理是否启用。"""
        return await dispatch('get_retention_policy', {})
    @app.tool
    async def set_retention_policy(enabled: bool, ctx: Context):
        """启用前须由用户确认；关闭不会启动清理。"""
        try:
            value = TOOL_INPUTS['set_retention_policy'].model_validate({'enabled':enabled})
            if backend is None:
                return ProtocolResult(_failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置'))
            if value.enabled:
                try:
                    response = await ctx.elicit('启用后，后台运行时会永久删除生成时间超过 90 天的符合条件的托管原件，以及其可安全清理的供应商响应、响应清单和参考图快照。确认启用吗？')
                except Exception:
                    return ProtocolResult(_failure('CONFIG_ERROR','当前 Host 不支持用户交互确认','使用本机 enable-auto-cleanup 命令'))
                if response.action != 'accept':
                    return ProtocolResult(_failure('STATE_CONFLICT','用户未批准启用自动清理','维持当前设置'))
            return ProtocolResult(await backend.call('__set_retention_policy__', {'enabled':value.enabled}))
        except ValidationError:
            return ProtocolResult(_failure('INVALID_ARGUMENT','策略参数无效','检查 enabled 参数'))
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
        'get_image': get_image, 'export_image': export_image, 'preview_cleanup': preview_cleanup,
        'execute_cleanup': execute_cleanup,
        'authorize_cleanup': authorize_cleanup,
        'get_retention_policy': get_retention_policy, 'set_retention_policy': set_retention_policy,
        'recover_task': recover_task, 'close_task': close_task,
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
