# MCP 契约基线

2026-11-14，使用工作树的 `create_server` 和真实 FastMCP Client 内存协议传输读取 `tools/list`；注入计数后端，没有调用供应商。下表为顶层字段，`*` 表示 Schema 必填；缺省值与具体字段类型见各 `TOOL_INPUTS` Pydantic Schema。

| 工具 | 顶层参数 | 原有工具说明 |
| --- | --- | --- |
| get_capabilities | 无 | 无 |
| generate_image | request* | 有 |
| generate_batch | requests* | 无 |
| get_task | task_id、idempotency_key | 无 |
| list_tasks | status、batch_id、model、created_from、created_to、limit、cursor | 无 |
| get_image | task_id*、image_index、include_preview | 有 |
| export_image | task_id*、image_index、destination* | 有 |
| preview_cleanup | before、keep_latest | 有 |
| execute_cleanup、authorize_cleanup | plan_id* | 有 |
| get_retention_policy | 无 | 有 |
| set_retention_policy | enabled* | 有 |
| recover_task | task_id* | 无 |
| accept_gif_size | task_id*、sha256*、width*、height* | 无 |
| close_task | task_id*、expected_status*、reason* | 无 |
| save_prompt_template | code*、content*、variables*、expected_version | 无 |
| get_prompt_template | code* | 无 |
| list_prompt_templates | query、limit、cursor | 无 |
| render_prompt_template | code*、variables* | 无 |

`request`/`requests` 嵌套 `GenerationRequest`：`idempotency_key`、`family` 必填；`channel=images`、`execution_mode=sync`、`provider=t8-star`、`size_policy=strict`，`references` 默认为空，其余选填或为空。实际约束包括 prompt/template_code 二选一、图像通道与尺寸、1024/2048/4096 路由、PNG 参考图最多 4 张及格式/通道限制；以 `generation/models.py`、`generation/admission.py` 和主规范 `image-generation`、`task-queue` 为准。资源为 `gptimage://capabilities`、`gptimage://prompt-guide`、`gptimage://recovery-guide`；Prompt 为 `optimize_ecommerce_prompt`。

同次真实客户端协议探针：`get_task {}` 在服务分派层返回结构化错误；`get_image` 错误类型、生成请求的互斥字段以及 `get_capabilities` 的未知字段由 SDK 前置校验返回非结构化错误。未知字段名中的测试标记出现在 SDK 错误中，故当前不能声称该路径完全脱敏；四个无效调用后注入后端调用数为零。此为无网络的工作树基线，不代表 Desktop 或真实供应商验收。
