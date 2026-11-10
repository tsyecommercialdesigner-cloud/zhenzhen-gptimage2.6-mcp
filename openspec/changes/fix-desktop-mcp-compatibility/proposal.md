# Proposal

## Why

Claude Desktop 的并行 MCP 实例争用同一数据目录而启动失败；DSH 桥接只将内容块文本交给模型，导致结果原件路径不可见，实际会话还出现图片无法预览。需要在保留数据安全边界的前提下改善 Desktop 使用体验。

## What Changes

- 让工具文本内容包含与结构化结果一致的安全结果信息，保留结构化结果、错误状态及图片内容块。
- 排查 DSH 图片预览失败的具体环节，按证据修复可由本项目控制的部分并记录 Host 限制。
- 避免 Claude Desktop 的重复服务配置争用同一目录；保留单目录单实例，提供正确的配置和验证步骤。
- 使用已发布版本和目标数据目录分别完成三个 Desktop 的真实验收，记录实际结果及收费授权。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `image-results`：兼容只读取文本内容的 Host，使结果、原件定位信息及预览限制可见。

## Impact

影响 MCP 结果格式、相关测试及 Host 文档；不改变图像原件、队列幂等或单目录单实例约束。实际 Desktop 展示依赖 Host 和模型服务，需要实测。
