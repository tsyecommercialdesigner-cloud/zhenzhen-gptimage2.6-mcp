"""Static resources and prompts: no provider or filesystem access."""
PROMPT_GUIDE = """根据用户用途组织商品主体、构图、光线、背景与画面文字。仅使用已确认的商品事实；
未知卖点、规格和认证须向用户询问。参考图只在实际查看或用户描述的范围内使用。
优先选择 Generations，其次 Flux，最后 Chat；Flux 不接受参考图，Chat 图片尺寸不可定制。"""
RECOVERY_GUIDE = """unknown 表示供应商可能已受理，不自动重新提交；查询任务并按需显式结案。
recovery_pending 表示有可恢复的结果材料，先使用 recover_task 本地恢复；不可恢复时可显式结案。
结案不表示供应商取消，重新生成需要新的幂等键。"""

def optimize_ecommerce_prompt(requirement: str, product_facts: str, image_purpose: str) -> str:
    return (PROMPT_GUIDE + '\n请根据以下信息优化提示词，不补造事实。\n'
            f'用途：{image_purpose}\n需求：{requirement}\n已确认事实：{product_facts}')
