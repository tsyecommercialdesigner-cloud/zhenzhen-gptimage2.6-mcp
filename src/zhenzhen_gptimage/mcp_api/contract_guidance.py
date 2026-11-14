"""Human-readable guidance attached to the MCP discovery schema."""

FIELDS = {
    'request': '单项生成请求对象；参见 generate_image 示例和字段说明。',
    'requests': '生成请求数组，每项使用不同幂等键；每批 1–20 项。',
    'idempotency_key': '请求稳定标识；同键同内容复用，同键不同内容冲突。结果未知时用原键查询，勿换键重发。',
    'family': '模型系列 flare 或 sunburst；型号按尺寸自动路由。',
    'channel': '调用通道；默认 images，flux 不接受参考图，chat 不接受宽高。',
    'width': '宽度像素；普通 images/flux 需与 height 同时填写，chat 禁止填写。',
    'height': '高度像素；普通 images/flux 需与 width 同时填写，chat 禁止填写。',
    'explicit_model': '可选明确型号，必须与系列和路由尺寸一致。',
    'prompt': '绘图提示词，与 template_code 恰好提供一个，最多 32 KiB UTF-8。',
    'template_code': '已保存模板代号，与 prompt 恰好提供一个。',
    'template_variables': '模板变量名与字符串值的映射；仅在使用模板时提供。',
    'references': '最多 4 张参考图，每项为 {"local_path":"本机 PNG 绝对路径"}；flux、SVG、GIF 不支持。',
    'local_path': '参考图的服务器本机 PNG 文件路径。',
    'provider': '供应商，目前仅 t8-star。',
    'execution_mode': '默认 sync；async 仅 images 通道基础 flare GIF，长边不超过 1024。',
    'output_format': '默认普通静态图片；可选 gif 或 svg，仅文生图。SVG 仅基础 flare。',
    'size': '仅 GIF/SVG 使用，支持 auto、1:1、3:2、2:3、4:3、3:4、5:4、4:5、16:9、9:16、2:1、1:2、21:9、9:21、3:1、1:3 或 WxH；不能与 width/height 同时提供。',
    'size_policy': 'GIF 尺寸不符策略：默认 strict 待确认，accept_actual 接受实际尺寸。',
    'frame_count': 'GIF 帧数 2–16，省略时默认 9；帧数影响拼图边长、面积及长宽比上限。',
    'frame_duration_ms': 'GIF 每帧毫秒数，至少 20 且为 10 的倍数。',
    'svg_model': 'SVG 绘制模型；仅 SVG 使用，省略时使用服务默认值。',
    'svg_reasoning_effort': 'SVG 绘制模型推理强度，仅 SVG 使用。',
    'task_id': '本地任务 ID；get_task 中与 idempotency_key 恰选一个。',
    'status': '按任务状态过滤。', 'batch_id': '按批次 ID 过滤。', 'model': '按完整模型 ID 过滤。',
    'created_from': '创建时间下界，带时区的 ISO 日期时间。', 'created_to': '创建时间上界，带时区的 ISO 日期时间。',
    'limit': '分页数量，默认 20，范围 1–100。', 'cursor': '上页返回的游标，须沿用相同筛选条件。',
    'image_index': '图片索引，从 0 开始，默认 0。', 'include_preview': '是否返回可用预览，默认 true；预览可能不是原件。',
    'destination': '服务器本机绝对文件路径，扩展名与原件一致；不覆盖已有文件。',
    'before': '清理生成时间早于此带时区 ISO 日期时间的产物，与 keep_latest 恰选一个。',
    'keep_latest': '保留最新 N 个产物，与 before 恰选一个。',
    'plan_id': '预览生成的清理计划 ID；执行前需用户授权。', 'enabled': '是否启用自动清理；启用前需用户确认。',
    'sha256': '待确认原件的 64 位小写 SHA-256。',
    'expected_status': '待结案任务当前状态：unknown 或 recovery_pending。', 'reason': '用户确认的结案原因。',
    'code': '模板快捷代号，1–64 位字母、数字、下划线或连字符。',
    'content': '模板内容，变量使用 {{变量名}}。', 'variables': '模板变量定义列表，或渲染时变量名到字符串值的映射。',
    'expected_version': '更新模板时的预期版本，用于并发检查。', 'query': '模板搜索关键词。',
    'name': '模板变量名称。', 'required': '变量是否必填；必填变量不能设置默认值。', 'default': '可选变量的默认值。',
}

TOOLS = {
    'get_capabilities': '查询模型、通道、格式与当前实现限制，不生成图片。',
    'generate_image': '提交单个图像任务。示例 {"request":{"idempotency_key":"unique-001","family":"flare","prompt":"蓝色杯子","width":1024,"height":1024}}。prompt 和 template_code 二选一；普通 images/flux 必须有宽高，chat 禁止宽高。长边不超过 1024/2048/4096 分别路由基础/2k/4k。PNG 参考图最多 4 张；flux、GIF、SVG 不支持参考图。GIF/SVG 仅文生图，SVG 仅基础 flare；自定义像素尺寸为 16 的倍数，GIF 拼图及 SVG 画布另受面积、边长和比例限制。async 仅 images 基础 flare GIF 且长边不超过 1024。默认同步等待；未知结果使用原任务 ID 或幂等键查询，勿重发。原件 local_path 与 Host 预览可能不同。更多示例见 gptimage://tool-guide。',
    'generate_batch': '批量生成；参数 {"requests":[生成请求对象]}，1–20 项；全局最多 20 个未完成任务。',
    'get_task': '按 task_id 或 idempotency_key 恰选一个查询任务，不提交生成。示例 {"idempotency_key":"unique-001"}。',
    'list_tasks': '分页查询历史任务；不触发生成或远程下载。',
    'get_image': '查询原件及可选预览。示例 {"task_id":"任务ID","image_index":0}；local_path 为原件。',
    'export_image': '复制已登记原件到本机绝对文件路径，不覆盖已有文件。示例 {"task_id":"任务ID","destination":"D:/output/image.png"}。',
    'preview_cleanup': '按日期或保留数量预览清理计划，不删除文件。',
    'execute_cleanup': '执行用户已批准的清理计划；未授权时不删除。',
    'authorize_cleanup': '请求用户交互确认清理计划，不直接删除。',
    'get_retention_policy': '查询 90 天自动清理策略。',
    'set_retention_policy': '修改自动清理策略，启用前需要用户确认。',
    'recover_task': '恢复同一个任务，不重新提交生成。示例 {"task_id":"任务ID"}。',
    'accept_gif_size': '用户明确同意后接受已保存 GIF 的实际尺寸。',
    'close_task': '显式结案允许结案的 unknown 或 recovery_pending 任务。',
    'save_prompt_template': '创建或按预期版本更新提示词模板。',
    'get_prompt_template': '按代号读取提示词模板。',
    'list_prompt_templates': '分页浏览或搜索提示词模板。',
    'render_prompt_template': '根据变量展开已保存模板，不生成图片。',
}


def describe_schema(schema: dict) -> dict:
    """Attach descriptions and inline local definitions for Host compatibility."""
    for obj in [schema, *schema.get('$defs', {}).values()]:
        for name, prop in obj.get('properties', {}).items():
            if name in FIELDS:
                prop['description'] = FIELDS[name]
    definitions = schema.get('$defs', {})
    def expand(value, active=frozenset()):
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        ref = value.get('$ref')
        if isinstance(ref, str) and ref.startswith('#/$defs/'):
            key = ref.removeprefix('#/$defs/')
            if key in active or key not in definitions:
                raise ValueError('recursive or unknown schema definition')
            resolved = expand(definitions[key], active | {key})
            return {**resolved, **{k: expand(v, active) for k, v in value.items() if k != '$ref'}}
        return {k: expand(v, active) for k, v in value.items() if k != '$defs'}
    return expand(schema)


def add_conditional_constraints(name: str, schema: dict) -> dict:
    """Keep complex conditions in descriptions and canonical runtime validation.

    Codex translates nested oneOf into unknown types, losing field schemas.
    """
    if name == 'accept_gif_size':
        schema['properties']['width']['description'] = '待确认 GIF 原件的实际宽度，单位像素。'
        schema['properties']['height']['description'] = '待确认 GIF 原件的实际高度，单位像素。'
    return schema
