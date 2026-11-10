# Proposal: SVG 与动态 GIF 生成

## Why

现有 MCP 只能校验并保存 PNG、JPEG、WebP，无法交付可缩放 SVG 或保留动画的 GIF。用户需要通过 Agent 生成并取得这两种格式的原始文件。

## What Changes

- 增加显式 SVG 和 GIF 输出选项，GIF 原样保留所有帧、帧延时与循环信息；查询和预览不改写原件。
- 仅使用已订阅的 t8-star，保留同步路径，并为已实测的 flare GIF 增加可显式选择的异步提交、查询及远程 ID 恢复；不接入其他供应商。
- 以用户提供的数据模型、接口契约及实测分别标识可信度：t8-star GIF 已返回动画，flare 使用 `gpt-6-luna` 绘制模型的一个 SVG 组合已实测成功；截图仅作为数据模型参考，不替换此前提供的接口路径。
- 扩展数据模型、快照幂等、格式安全校验、资源限制、异常恢复和向后兼容；对 SVG/GIF 的限制与不支持项在发送前明确提示。
- 用户指定的 GIF 动画必须实际具有多帧；不以静态 GIF 或 PNG 冒充成功。
- SVG 暂仅使用已验证的 `gpt-image-2.6-flare` 基础型号；其他型号请求在提交前拒绝。
- GIF 请求精确尺寸与实际不一致时，默认保留原件并进入待处理状态；允许用户显式接受该结果，不重发生成请求。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `image-generation`: 输出格式、SVG/GIF 文生图参数校验和尺寸映射。
- `image-results`: SVG 与动态 GIF 安全验证、原样落盘及预览。
- `task-queue`: 将新格式纳入既有容量、期限、幂等和批量行为。
- `task-recovery`: 保留同步提交未知保护与已有响应的本地恢复，并支持持久化远程 ID 后恢复查询。
- `prompt-assistance`: 向 Host 说明格式、供应商和验证范围。

## Impact

涉及 MCP 输入/输出、供应商适配、调度、SQLite 迁移、结果保存与预览、配置及文档；现有静态接口和旧任务必须兼容。t8-star 使用既有密钥来源。新增真实供应商验收需单独授权。
