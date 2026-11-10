# t8-star SVG 参数验证（2026-11-10）

## 目标与边界

验证 `https://ai.t8star.org/v1/images/generations` 的 SVG 参数与响应。用户授权必要的收费测试；本轮发送四次独立请求，均得到明确 HTTP 响应，没有对结果未知的请求重发。使用 Windows 用户级 `ZHENZHEN_GPTIMAGEGEN_API_KEY`，不记录密钥、认证头或图片 URL；实际账单未核对。前一轮三次 SVG/GIF 探测和其独立授权范围见 [设计记录](design.md)。

## 请求与结果

四个请求均使用 `output_format=svg`、`n=1`、`size=1024x1024`，以及简短的蓝色陶瓷杯矢量图提示词；每行仅发送一次。

| 型号 | SVG 参数形式 | HTTP | 脱敏供应商错误 |
| --- | --- | --- | --- |
| `gpt-image-2.6-flare` | `"svg":{"model":"gpt-5.4-mini"}` | 400 | `Bad request to openai: SVG generation requires '***.model'.` |
| `gpt-image-2.6-flare` | `"svg.model":"gpt-5.4-mini"` | 400 | 同上 |
| `gpt-image-2.6-sunburst` | `"svg":{"model":"gpt-5.4-mini"}` | 400 | 同上 |
| `gpt-image-2.6-flare` | `"svg":{"model":"gpt-5.4-mini","reasoning":{"effort":"low"}}` | 400 | 同上 |

这四次响应都没有返回可验证的 SVG 文件。供应商错误信息遮蔽了模型字段名称，不能据此确定字段被哪个环节忽略、是否支持该模型、是否与账号分组或 SVG 权限有关。原厂 [Image API 文档](https://developers.openai.com/api/reference/resources/images/methods/generate) 描述了可选的 `svg` 对象，但它不证明 t8-star 已透传该字段。

实际请求和脱敏响应账本保存在忽略目录 `.cache/svg-confirm-20261110/ledger.jsonl`、`.cache/svg-confirm-20261110/dotted/ledger.jsonl`、`.cache/svg-confirm-20261110/sunburst/ledger.jsonl` 和 `.cache/svg-confirm-20261110/reasoning/ledger.jsonl`；账本不含密钥。后三项目录按参数形式或型号区分，与第一次请求的原始账本分开保存。

## 后续所需证据

需要供应商提供 t8-star 复数路径下该型号和账号分组可用的完整 SVG JSON 示例与成功响应，或明确解释参数转发/权限条件。可提供本页的脱敏请求形式与错误供其排查；不应将已失败的尝试作为支持成功的证据，也不应重复发送结果未知的请求。

## Chat Completions 单次探测

用户授权针对 `POST /v1/chat/completions` 进行一次测试。使用 `gpt-image-2.6-flare`、`stream=false`，在 user message 中请求返回 SVG 矢量杯子图；未发送未经确认的 SVG 参数。2026-11-10 返回 HTTP 403，错误为余额不足，响应中报告余额 `¥-0.029342`。未返回可验证的图片，未自动重试；这次结果不能说明 Chat 通道是否支持 SVG。脱敏账本位于 `.cache/chat-svg-probe-20261110/ledger.jsonl`；由于 Windows 控制台不能编码错误消息中的货币符号，程序在已持久化明确 403 响应后额外记录了输出阶段的 `UnicodeEncodeError`，不表示提交结果未知。实际账单尚未核对。

用户说明中转站切换账户后授权重试，同日使用相同请求独立提交 1 次，再次得到 HTTP 403，响应仍报告余额不足 `¥-0.029342`；无图片，不证明 SVG 能力或接口不支持。重试账本位于 `.cache/chat-svg-probe-20261110-retry1/ledger.jsonl`。实际账单与该密钥所属账户、分组切换状态未核对。

## 更换 SVG 绘制模型

用户要求在 `/v1/images/generations` 将 `svg.model` 改为 `gpt-6-luna`。使用 `gpt-image-2.6-flare`、1024×1024、`output_format=svg`、`n=1` 及 `svg: {"model":"gpt-6-luna"}` 提交一次，收到明确 HTTP 403：余额不足，响应报告 `¥-0.029342`。未取得 SVG，不能判断该模型参数是否可用或已透传。账本为 `.cache/svg-confirm-20261110/luna/ledger.jsonl`；其末尾的 `UnicodeEncodeError` 是将已持久化的 403 文本输出到 Windows 控制台时产生，非请求结果未知。没有重试；实际账单未核对。

用户随后确认令牌账户 ID 为 `120510`、分组为 `default`，且控制台显示有余额；当前进程和用户级环境变量的密钥一致。按之前相同参数再提交一次，HTTP 200，返回 `data[0].url`；下载内容是可解析 SVG，根元素为 SVG，width/height 为 1024×1024、viewBox 为 `0 0 1024 1024`，文件 1073 字节，SHA-256 `48f37dbd966816397cc703ee5476ccd02840bfd1491597e79eb1302c58f0fa4a`。结果与账本保存在 `.cache/svg-confirm-20261110/luna-account-confirmed/`；简单检查未见脚本、foreignObject 或外部引用，不等于完整安全审计。本次一次生成、未自动重试，账单未核对；账户 ID 和分组由用户确认，非 API 查询结果。该结果只证明本次 flare、尺寸和参数组合，不证明其他型号、其他绘制模型或 Chat 接口支持。

## GIF 额度对照

用户要求再次提交 GIF 以对照余额。使用同一用户级密钥和 `/v1/images/generations`，对 `gpt-image-2.6-flare` 以 `output_format=gif`、`size=512x512` 发送一次，HTTP 403 余额不足，响应报告 `¥-0.029342`，未生成图片。未自动重试；记录保存在 `.cache/gif-quota-check-20261110/ledger.jsonl`。此结果表明本次 GIF 请求也受到额度限制，无法用本次对照判断 SVG 渠道；实际账单及密钥分组未核对。

用户随后要求核对配置并再测一次。项目根目录不存在 `.env`，不能比较该文件与用户级密钥；当前进程和 Windows 用户级环境变量均有值且一致，依项目优先级本次使用进程环境变量。相同密钥再次提交一次 GIF，HTTP 403，余额报告仍为 `¥-0.029342`；未自动重试。账本为 `.cache/gif-quota-check-20261110-configcheck/ledger.jsonl`。一致性不证明密钥所属账户或分组正确，未记录密钥及摘要。

## 普通 PNG 额度对照

用户要求测试普通 PNG。使用相同密钥向 `/v1/images/generations` 以 `gpt-image-2.6-flare`、1024×1024 发送一次普通文生图请求，省略 `output_format`，得到 HTTP 403，提示余额不足，报告余额 `¥-0.029342`；未返回图片，未自动重试。账本为 `.cache/png-quota-check-20261110/ledger.jsonl`。这次结果不代表供应商不支持 PNG，实际账单和密钥所属账户仍未核对。

## 修复后的 MCP SVG 端到端

2026-11-10，使用独立 stdio MCP 实例和数据目录提交一次 `gpt-image-2.6-flare`、1024×1024、`svg_model=gpt-6-luna` 请求。task_id `fadb1443-cad1-44c7-9852-f206263f9161` 最初进入 `recovery_pending`，`attempt_count=1`；供应商原始响应已持久化。诊断显示图片是合法 SVG，带 `role` 和 `aria-labelledby`，被初版安全白名单拒绝。添加无障碍属性并通过离线测试后，对同一任务调用 `recover_task`，只重新下载和保存已有响应，未重发生成；结果 `succeeded`，尝试数仍为 1。

原件 `.cache/svg-live-mcp-20261110/images/fadb1443-cad1-44c7-9852-f206263f9161.0.svg` 是 1024×1024、849 字节的 SVG，SHA-256 为 `4f6737e54bbe07523b6042c431a69fb5cc7279b3786908f1147bc56ae9255f92`。该证据证明恢复后的 MCP SVG 路径；不证明最初请求直接成功落盘，也不证明真实 MCP GIF 或其他型号组合。账单未核对。

## Sunburst 同步 SVG 对照

2026-11-10，用户授权一次收费测试，使用 `POST https://ai.t8star.org/v1/images/generations`（不带异步参数），请求 `gpt-image-2.6-sunburst`、`size=1024x1024`、`output_format=svg`、`n=1` 及 `svg: {"model":"gpt-6-luna"}`，返回 HTTP 400：`Bad request to openai: SVG generation requires '***.model'.` 未返回 SVG，未重试。脱敏账本位于 `.cache/t8-sunburst-svg-sync-20261110/ledger.jsonl`，实际账单未核对。与同参数异步请求的失败对照表明该错误在同步与异步路径均可出现，不能仅归因于异步接口；上游字段处理、模型或账户分组等原因仍未确认。
