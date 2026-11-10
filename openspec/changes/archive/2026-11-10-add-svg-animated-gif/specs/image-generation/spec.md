## MODIFIED Requirements

### Requirement: 参数映射和同步响应
系统 SHALL 仅通过 t8-star 的 Generations、Flux 和 Chat 调用，默认同步；支持经验证的 GIF 显式异步模式，按适用契约映射参数，不自动跨通道切换。

#### Scenario: 解析 Chat 结果
- **WHEN** message.content 包含 Markdown 图片和相同下载链接
- **THEN** 提取并去重图片目标，普通文本不作为图片成功结果

#### Scenario: 原有同步通道
- **WHEN** 旧请求未选择新通道和输出格式
- **THEN** 保持原有默认行为和同步接口请求

## ADDED Requirements

### Requirement: GIF 异步生成
系统 SHALL 提供已验证的 flare 基础型号 GIF 显式异步模式，并在提交后持久化远程任务 ID 后查询结果；其他未经验证的异步组合在提交前拒绝。

#### Scenario: 同步默认
- **WHEN** 调用者不指定执行模式
- **THEN** 使用原有同步路径和旧幂等行为

### Requirement: SVG 与 GIF 请求
系统 SHALL 提供显式 SVG、GIF 文生图输出格式，使用 t8-star，并在提交前验证型号、尺寸、帧参数和 SVG 绘制模型；未确认的组合明确拒绝。比例使用 `aspect_ratio`，auto 不发送尺寸字段，像素尺寸使用可选 `size`；供应商可能将 `size` 转换为比例。

#### Scenario: SVG 绘制模型
- **WHEN** 请求 SVG 生图且所选通道支持该参数组合
- **THEN** 使用已配置的 SVG 绘制模型、单图数量和供应商格式参数

#### Scenario: SVG 型号限制
- **WHEN** 请求 SVG 且路由结果不是已验证的 `gpt-image-2.6-flare` 基础型号
- **THEN** 提交前拒绝并说明目前仅开放已验证的 Flare 型号，不自动切换型号

#### Scenario: GIF 带参考图
- **WHEN** GIF 请求包含参考图且所选通道未确认支持该组合
- **THEN** 在远程提交前明确拒绝，不丢弃参考图

#### Scenario: 不支持的格式和接口组合
- **WHEN** 请求的格式和通道组合未经支持
- **THEN** 提交前返回明确错误，不静默降级为静态图片

#### Scenario: SVG 与 GIF 仅支持文本
- **WHEN** SVG 或 GIF 请求包含参考图、蒙版或标注层
- **THEN** 提交前拒绝，不忽略输入

#### Scenario: 供应商 GIF 拼图尺寸超限
- **WHEN** 已确认适用该拼图规则的通道收到 4 帧、1024×1024 单帧 GIF 请求
- **THEN** 提交前拒绝，并提示缩小单帧或减少帧数

#### Scenario: 供应商 SVG 画布面积不足
- **WHEN** 已确认适用该画布规则的通道收到 512×512 的 SVG 请求
- **THEN** 提交前拒绝，并说明画布面积低于最低要求
