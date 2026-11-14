"""Static resources and prompts: no provider or filesystem access."""
PROMPT_GUIDE = """根据用户用途组织商品主体、构图、光线、背景与画面文字。仅使用已确认的商品事实；
未知卖点、规格和认证须向用户询问。参考图只在实际查看或用户描述的范围内使用。
优先选择 Generations，其次 Flux，最后 Chat；Flux 不接受参考图，Chat 图片尺寸不可定制。"""
RECOVERY_GUIDE = """unknown 表示供应商可能已受理，不自动重新提交；查询任务并按需显式结案。
recovery_pending 表示有可恢复的结果材料，先使用 recover_task 本地恢复；不可恢复时可显式结案。
unknown 如保存了远程任务 ID，可用 recover_task 查询同一远程任务，不会重新提交；无 ID 时不得自动重发。
结案不表示供应商取消，重新生成需要新的幂等键。"""

TOOL_EXAMPLES = {
    'generate_image': {'request': {'idempotency_key': 'example-001', 'family': 'flare', 'prompt': '蓝色杯子', 'width': 1024, 'height': 1024}},
    'generate_batch': {'requests': [{'idempotency_key': 'example-002', 'family': 'flare', 'prompt': '白色杯子', 'width': 1024, 'height': 1024}]},
    'reference': {'request': {'idempotency_key': 'example-003', 'family': 'flare', 'prompt': '保留商品外观', 'width': 1024, 'height': 1024, 'references': [{'local_path': 'D:/example/reference.png'}]}},
    'gif': {'request': {'idempotency_key': 'example-004', 'family': 'flare', 'prompt': '旋转的蓝色杯子', 'output_format': 'gif', 'size': 'auto'}},
    'svg': {'request': {'idempotency_key': 'example-005', 'family': 'flare', 'prompt': '蓝色杯子图标', 'output_format': 'svg', 'size': 'auto'}},
    'get_task': {'idempotency_key': 'example-001'},
    'get_image': {'task_id': 'example-task', 'image_index': 0},
    'recover_task': {'task_id': 'example-task'},
    'export_image': {'task_id': 'example-task', 'destination': 'D:/example/image.png'},
}

def tool_guide() -> str:
    import json
    return ('参数示例仅展示结构，生成调用可能收费；使用前替换幂等键、任务 ID 和本机路径。'
            '生成后用 get_task 查询，成功后 get_image 或 export_image。'
            '结果未知时使用原幂等键或任务 ID 查询，不要换键重发。\n' +
            json.dumps(TOOL_EXAMPLES, ensure_ascii=False, indent=2))

def optimize_ecommerce_prompt(requirement: str, product_facts: str, image_purpose: str) -> str:
    return (PROMPT_GUIDE + '\n请根据以下信息优化提示词，不补造事实。\n'
            f'用途：{image_purpose}\n需求：{requirement}\n已确认事实：{product_facts}')
