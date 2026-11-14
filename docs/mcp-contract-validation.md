# MCP 工具契约验证记录

2026-11-14，在 Windows 工作树上使用 FastMCP Client 的内存与 stdio 协议传输读取工具发现结果、示例及条件 Schema，检查有效和无效参数。验证了未知字段、类型、范围、嵌套和互斥条件的脱敏错误及本地后端未接收无效请求；测试密钥、提示词和路径标记没有进入响应或测试日志。模拟结果未知时保留原幂等键查询提示，后端只调用一次。相关测试 `tests/test_mcp_surface.py` 与 `tests/test_shared_stdio_integration.py` 共 13 项通过；这是开发工作树和受控后端验证，不代表发布版或 Desktop 会话验收。

FastMCP 严格 Schema 校验原先会把未知字段名称放入非结构化错误；当前工作树在 SDK 前置校验之前使用规范模型进行脱敏验证，并保留现有错误封装。此实现依赖当前 MCP SDK 的请求处理注册接口，需继续在完整回归和三个实际 Host 中验证兼容性。

使用独立检出的 v0.1.2 安装目录作为旧版测试输入，最终工作树完整测试为 293 通过、1 跳过，变更及 10 个主规范严格校验通过。`tests/test_mcp_backend.py` 的 10 项测试通过，包含受控供应商替身上的批量幂等与查询；这是程序化客户端测试，尚不代表实际 Agent 自行构造参数或真实供应商验收。

2026-11-14，Claude Desktop Cowork 和 DeepSeek Harness Desktop 加载开发工作树的 `zhenzhen-contract-test` 隔离服务；它使用 `.cache/contract-host-harness/` 的分 Host 测试数据和本地合成图片，不请求供应商。Cowork 首次根据自然语言构造了 `request`、幂等键、提示词和尺寸，但遗漏必填 `family`；该调用停在 Host 的用户确认提示，尚未观察错误或纠正。

DSH 初次将 `request` 作为 JSON 字符串传递，收到脱敏 `INVALID_ARGUMENT`；Agent 随后将其改为对象并正确填写 `family=flare` 等字段，工具返回成功及图片信息。脱敏合成提交账本记录一次生成，未调用供应商；Host 此后报告会话模型服务 `AUTH / API 密钥无效`，切换到已有 codeproxy GPT 后继续查询仍遇到同一类 Host 错误，查询与导出尚未完成。此错误发生在 Host 模型会话，不是本地替身供应商生成失败；不能据此判断具体密钥或供应商账户的根因。

同日用户恢复 DSH 会话模型后，Agent 继续查询该已有合成任务并调用 `export_image`；目标 `D:\MCP-host-tests\zhenzhen-gptimage2.6\contract-dsh.png` 与隔离原件独立计算的 SHA-256 均为 `b768ea017c93ad562cae4c99ad7d34bfb409ffedad1f378564f5b7a260969515`，合成提交账本仍只有一条。该结果属于实际 DSH 会话与开发版隔离替身验收，不代表正式发布版或真实供应商验收。

Cowork 用户允许首次调用后，工具调用标记失败；会话模型随后返回 `403 No active subscription found for this group`，尚未观察到自行纠正与导出。此为 Host 会话模型服务报错，不应误写为图像供应商错误。

用户恢复 Cowork 会话模型后继续同一隔离验收：Agent 识别 `request.family` 缺失，自行填写 `flare` 并沿用原幂等键，合成任务成功；随后查询并导出到 `D:\MCP-host-tests\zhenzhen-gptimage2.6\contract-cowork.png`。本机独立计算导出副本与隔离原件的 SHA-256 均为 `b768ea017c93ad562cae4c99ad7d34bfb409ffedad1f378564f5b7a260969515`，合成提交账本只有一条。图片为纯色本地测试合成物，并非真实供应商生成；正式发布版验收仍需单独完成。

Codex Desktop 使用相同工作树的隔离服务，先发送缺少 `family` 的请求并收到 `request.family: 缺少必填字段`，再沿用同一幂等键补全 `flare`；合成生成、幂等键查询与导出均成功，独立核对原件与 `D:\MCP-host-tests\zhenzhen-gptimage2.6\contract-codex.png` 的 SHA-256 均为 `b768ea017c93ad562cae4c99ad7d34bfb409ffedad1f378564f5b7a260969515`，替身记录一次提交。该错误请求由验收者刻意构造，不能据此认定 Codex 自主首次传参失败。

本次还发现，将互斥规则放在嵌套 `oneOf` 时，Codex 工具声明把 `generate_image.request` 转换成 `unknown` 交叉类型，无法清晰暴露字段类型；`get_task` 也出现类似转换。因此依据设计的兼容回退，工作树移除这些组合 Schema，保留字段描述与服务端校验；修改后协议聚焦测试 13 项通过。Codex 重新加载后的工具发现效果仍需验证，上述三个 Host 的成功调用只证明回退前的隔离工作树行为。

兼容回退后重新运行工作树全量测试：293 通过、1 跳过；变更和 10 项主规范严格校验通过。旧版兼容测试使用独立检出的 v0.1.2 环境，未替换实际安装。

用户再次重启 Codex Desktop 后，隔离服务的实际工具声明重新显示完整 `request` 对象、各字段类型、描述和 `family`、`idempotency_key` 必填项，`get_task` 两个可选字段也不再显示为 `unknown`。当前 Codex Agent 依据发现结果构造两项批量生成请求，替身均返回成功；重复提交相同两项时均返回 `reused: true`，用原幂等键查询获得同一任务。独立账本共三条，分别为此前单项和这次两项合成提交，重复批次没有新增提交。未访问真实供应商；该测试仅验证当前 Codex 会话和隔离替身。

重新加载后的 DSH 会话报告能看到 `request` 对象和 `family`、`idempotency_key` 的类型，并查询及导出既有合成任务；Cowork 会话查询和导出成功，但报告其工具视图中 `request` 为没有可见 `properties` 的对象，不能看到这两个字段类型。两个导出副本经本机核对均与合成原件摘要一致；没有重新生成图片。Cowork 所见为 Agent 对 Host 工具视图的报告，不能仅凭它断言缺陷位于哪一层。

为处理该兼容差异，当前工作树将本地 Schema `$defs` 引用展开到字段位置，以让不解析 `$ref` 的 Host 能收到完整嵌套字段；保留运行时校验和输入约束。相关模型、协议和共享 stdio 测试 15 项通过；最终 Schema 尚待三个 Host 重新加载验证。

最终 Schema 展开后，三个 Desktop 重启并加载各自的工作树隔离服务。Cowork 和 DSH 的 Agent 均报告 `request.properties` 可见，`family` 和 `idempotency_key` 为必填字符串；Codex 工具声明同样显示完整嵌套类型。三个会话各自构造 512×512 合成生成请求、查询成功任务并导出，导出文件 `contract-cowork-inline.png`、`contract-dsh-inline.png`、`contract-codex-inline.png` 经本机独立计算 SHA-256 均为 `b768ea017c93ad562cae4c99ad7d34bfb409ffedad1f378564f5b7a260969515`。合成图片一致是替身固定输出的预期行为。各 Host 的脱敏提交账本分别累计 2、2、4 条，包含此前测试；本轮各新增一条。此前错误纠正和幂等复用的会话证据见上文。该结果仅证明开发工作树与本地替身，正式发布安装的三个 Host 验收尚未进行，未提交真实供应商请求。

最终 Schema 的完整回归为 293 通过、1 跳过；严格校验通过变更和全部 10 个主规范。其后增强递归字段描述断言，相关协议测试 12 项通过。

隔离验收结束后，已从三个 Host 配置移除 `zhenzhen-contract-test` 条目并停止相应进程、移除测试服务入口；正式服务条目保留。`.cache/contract-host-harness/` 中的测试原件和脱敏提交账本保留作为证据。
