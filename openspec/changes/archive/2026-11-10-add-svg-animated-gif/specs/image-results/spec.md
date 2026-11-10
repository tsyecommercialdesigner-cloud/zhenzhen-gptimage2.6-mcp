## MODIFIED Requirements

### Requirement: 完整结果落盘
系统 SHALL 验证图片集合后再标记成功，登记实际尺寸、媒体类型、字节数、路径及摘要；原有静态 Generations/Flux 尺寸不符进入 recovery_pending，Chat 不作请求尺寸比较；GIF 按用户选择的尺寸策略处理。

#### Scenario: 部分下载失败
- **WHEN** 多张图片中一张下载失败
- **THEN** 不标记整任务成功，保留恢复材料且不重新生成

#### Scenario: 格式与请求不符
- **WHEN** 请求 SVG 或 GIF 但供应商返回其他格式或不符合动画要求的文件
- **THEN** 不标记成功，保留恢复证据且不重新生成

#### Scenario: GIF 精确尺寸不符
- **WHEN** GIF 实际尺寸与精确请求不同且使用默认严格策略
- **THEN** 原样保存并报告原件和实际尺寸，任务进入 recovery_pending，不缩放或重新生成

#### Scenario: 用户接受 GIF 实际尺寸
- **WHEN** 用户明确接受已验证的尺寸不符 GIF，或提交时明确选择接受实际尺寸策略
- **THEN** 保存实际尺寸及警告并标记成功，不触发新的生成请求

## ADDED Requirements

### Requirement: 动画与矢量原件
系统 SHALL 对有效 SVG 和多帧 GIF 原样保存并验证摘要；GIF 帧、每帧时长及循环信息不得因保存或预览而丢失。

#### Scenario: 动画落盘
- **WHEN** 供应商返回有效多帧 GIF
- **THEN** 保存原始 GIF 字节，查询返回文件路径、实际尺寸和动画元数据

#### Scenario: 不安全 SVG
- **WHEN** SVG 含脚本、外部资源或其他不安全内容
- **THEN** 拒绝将其作为可展示的成功结果并保留错误与恢复证据

### Requirement: 新格式预览
系统 SHALL 在不改变原件的前提下提供安全且受现有限额约束的预览；无法提供预览时返回可用的原件信息和明确提示。

#### Scenario: GIF 静态预览
- **WHEN** Host 仅支持静态预览
- **THEN** 可提供首帧并明确标记为静态预览，原始 GIF 保持动画
