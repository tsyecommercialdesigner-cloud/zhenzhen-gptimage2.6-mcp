# t8-star 接口支持与证据

本项目目标是六个 GPT Image 2.6 型号。能力状态与已实现的协议适配分开记录：

| 能力 | 证据 |
| --- | --- |
| Generations 文生图与 PNG data URL 单图 | `gpt-image-2.6-flare` 单次请求返回图像，参见[归档的供应商缺口验证记录](../openspec/changes/archive/2026-11-09-add-image-generation-mcp/provider-validation.md)；其他型号未实测，多图测试见下文 |
| Chat 文生图 | 基础 flare 单次返回 Markdown 图片链接；实际图片内容未验证 |
| Chat PNG data URL 单图 | 基础 sunburst 请求返回 Markdown 图片链接；图片内容未验证 |
| Chat 尺寸 | flare 和 flare-2k 的顶层 `size` 两次均未兑现尺寸；接口按不可定制尺寸处理 |
| Flux 格式 | 采用 Generations 同端点简化字段，flare 基础、2k 和 4k 有限实测；不支持参考图 |
| 图片 Base64 响应 | 支持解析参考契约中的字段；2.6 实测尚未确认 |

Flux 基础和 2k、Generations 双参考图已有有限实测。flare-4k 显式后缀触发重复 `-4k-4k` 的 503；基础名配合 4k 尺寸已有两次成功，产品已针对 flare 映射，修复后的独立 stdio MCP Flux 4k 调用及落盘亦已实测成功，详情见 [供应商集成验收](provider-acceptance-20261109.md)。sunburst 4k 尚未收费实测；本模块的自动化测试使用 HTTP 替身。
未覆盖的能力不得作为已验证能力宣传，供应商账单和模型质量亦未独立核验。
