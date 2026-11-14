"""Map validation failures to fixed, non-sensitive guidance."""
from pydantic import ValidationError
from zhenzhen_gptimage.generation.models import GenerationRequest, ReferenceInput
from zhenzhen_gptimage.generation.contracts import TOOL_INPUTS, TemplateVariable

SAFE_FIELDS = frozenset().union(*(set(model.model_fields) for model in
    (*TOOL_INPUTS.values(), GenerationRequest, ReferenceInput, TemplateVariable)))


def safe_validation_error(name: str, args: dict, error: ValidationError) -> tuple[str, str]:
    """Never interpolate Pydantic messages, dynamic keys, input values or context."""
    item = error.errors(include_url=False, include_input=False)[0]
    location = [str(part) if isinstance(part, int) or part in SAFE_FIELDS else '*' for part in item['loc']]
    path = '.'.join(location) or '参数'
    kind = item['type']
    if kind == 'missing':
        return f'{path}: 缺少必填字段', '填写该字段后重试'
    if kind == 'extra_forbidden':
        return f'{path}: 存在不支持的字段', '删除未知字段并参考工具参数说明'
    if kind in {'int_type', 'string_type', 'bool_type', 'list_type', 'dict_type', 'model_type'}:
        return f'{path}: 数据类型不正确', '按工具 Schema 提供对应类型'
    if kind in {'greater_than', 'greater_than_equal', 'less_than', 'less_than_equal', 'string_too_short', 'string_too_long', 'too_short', 'too_long'}:
        return f'{path}: 数值或长度超出允许范围', '参考工具 Schema 的范围限制'
    if kind in {'literal_error', 'enum', 'string_pattern_mismatch'}:
        return f'{path}: 取值不符合允许的格式或选项', '参考工具 Schema 的枚举或格式约束'
    if kind == 'value_error':
        if name == 'get_task':
            return 'task_id 和 idempotency_key 必须且只能提供一个', '选择一个查询条件'
        if name == 'preview_cleanup':
            return 'before 和 keep_latest 必须且只能提供一个', '选择一个清理条件'
        if name in ('generate_image', 'generate_batch'):
            requests = [args.get('request')] if name == 'generate_image' else args.get('requests', [])
            if isinstance(requests, list):
                for request in requests:
                    if isinstance(request, dict) and (request.get('prompt') is None) == (request.get('template_code') is None):
                        return 'prompt 与 template_code 必须且只能提供一个', '选择提示词或模板代号后重试'
            return '生成请求的字段组合不符合约束', '检查 prompt/template_code、通道、尺寸、格式及执行模式的工具说明'
        return f'{path}: 字段组合不符合约束', '检查工具参数说明'
    return f'{path}: 类型或取值不符合约束', '检查字段类型、取值范围及工具说明'
