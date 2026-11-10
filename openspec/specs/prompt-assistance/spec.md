# prompt-assistance Specification

## Purpose

为电商运营 Agent 提供可读取的商品事实、构图和参考图使用指引，使提示词优化在当前 Host 会话内完成，并让用户了解不同图像接口的能力和尺寸限制。

## Requirements

### Requirement: 提示词优化指引
系统 SHALL 提供 prompt-guide Resource 和 optimize_ecommerce_prompt Prompt，使用用户需求与商品事实构造指令，不自行调用付费模型或补造商品事实。

#### Scenario: 优化电商提示词
- **WHEN** Agent 提供需求、商品事实及用图目的
- **THEN** 系统返回供 Host 优化的指令，且不创建图像任务或发送付费请求

### Requirement: 能力与恢复说明
系统 SHALL 提供 capabilities 与 recovery-guide Resource，说明验证范围、Generations → Flux → Chat 优先级及未知结果的处理路径。

#### Scenario: 选择 Chat
- **WHEN** Agent 读取能力说明并选择 Chat
- **THEN** 说明明确要求调用前提示用户尺寸不可定制，不将未验证组合标为已验证

### Requirement: 格式与验证说明
系统 SHALL 向 Host 说明 SVG/GIF 格式、动态原件与静态预览的区别、渠道限制及各组合的验证状态，不把供应商文档支持表述为本项目实测通过。

#### Scenario: 查询新格式能力
- **WHEN** Host 查询 SVG 或 GIF 能力
- **THEN** 说明仅使用 t8-star、文生图限制及真实验证范围，并说明 GIF 预览可能是静态首帧、原件保留动画及尺寸不符的处理方式，SVG 原件保留矢量内容
