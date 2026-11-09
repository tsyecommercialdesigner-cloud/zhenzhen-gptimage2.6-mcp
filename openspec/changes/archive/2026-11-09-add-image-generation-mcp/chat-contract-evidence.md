# Chat 接口探测记录

日期：2026-11-09（Asia/Shanghai）。用户授权最多 10 次收费请求，本轮实际发出 2 次，无自动重试。HTTP 200 不代表已核验账单或图片质量；本轮检查请求接受情况及响应结构，未下载、渲染或验收图片内容。其余 8 次额度未使用。

共同设置：`POST https://ai.t8star.org/v1/chat/completions`，Bearer 认证，JSON，`stream=false`，600 秒超时；未传 `tools`、`tool_choice`、`size` 或质量参数。项目无 `.env`，从指定 Windows 用户级变量读取密钥，未输出或保存密钥。

| 序号 | 模型 | 输入 | 结果 |
| --- | --- | --- | --- |
| 1 | gpt-image-2.6-flare | messages 中 user.content 为文本，要求生成白底蓝色杯子 | HTTP 200，finish_reason=stop |
| 2 | gpt-image-2.6-sunburst | user.content 为 text 与 image_url 数组；image_url.url 为合成 256×256 PNG 的 data URL，要求把蓝方块变红 | HTTP 200，finish_reason=stop |

两次响应顶层字段均为 `id/model/object/created/choices/usage`。`choices[].message` 含 `role` 与字符串 `content`；content 包含提示词及 `![image1](图片URL)`、`[下载1](图片URL)`。URL 已从记录中移除。两次均不需要函数工具定义。

由此采用的 Chat 基础契约：文本输入可以使用字符串；带图输入使用 `{type:"text",text:...}` 与 `{type:"image_url",image_url:{url:"data:image/png;base64,..."}}` 内容块；同步输出解析 message.content 的 Markdown 图片链接。相同图像的下载链接应去重，不计为第二张图片；不抓取任意普通文本链接作为生成图片。

证据范围：基础 flare 文生图与基础 sunburst 单图输入被接受，图片内容未验证；不证明六个模型全部组合、2k/4k 尺寸参数传递、多个参考图、裸 Base64、图片 URL 输入或错误响应语义。不得把该证据作为 Generations.image 的编码支持证明。

本地计数账本及脱敏结果：`.cache/chat-contract/attempts.jsonl`、`result-1.json`、`result-2.json`。后续若使用剩余额度，继续累计该账本，不能从零计数。
