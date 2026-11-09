## Purpose

提供统一的同步图像生成行为，使六个目标模型通过 Generations、Flux 格式或 Chat 接口使用，同时明确尺寸路由、参考图输入及不同接口的限制。

## ADDED Requirements

### Requirement: 通道与请求校验
系统 SHALL 默认使用 Generations，选型优先级为 Generations、Flux、Chat；不在失败后自动切换通道或模型。仅支持六个指定 2.6 模型，prompt 与 template_code 必须恰选一个。

#### Scenario: 默认生成
- **WHEN** 用户提交有效请求但省略 channel
- **THEN** 使用 Generations 同步生成，返回任务状态与结果

#### Scenario: Flux 带参考图
- **WHEN** Flux 请求包含参考图
- **THEN** 发送前拒绝，不静默丢弃参考图

### Requirement: 尺寸与型号路由
系统 SHALL 对 Generations/Flux 要求 1–4096 的整数宽高，按长边 ≤1024、≤2048、≤4096 在选定系列内路由基础、2k、4k 型号；显式型号必须一致。

#### Scenario: 路由到 2k
- **WHEN** flare 请求宽高为 2048×1024
- **THEN** 型号固定为 gpt-image-2.6-flare-2k，重试不改变型号

### Requirement: Chat 不定制尺寸
系统 SHALL 对 Chat 拒绝 width/height、不发送 size，并在能力说明及结果 warnings 提示尺寸不可定制；无显式型号时选择系列基础型号。

#### Scenario: Chat 返回不同尺寸
- **WHEN** Chat 返回有效图片
- **THEN** 保存实际尺寸，不因型号名暗示的尺寸不同判定失败，不自动缩放原图

### Requirement: 参数映射和同步响应
系统 SHALL 按设计第 12 节映射白名单字段；Generations 参考图使用 PNG data URL，Chat 使用 text/image_url 内容块且 stream=false；不得发送异步生成或远程轮询请求。

#### Scenario: 解析 Chat 结果
- **WHEN** message.content 包含 Markdown 图片和相同下载链接
- **THEN** 提取并去重图片目标，普通文本不作为图片成功结果

### Requirement: 凭据来源隔离
系统 SHALL 使用 ZHENZHEN_GPTIMAGEGEN_API_KEY，按 .env 非空值、进程环境、Windows 用户环境的顺序读取，不向父目录搜索，不记录或持久化密钥。

#### Scenario: 本地配置缺失
- **WHEN** .env 不存在但用户环境有密钥
- **THEN** 使用该值认证，日志和任务记录不含密钥
