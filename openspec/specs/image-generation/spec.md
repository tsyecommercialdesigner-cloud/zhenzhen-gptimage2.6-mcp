# image-generation Specification

## Purpose

提供统一的同步图像生成行为，使六个目标模型通过 Generations、Flux 格式或 Chat 接口使用，同时明确尺寸路由、参考图输入及不同接口的限制。

## Requirements

### Requirement: 通道与请求校验
系统 SHALL 默认使用 Generations，选型优先级为 Generations、Flux、Chat；不在失败后自动切换通道或模型。仅支持六个指定 2.6 模型，prompt 与 template_code 必须恰选一个。

#### Scenario: 默认生成
- **WHEN** 用户提交有效请求但省略 channel
- **THEN** 使用 Generations 同步生成，返回任务状态与结果

#### Scenario: Flux 带参考图
- **WHEN** Flux 请求包含参考图
- **THEN** 发送前拒绝，不静默丢弃参考图

### Requirement: 尺寸与型号路由
系统 SHALL 对原有静态 Generations/Flux 请求要求 1–4096 的整数宽高，按长边 ≤1024、≤2048、≤4096 在选定系列内路由基础、2k、4k 型号；显式型号必须一致。SVG/GIF 按其格式请求规则允许 auto 和比例。

#### Scenario: 路由到 2k
- **WHEN** flare 请求宽高为 2048×1024
- **THEN** 型号固定为 gpt-image-2.6-flare-2k，重试不改变型号

### Requirement: Chat 不定制尺寸
系统 SHALL 对 Chat 拒绝 width/height、不发送 size，并在能力说明及结果 warnings 提示尺寸不可定制；无显式型号时选择系列基础型号。

#### Scenario: Chat 返回不同尺寸
- **WHEN** Chat 返回有效图片
- **THEN** 保存实际尺寸，不因型号名暗示的尺寸不同判定失败，不自动缩放原图

### Requirement: 参数映射和同步响应
系统 SHALL 仅通过 t8-star 的 Generations、Flux 和 Chat 调用，默认同步；支持经验证的 GIF 显式异步模式，按适用契约映射参数，不自动跨通道切换。原有静态参数按[设计](../../changes/archive/2026-11-09-add-image-generation-mcp/design.md)第 12 节映射；Generations 参考图使用 PNG data URL，Chat 使用 text/image_url 内容块且 stream=false。

#### Scenario: 解析 Chat 结果
- **WHEN** message.content 包含 Markdown 图片和相同下载链接
- **THEN** 提取并去重图片目标，普通文本不作为图片成功结果

#### Scenario: 原有同步通道
- **WHEN** 旧请求未选择新通道和输出格式
- **THEN** 保持原有默认行为和同步接口请求

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

### Requirement: 凭据来源隔离
系统 SHALL 使用 ZHENZHEN_GPTIMAGEGEN_API_KEY，按项目 .env、进程环境、Windows 用户级环境的顺序读取；仅来源或字段缺失时才回退。已定义的空值、非法值、重复字段及文件读取或解析错误必须失败，不向父目录搜索，不记录或持久化密钥。

#### Scenario: 本地配置缺失
- **WHEN** .env 不存在但用户环境有密钥
- **THEN** 使用该值认证，日志和任务记录不含密钥

#### Scenario: 文件字段为空
- **WHEN** .env 已定义目标字段但值为空或空白，且进程或用户环境存在密钥
- **THEN** 返回配置错误，不回退或发送请求

#### Scenario: 进程字段为空
- **WHEN** .env 中目标字段缺失而进程环境已定义空值，且用户环境存在密钥
- **THEN** 返回配置错误，不回退到用户环境

#### Scenario: 目标字段重复或文件不可解析
- **WHEN** .env 重复定义目标字段或无法读取、解析
- **THEN** 返回脱敏配置错误，不使用环境中的密钥
