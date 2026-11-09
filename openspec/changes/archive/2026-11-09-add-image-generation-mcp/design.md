# Design

> 设计状态：技术栈已确定；用户已批准方案 B 的八模块职责划分、执行约束及 NFR-01 至 NFR-11 的规则与优先级。接口契约及具体配置值仍待补齐，本文件不代表完整设计已批准或可开始实现。

## Context

动机及功能范围见 [proposal.md](proposal.md)。当前仓库只有规划资料，没有业务代码、测试或既有数据库需要兼容。

已确定：Python 3.12.14、uv、FastMCP、SQLite、httpx，本地 stdio 运行；t8-star 的六个指定模型，通过 Images 和 Chat 两个通道同步生成图片。单批最多 20 个请求，全局最多 20 个未完成任务，最多 6 个并发提交。httpx 异步 I/O 用于并发通信，不增加异步生成产品模式。

接口契约参考用户指定的 `references/API-ENDPOINT-GPTIMAGE.md`，复用其中相同 Generations 接口的请求与响应结构。该文档的实测模型为 2.5 系列，不构成六个 2.6 模型的实测记录；Chat 基础输入输出已通过本轮两次探测补充；Generations 参考图字符串编码和失败响应仍未覆盖。详见下述接口映射。

## Goals / Non-Goals

**Goals:**

- 在一个本地 Python 进程内组织 MCP 接入、生成执行、持久化和结果处理。
- 明确队列容量、幂等、状态转换及文件落盘的职责归属，避免多个模块各自维护一套任务状态。
- 将供应商协议差异限制在适配模块，使两个通道共享队列、历史和恢复逻辑。
- 采用用户批准的方案 B，以八个职责模块为基础细化设计。

**Non-Goals:**

- 不引入微服务、Redis、外部任务队列或独立常驻 Worker 服务。
- 不实现远程异步任务提交与轮询，不承诺同步请求中断后可从供应商找回结果。
- 不在本轮实现业务代码或确定 FastMCP 等依赖的最终版本。

## Decisions

### 1. 已确定的技术职责

| 技术 | 本项目中的职责 |
| --- | --- |
| Python 3.12.14 + uv | 运行环境、包与依赖管理 |
| FastMCP | stdio MCP 接入，注册 Tools、Resources、Prompts，组织协议输出 |
| httpx | 调用供应商同步生成接口，以及按最终响应契约获取图片内容 |
| SQLite | 持久化任务状态、幂等记录、结果索引及模板数据 |
| 本地文件系统 | 保存图片及必要的恢复材料；数据库保存关联信息 |

技术栈由用户指定，此处不另行提出替换框架。具体版本兼容性和 SDK 用法在后续详细设计中核对。

### 2. 模块划分决策：采用方案 B

用户已批准方案 B。以下都是同一个 Python 包内的逻辑模块，不是独立服务；模块可以包含多个文件。方案 A、C 保留为未采用的备选方案记录。

#### 方案 A：精简组织，5 个模块（未采用）

| 模块 | 职责 |
| --- | --- |
| `server` | FastMCP 入口、配置与生命周期、Tools / Resources / Prompts 注册及输出 |
| `jobs` | 输入校验、批量入队、幂等、6 并发调度、状态转换、重启恢复 |
| `provider` | t8-star HTTP 通信，Images / Chat 请求构造和响应解析 |
| `storage` | SQLite、历史查询、结果索引、图片文件保存与一致性处理 |
| `prompts` | 提示词优化指引、模板保存与查询、快捷代号解析 |

优点：文件导航简单、初始协作成本低。代价：`jobs` 同时承载业务与执行调度，`storage` 同时承载数据库与文件恢复，后续复杂度容易集中。

适合：更看重快速完成首版，接受后续拆分。

#### 方案 B：按职责拆分，8 个模块（已批准）

| 模块 | 负责什么 | 边界 |
| --- | --- | --- |
| `bootstrap` | 配置读取、依赖组装、进程生命周期、日志初始化、启动恢复顺序 | 不处理生成业务；日志不写入 stdio 协议输出流 |
| `mcp_api` | Tools / Resources / Prompts 注册，协议输入输出，图片展示内容封装 | 不直接写 SQL，不直接调用供应商 |
| `generation` | 用例编排、批量校验、模板展开后的请求快照、幂等规则、入队决策、任务状态转换规则 | 是任务业务规则的唯一归属，不自行维护第二份队列 |
| `scheduler` | 领取持久化待执行任务、控制 6 个并发请求、调用生成执行流程、协调关闭与启动恢复 | 调用 `generation` 执行状态转换，不绕过容量与幂等规则 |
| `providers/t8_star` | 共享 HTTP 客户端与认证配置，Images / Chat 两个适配器，协议错误归类 | 不入队、不操作数据库、不执行 Chat 返回的函数工具调用 |
| `repository` | SQLite 事务、容量检查与入队原子操作、幂等唯一约束、任务及模板读写、历史查询 | 持久化 `generation` 的规则，不决定供应商请求格式 |
| `artifacts` | 图片内容处理、临时文件与最终文件落盘、结果完整性检查、落盘恢复 | 不重新提交生成请求；MCP 展示封装归 `mcp_api` |
| `prompts` | 电商优化指引、模板管理业务、快捷代号解析 | 不额外调用模型优化提示词；优化由 Host Agent 完成 |

依赖方向：`bootstrap` 组装全部模块；`mcp_api` 调用 `generation` / `prompts`；`scheduler` 驱动 `generation` 的执行流程；业务模块通过 `repository` 持久化，通过 `providers/t8_star` 生成，通过 `artifacts` 保存结果。底层模块不反向依赖 FastMCP。

选择理由：当前真正复杂的部分是同步请求中断、并发容量和落盘恢复，这一方案为它们划清职责，同时无需引入通用插件系统或多层抽象框架。

#### 方案 C：严格分层，4 层及独立组装入口（未采用）

| 层/入口 | 包含职责 |
| --- | --- |
| `presentation` | MCP Tools / Resources / Prompts 与协议输出 |
| `application` | 生成、批量、查询、模板、恢复用例与调度协调 |
| `domain` | 状态转换、容量及幂等规则、内部实体和存储/供应商接口契约 |
| `infrastructure` | SQLite 仓储、httpx 供应商适配、文件存储实现 |
| `bootstrap` | 配置、依赖注入、进程生命周期 |

优点：业务规则与框架隔离明确，后续替换存储或扩展供应商时边界更稳定。代价：接口、对象映射和跨层文件较多；层数少并不意味着代码量更少。

适合：已经计划支持多个供应商、多个维护者长期协作。当前只有一个供应商，收益尚不足以优先选择。

### 3. 方案 B 的执行约束（已批准）

- **本地查询与远程同步分开表达**：查询读取本地状态和历史，不访问假定存在的远程轮询接口。MCP 生成调用等待同步请求及保存完成后返回；长调用超时、客户端取消和重启恢复遵守下述已批准的非功能约束，任务总期限采用 600 秒，不自动增加“立即返回任务 ID”的异步生成模式。
- **队列以 SQLite 为事实来源**：容量检查、幂等检查及入队在同一事务内完成；不要依靠内存计数保证全局 20 个上限。整批接收或整批拒绝，避免静默部分接收。
- **并发槽覆盖完整远程请求**：从开始提交持有到收到完整响应或请求结束，防止只限制发送瞬间却放任大量生成请求并行。后续图片下载与落盘需独立限制资源使用，但任务保存完成前仍占队列容量。
- **幂等不等于提示词去重**：由调用方提供幂等键并绑定请求摘要；同键同内容返回已有任务，同键不同内容报冲突。用户主动使用新键可以再次生成相同提示词。
- **恢复不盲目重提**：尚未开始远程请求的任务可恢复调度；请求已开始但无可靠响应的任务标记结果未知，不自动重发。已收到且持久化完整响应的任务可恢复解析或落盘。结果未知任务继续占容量，显式结案后释放容量并保留记录；具体工具签名后续细化。
- **文件与数据库分步提交**：先写临时文件、检查并移动至最终位置，再提交结果索引；恢复流程识别中间状态。不能把文件写入与 SQLite 事务视为一个原子操作。
- **单数据目录单运行实例**：首版对同一数据库只允许一个活动 Server 实例，防止多个 Host 各自启动 6 个请求而突破全局上限。不同实例使用不同数据目录时，各自拥有独立容量；若需要跨实例全局限额，应改为共享协调设计。

上述执行原则已批准；业务数据模型已批准，工具签名见第 10 节，数据库 DDL 见第 13 节。

### 4. 共享接口契约与初步数据模型

依据 [API-ENDPOINT-GPTIMAGE.md](../../../../references/API-ENDPOINT-GPTIMAGE.md) 的 Generations OpenAPI、请求示例及同步响应样例制定以下映射。保留原参考文档，不修改其历史记录。

| 对象 | 采用的字段与处理方式 |
| --- | --- |
| Generations 请求 | `POST /v1/images/generations`，JSON，Bearer 认证；必填 `model: string`、`prompt: string`；可选 `size: string`、`image: string[]`、`response_format: url 或 b64_json`。模型限定为已选六个 2.6 标识。未提供的可选字段不发送。 |
| 响应信封 | `data` 为图片项数组；`created`、`model`、`usage` 作为可选元数据，保留供应商原值，不从 usage 推算实际费用。空数组或缺失有效图像内容不算生成成功。 |
| 图片项 | 接受非空 `url` 或非空 `b64_json`，`revised_prompt` 可选；优先使用有效非空 Base64，否则使用 URL。空字符串不能解码为图片。返回格式按实际内容识别，不仅依赖请求中的 response_format。 |
| 归一化结果 | 图片列表及各项的来源类型、可选修订提示词、供应商元数据；下载或解码并验证后交给 `artifacts` 落盘，再登记本地路径、校验和、媒体类型及字节数。这里的本地字段是内部设计，不是供应商字段。 |
| 失败结果 | 保留 HTTP 状态和脱敏后的供应商错误摘要；无明确未受理证据时不得凭 5xx 或无法解析的响应自动重试生成。 |

参考文档的同步实测是 `data[].url`；`b64_json` 来自格式声明及示意结构，设计兼容两种表示，不声称两种都已在 2.6 上验证。200 且无法解析图像时保留恢复材料并报告响应格式错误，不以解析失败为由重发生成。

兼容边界：

- Generations.image 采用 PNG data URL 数组；基础 flare 单图已通过本次请求与结果检查，其他 MIME、多图和型号组合未验证。不得发送本地文件路径或假定支持裸 Base64。
- 既有通用契约的 `aspect_ratio` 与本参考文档的 `size` 分别保留来源；不自动同时发送两者，也不擅自规定转换或优先级。`quality` 只见于分组描述，待确认目标分组后决定是否暴露。
- 本项目新增尺寸路由，采用下述本地路由规则；不把参考文档的 2.5 实测与尺寸限制描述为已验证的 2.6 供应商能力。
- `/v1/images/edits`、`async=true`、`/v1/images/tasks/{task_id}` 不在本期范围。文档所称“所有模型异步”不覆盖用户已明确的六个 2.6 模型不支持异步的决定。
- 文档没有 `/v1/chat/completions`。Chat 通道仍在范围内，但不能用 Images 的 `data[]` 冒充 Chat 返回结构，或将普通文本响应视为图像成功。

### 5. 600 秒超时口径

按已批准的总期限设计，将用户指定的 600 秒用于每个逻辑任务的总预算：从入队事务提交开始，覆盖排队、所有最多三次尝试、退避、图片获取及保存。不为每次重试重新分配 600 秒，因此不是 3 × 600 秒；批量中的任务分别记录入队时间和截止时间。

HTTP 连接、读、写、连接池等待的阶段上限均不超过 600 秒及当前剩余预算；另设应用层墙钟截止时间，避免多个阶段或持续分块响应累计超时。重启保留原截止时间，不重置预算；运行期间使用单调时钟计时，持久化 UTC 截止时间用于恢复。

期限耗尽时：尚未提交的任务终止为本地超时；已提交但没有可靠响应的任务归为结果未知；已持久化响应但未完成保存的任务保留材料供本地恢复，不重新生成。后续显式本地恢复使用独立有限执行预算，不重新开放原任务的远程生成预算。

600 秒不是 SQLite 锁等待或关闭宽限期的默认值。Host 若先于该期限结束调用，按已批准的取消/结果未知规则处理，不假定服务端配置能延长 Host 限制。

### 6. 尺寸路由（已批准）

最新通道策略：默认 Generations（channel=images），其次 Flux 格式（channel=flux），最后 Chat Completions（channel=chat）。这是 Agent 选型优先级，不是收费请求失败后自动切换并重新生成的策略。工具省略 channel 时固定 images；每个已接收任务的通道与型号不变。

以下尺寸路由适用于 Images/Flux。Chat 不提供尺寸定制：width/height 必须省略，默认选择 family 的基础型号；显式选择同系列 2k/4k 仍不保证实际分辨率。Host 调用前说明“Chat Completions 生成图像的尺寸由供应商决定，无法定制”，工具结果在 `warnings` 中重复该提示，无需额外确认工具或确认参数。用户需要精确尺寸时优先使用 Images/Flux，不能直接替换成 Chat；传入 Chat 宽高返回 INVALID_ARGUMENT，提示移除尺寸字段或改选接口。

TaskView 的 width/height 表示请求尺寸，Chat 为 null；ImageView 的 width/height 始终是实际文件尺寸。Chat 不因实际尺寸与型号名称不符报 RESPONSE_INVALID，也不自动裁切或缩放原图。所有通道仍执行第 8 节解码像素及文件限值。

调用者选择 `family=flare|sunburst` 和显式 `width`、`height`，按最终提交画布长边 L 路由：L ≤ 1024 使用基础型号，1024 < L ≤ 2048 使用 `-2k`，2048 < L ≤ 4096 使用 `-4k`。L > 4096 本地拒绝。系列保持不变，不跨系列降级；路由结果在入队前冻结，所有重试使用相同 resolved_model。

提供显式型号时校验尺寸档位一致，不静默切换计费型号。`auto` 尺寸无法可靠判断档位，自动路由模式要求明确宽高；仅比例输入须先展开为明确画布。尺寸为正整数，不自动裁切或放大参考图；16 倍数、3:1 比例及 8,294,400 像素约束不从旧模型盲目继承。4096 长边是本项目拟定输入上限，仍需目标模型验证。

### 7. 配置与业务数据模型（已批准）

API 密钥变量名固定为 `ZHENZHEN_GPTIMAGEGEN_API_KEY`。默认读取项目运行配置目录中的 `.env`（源码运行时为项目根目录，可显式指定绝对路径），不向父目录递归搜索。读取顺序：指定 `.env` 的非空值 → 当前进程同名环境变量 → Windows 用户级同名环境变量。文件不存在或缺少该键时回退；语法错误明确报告。密钥仅保存在内存，不进入任务 JSON、SQLite、日志或错误输出；不覆盖系统环境变量。

| 模型 | 主要字段及约束 |
| --- | --- |
| RuntimeConfig | provider、base_url、env_file、secret_source、内存密钥、data_dir、各项限额；普通配置与 secret 序列化隔离 |
| GenerationRequest | idempotency_key、channel、family、width、height、可选 explicit_model、prompt/template_code、template_variables、references；请求校验与路由后冻结 |
| RequestSnapshot | resolved_model、最终 prompt、width/height、reference 内容摘要、channel、实际供应商参数及规范化摘要；不含凭据 |
| Task | task_id、可选 batch_id、唯一 idempotency_key、snapshot、status、created_at、deadline_at、attempt_count、next_attempt_at、error_category、response_ref；总期限 600 秒 |
| Attempt | task_id、attempt_no（联合唯一）、started_at、finished_at、submission_certainty、HTTP 状态、脱敏错误、response_ref；最多 3 次，崩溃不重置 |
| ReferenceAsset | asset_id、local_path、sha256、mime_type、bytes、width、height、来源类型；传输表示由通道适配器决定 |
| ImageArtifact | task_id、index（联合唯一）、最终文件路径、sha256、mime_type、bytes、width、height、可选 revised_prompt；原始供应商响应单独受控保存 |
| PromptTemplate | code（唯一）、version、内容、变量定义、created_at、updated_at；任务保存展开快照，模板更新不改变历史请求 |
| ClosureRecord | task_id、reason、closed_at、原状态；显式结案释放名额但保留幂等与审计记录 |

状态模型（已批准）：queued → submitting → materializing → succeeded；安全失败可进入 retry_wait 后重新提交；确定失败进入 failed；未提交前超时/取消进入 expired/cancelled；远程结果未知进入 unknown；可恢复落盘失败进入 recovery_pending。unknown 与 recovery_pending 继续占容量，显式结案可转 closed。恢复只执行有证据支持的本地步骤，不能从 unknown 自动回到 submitting。

### 8. 资源限值（本地保护默认值，已批准）

这些是已批准的项目保护限额，不是供应商公开限额；允许配置但不能突破已批准的 6 并发、20 队列及 3 次尝试上限。

| 项目 | 推荐默认值 |
| --- | --- |
| 提示词 | 32 KiB UTF-8，每个任务 |
| 参考图 | 每任务最多 4 张；单图 20 MiB；合计 40 MiB |
| 图像解码 | 单图最多 16,777,216 像素；输出目标长边最多 4096 |
| 请求/响应实体 | 单个 JSON 请求 64 MiB；单个响应解压后 64 MiB，流式计数超限停止 |
| 输出图片 | 每任务最多 4 张，单图 32 MiB，累计 64 MiB；超出时明确报告，不静默截断 |
| 图片获取与解码 | 独立下载并发 2；解码并发 1；禁止一次加载所有排队任务图片 |
| MCP 预览 | 单次最多 1 张，长边 1024、编码后 ≤1 MiB；原图完整落盘，其他结果以索引返回 |
| 历史查询 | 默认 20 条，单页最多 100 条 |
| SQLite 锁等待 | 5 秒，不持锁等待网络；数据库操作失败不启动生成 |
| 优雅关闭 | 停止接收并等待在途任务的宽限期最多 30 秒，且不超过任务剩余期限；超时后不再启动请求，必要的状态持久化和资源关闭可以继续完成 |
| 下载重试 | 最多 3 次，计入原任务 600 秒总期限；不得触发重新生成 |
| 日志 | 单文件 10 MiB、最多 5 个轮转备份 |
| 磁盘余量 | 新任务接收时至少保留 2 GiB，并核算未完成任务文件预算；不足则拒绝新增，保留已有恢复材料 |

6 个请求可同时收到大响应，因此必须流式落盘并限制 JSON/Base64 解析并发；上述限值不等于进程 RSS 的硬上限，实际内存峰值需实测。

### 9. Chat 契约探测授权

用户授权本轮最多 10 次收费请求用于确认 Chat 图像契约；每次发出前持久化计数，失败和超时同样占一次，禁止隐藏重试。先验证基础文本生图，再按证据验证参考图和模型差异；得到充分证据即停止，不为用完预算而请求。测试使用简单非敏感合成图；仅保留脱敏契约摘要，不记录密钥或签名 URL。工具签名须在用户确认上述数据模型后生成。

本轮已使用 2/10 次，均返回 HTTP 200，详见 [Chat 契约探测记录](chat-contract-evidence.md)。ChatRequest 采用 model、messages、stream=false；文本 content 可为字符串，参考图采用 text/image_url 内容块与 PNG data URL。ChatResponse 使用 choices[].message.content 字符串中的 Markdown 图片链接；归一化为同一 ImageArtifact 流程，图片链接与相同下载链接去重。不要求 tools/tool_choice，不执行供应商返回的函数调用。尚未验证返回图片内容、2k/4k 尺寸传参及多参考图，不声称这些组合已通过测试。

### 10. MCP 工具签名（已批准）

以下为协议设计签名，不是实现代码。类型映射到 JSON Schema；所有工具拒绝未知参数，不接受 API 密钥、任意供应商端点或覆盖重试预算的参数。日期为 UTC RFC 3339 字符串，路径为本机绝对路径；尺寸、字节数和索引为整数。输入引用使用本地文件路径，读取后校验并冻结内容，不能把路径直接发送给供应商。

#### 公共输入类型

```text
GenerationRequest {
  idempotency_key: string,             // 1–128 字符
  channel: "images" | "flux" | "chat" = "images", // 优先级 images > flux > chat
  family: "flare" | "sunburst",       // 必填
  width?: integer, height?: integer,   // images/flux 必填；chat 不接受，尺寸由供应商决定
  explicit_model?: ModelId,            // 只能是六个目标模型，须与系列和尺寸档位一致
  prompt?: string,
  template_code?: string,
  template_variables?: object<string, string>,
  references?: ReferenceInput[]        // 默认 []，最多 4 项
}
ReferenceInput { local_path: string }
TemplateVariable { name: string, required: boolean, default?: string }
TaskStatus = queued | submitting | retry_wait | materializing |
             recovery_pending | unknown | succeeded | failed |
             expired | cancelled | closed
```

`prompt` 与 `template_code` 必须且只能提供一个。直接 prompt 不允许 template_variables；模板变量名必须匹配定义，展开结果遵守 32 KiB 限值。模板使用简单命名占位符，不执行表达式或代码。请求没有 `size=auto`、aspect_ratio 或任意参数透传；Images/Flux 的供应商 size 由 width/height 构造，Chat 不发送 size。ModelId 为第 6 节路由出的六个完整模型名。

重复幂等请求先定位已有任务。显式输入的规范化摘要用于检查冲突；已有任务继续使用原始模板版本与参考图快照，不重新读取已变化的模板或本地图片。新增请求才创建内容快照；有意采用新内容必须使用新幂等键。为此 RequestSnapshot 分别保存 `input_digest`（调用者输入）和 `resolved_digest`（冻结后的最终请求），两者均不含密钥。

#### 工具清单（12 个）

| 签名 | 语义与返回 data 类型 |
| --- | --- |
| `get_capabilities() -> Result<Capabilities>` | 只读，返回六个模型、路由规则、限额、通道能力及 verified/reference/pending/blocked 证据状态；不暴露密钥或其值 |
| `generate_image(request: GenerationRequest) -> Result<TaskView>` | 单任务同步生成并落盘；可产生费用；相同幂等请求复用已有任务，不重复提交 |
| `generate_batch(requests: list[GenerationRequest]) -> Result<BatchView>` | 1–20 项，整批校验并原子接收新增任务，最多 6 并发；接收原子不代表生成结果全成或全败 |
| `get_task(task_id?: string, idempotency_key?: string) -> Result<TaskView>` | 两种定位方式恰选一种；只查询 SQLite，不触发生成或恢复 |
| `list_tasks(status?: TaskStatus, batch_id?: string, model?: ModelId, created_from?: string, created_to?: string, limit: int=20, cursor?: string) -> Result<TaskPage>` | 历史和活动任务统一分页，limit 1–100；时间范围左闭右开，稳定按 created_at、task_id 倒序 |
| `get_image(task_id: string, image_index: int=0, include_preview: bool=true) -> Result<ImageView>` | 返回已登记文件信息，可附单张受限预览；不重新生成、不在查询时重新下载丢失文件 |
| `recover_task(task_id: string) -> Result<TaskView>` | 仅处理 recovery_pending 且存在可靠持久化响应的任务；同步重试本地解析/下载/落盘，不调用生成端点 |
| `close_task(task_id: string, expected_status: "unknown" | "recovery_pending", reason: string) -> Result<TaskView>` | 显式结案；事务内校验状态、写 ClosureRecord 并释放容量；不会取消供应商操作或删除文件 |
| `save_prompt_template(code: string, content: string, variables: list[TemplateVariable], expected_version?: int) -> Result<TemplateView>` | 无 expected_version 为创建，已存在则冲突；更新须提供当前版本，事务内比较并递增；相同内容不额外增版本 |
| `get_prompt_template(code: string) -> Result<TemplateView>` | 按快捷代号读取完整模板与变量定义 |
| `list_prompt_templates(query?: string, limit: int=20, cursor?: string) -> Result<TemplatePage>` | 按代号或内容搜索；limit 1–100，按 code 稳定分页 |
| `render_prompt_template(code: string, variables: object<string,string>) -> Result<RenderedPrompt>` | 本地展开并校验，返回 prompt、code、version；不调用任何模型，不创建生成任务 |

模板 code 限 1–64 个 ASCII 字母、数字、下划线或连字符，大小写敏感；变量 name 使用相同字符集且不得重复，required=true 不设 default；模板 content 及展开文本均最多 32 KiB。close_task 的 reason 为 1–1024 字符。游标为不透明值，绑定筛选条件；筛选条件变化时旧游标返回 INVALID_ARGUMENT。

#### 公共返回与错误约定

```text
Result<T> {
  ok: boolean,
  warnings: string[], // 默认 []，Chat 返回尺寸不可定制提示
  data: T | null,
  error: { code: string, message: string, retryable: boolean,
           task_id?: string, next_action: string } | null
}
TaskView {
  task_id, batch_id?, idempotency_key, status, resolved_model,
  channel, width, height, created_at, deadline_at, attempt_count,
  images: ImageView[], error_category?, allowed_actions: string[]
}
ImageView { task_id, image_index, local_path, sha256, mime_type,
            bytes, width, height, available: boolean }
BatchView { batch_id, items: { input_index, task: TaskView, reused: boolean }[],
            succeeded_count, unresolved_count, failed_count }
TaskPage { items: TaskView[], next_cursor: string | null }
TemplateView { code, version, content, variables, created_at, updated_at }
TemplatePage { items: TemplateView[], next_cursor: string | null }
RenderedPrompt { code, version, prompt }
Capabilities { models, routing, limits, channels, evidence }
```

工具结果以结构化内容返回上述对象，并提供简短文本摘要。generate_image、generate_batch、recover_task、get_image 每次至多附一张图像内容块，遵守第 8 节预览限制；完整原图始终落盘。预览失败不撤销已保存的生成结果，返回可用文件及展示错误说明。具体 FastMCP 封装接口由后续锁定的版本决定。

generate_image 的新请求等待至成功、确定失败、需人工处理或 600 秒截止；重复请求如果仍在执行也等待同一任务的原期限，不新建 Worker。unknown/recovery_pending 返回可操作状态，不无限等待。批量按输入顺序返回每项结果：整批请求合法且执行完成返回 ok=true，即使部分任务 failed；业务结果看各任务 status 与计数。输入校验或容量不足时 ok=false，新增任务一个也不入队。

普通 get_task 对 failed/unknown 等任务返回 ok=true 与真实状态；ok 表示查询成功，不表示图片生成成功。生成工具出现确定失败或 unresolved 状态时返回 ok=false，data 保留 TaskView，以便定位与恢复。批量混合结果语义按上段执行。MCP 工具执行失败标记与 ok=false 对齐，具体协议参数校验错误由框架处理。

错误码包括 INVALID_ARGUMENT、NOT_FOUND、IDEMPOTENCY_CONFLICT、TEMPLATE_VERSION_CONFLICT、QUEUE_FULL、RESOURCE_LIMIT、CONFIG_ERROR、PROVIDER_REJECTED、SUBMISSION_UNKNOWN、DEADLINE_EXCEEDED、RESPONSE_INVALID、ARTIFACT_UNAVAILABLE、PERSISTENCE_ERROR、STATE_CONFLICT。`retryable` 指可安全重复当前工具调用，不授权新键重新生成；生成自动重试由服务端统一完成，Host 不应额外叠加远程重试。返回前保留 task_id；协议断开无法接收时可用原幂等键查询。

recover_task 使用任务级排他锁，与 scheduler、close_task 互斥；并发重复恢复复用正在进行的本地恢复，不重复下载。单次恢复预算 600 秒，下载最多三次；不重置生成 attempt_count。close_task 遇到状态变化返回 STATE_CONFLICT；对同一已结案任务重复调用返回已有结案结果，不修改原 reason，不再次释放容量。

BatchView 使用本次调用 batch_id 与输入项关联表记录映射；复用的已有任务不修改原 task.batch_id。多次相同批量调用可能获得不同批量记录，但单项生成幂等保持；相同输入键在批内重复时按输入位置映射同一任务，冲突内容则整批拒绝。

### 11. Resources / Prompts 与能力边界

- `gptimage://capabilities`：与 get_capabilities 相同的只读能力说明，包含验证范围。
- `gptimage://prompt-guide`：电商提示词组织、商品事实约束、参考图使用与尺寸选择指引。
- `gptimage://recovery-guide`：超时、unknown、recovery_pending 的含义及工具调用路径。
- Prompt `optimize_ecommerce_prompt(requirement: string, product_facts: string, image_purpose: string)`：构造供 Host Agent 使用的优化指令；不直接访问模型，不收费，不自行补造商品事实。引用图由会话与生成请求提供，不把不可读取的图像描述成已检查。

无需为尺寸路由单独增加收费工具；get_capabilities 可展示规则，generate 校验并返回 resolved_model。暂不提供删除任务、删除图片、任意 SQL 或任意 HTTP 工具。

能力证据与产品可用性分开标注。Chat 按不可定制尺寸模式可用，尺寸探测失败不再阻塞该通道；Flux 及其他未测组合保留 reference/pending 标记。不忽略用户请求的精确尺寸，不静默跨通道重新收费。

### 12. 供应商参数映射

Flux 是 `/v1/images/generations` 的简化请求格式，不是第三个 HTTP 端点，也不新增 flux-dev 等模型。使用 `{model: wire_model, prompt: final_prompt, size: "WxH"}`，响应沿用 Images data[] 解析。现有 Flux 契约未定义参考图，首版 channel=flux 且 references 非空时在发送前明确拒绝；不得静默丢图。下表 Images 指完整 Generations 格式。

2026-11-09 供应商验收发现：显式 `gpt-image-2.6-flare-4k` 配合 4k 尺寸被服务端映射为不存在的 `gpt-image-2.6-flare-4k-4k` 并返回 503；发送基础 `gpt-image-2.6-flare` 配合 3072×2048、3840×2160 均成功返回对应尺寸。因此 Images/Flux 的内部 `resolved_model` 保持 `gpt-image-2.6-flare-4k`，但 HTTP `wire_model` 使用 `gpt-image-2.6-flare`，由供应商按尺寸路由。此例外不更改 Chat 或其他型号；sunburst 4k 的行为未实测，不能推断相同规则。详见供应商验收报告。

所有请求固定 base_url=https://ai.t8star.org，由 bootstrap 从已批准的密钥来源构造 Authorization: Bearer；凭据不进入 RequestSnapshot。适配器仅发送字段白名单，HTTP JSON 请求使用 Content-Type: application/json。内部 JSON 不直接透传至供应商。

| 内部字段 | Images Generations | Chat Completions |
| --- | --- | --- |
| resolved_model | body.model 为 wire_model；flare-4k 使用 flare 基础名，其余沿用 resolved_model | body.model 为 resolved_model |
| 最终 prompt | body.prompt | 无参考图时 messages=[{role:user,content:prompt}]；有图时为首个 text 内容块 |
| width、height | body.size="{width}x{height}"（参考契约） | 不发送 size；不接受定制宽高，按供应商输出保存实际尺寸并提示用户 |
| 冻结参考图 | body.image 为 PNG data URL 数组；基础 flare 单图已验证接受 | messages[0].content 后续 image_url 块，url="data:{mime};base64,{bytes}"；PNG 单图已实测接受 |
| response_format | 内部默认省略，解析实际 url/b64_json；不向工具暴露该选项 | 不发送 |
| stream | 不发送 | false |
| family、explicit_model | 仅用于解析 resolved_model，不发送原字段 | 同左 |
| idempotency_key、task_id、deadline、attempt | 仅本地记录，不假设供应商支持幂等头 | 同左 |
| 模板代号及变量 | 展开并冻结为 prompt，不发送模板元数据 | 同左 |

不发送 n、quality、aspect_ratio、tools、tool_choice、temperature、webhook 或 async。一个任务是一条生成请求；返回多张图由既定结果限额约束，不能把 n 当成批量任务数量。

Images/Flux 路由是客户端确定型号，不等于供应商保证精确像素。保存时读取实际尺寸；Images/Flux 与请求不一致时保留图片和原始响应，返回 RESPONSE_INVALID / recovery_pending，不静默缩放，也不重发生成。后续契约如定义了比例而非精确尺寸，应显式修订验收口径。

#### 响应解析与错误分类

Images 解析 data[]；每项优先解码非空且合法的 b64_json，否则在该项提供有效 url 时下载；如果 Base64 不合法且存在有效 URL，可恢复为 URL 获取并记录解析差异。Chat 只提取 choices[].message.content 中 Markdown 图片目标，按完整 URL 去重；普通下载链接只有与图片目标一致时才作为同一结果识别，不递归抓取网页。顶层 model/created/usage 与 Chat id 均为可选供应商元数据。

下载不携带 API Authorization，不跨主机转发密钥；仅允许 HTTP(S) 图片地址，逐次校验重定向并限制为 3 跳。远程响应及带签名 URL 存于受控恢复文件，不进入普通日志。成功要求图片可解析、数量及资源合规、文件发布完成，不以 HTTP 200 或存在 URL 单独判断成功。

| 情况 | 本地处理 |
| --- | --- |
| 连接建立前明确失败 | 可安全重试，总计不超过 3 次 |
| 明确鉴权/输入拒绝（如 400/401/403/422） | PROVIDER_REJECTED，failed；不重试；保留脱敏错误，不推断退款 |
| 429 或 5xx，无明确未受理证据 | SUBMISSION_UNKNOWN，unknown；不自动重试 |
| 读超时、写入后断连、进程在提交窗口退出 | unknown，不自动重发 |
| 完整 HTTP 200 响应但无有效图像结构 | RESPONSE_INVALID，recovery_pending；保存证据，允许本地恢复或结案 |
| 已获得图像信息但下载/校验/落盘失败 | recovery_pending；仅本地恢复 |

Generations PNG data URL 已有基础 flare 单图证据。Chat 尺寸测试结论保留在 [供应商缺口验证](provider-validation.md)，产品采用无定制尺寸模式，不继续猜测尺寸字段。

### 13. SQLite schema v1（DDL）

以下 SQL 是设计附件，仅在测试内存库中校验，不创建正式运行库。SQLite 使用 STRICT 表并要求 JSON 函数可用，启动检测运行时能力；锁定 Python 时同时核对实际 SQLite 版本。时间存储为 UTC Unix 毫秒 INTEGER，在协议层转换 RFC 3339。每条连接在事务外启用 foreign_keys，设置 busy_timeout=5000；写连接设置 WAL 与 synchronous=FULL。依据：[SQLite 表约束](https://www.sqlite.org/lang_createtable.html)、[SQLite 外键](https://www.sqlite.org/foreignkeys.html)。

```sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
BEGIN IMMEDIATE;
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY CHECK(version > 0),
  applied_at INTEGER NOT NULL,
  checksum TEXT NOT NULL
) STRICT;
CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY NOT NULL,
  created_at INTEGER NOT NULL
) STRICT;
CREATE TABLE prompt_templates (
  code TEXT PRIMARY KEY NOT NULL COLLATE BINARY
    CHECK(length(code) BETWEEN 1 AND 64 AND code NOT GLOB '*[^A-Za-z0-9_-]*'),
  version INTEGER NOT NULL CHECK(version >= 1),
  content TEXT NOT NULL CHECK(length(CAST(content AS BLOB)) BETWEEN 1 AND 32768),
  variables_json TEXT NOT NULL CHECK(json_valid(variables_json) AND json_type(variables_json)='array'),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL CHECK(updated_at >= created_at)
) STRICT;
CREATE TABLE tasks (
  task_id TEXT PRIMARY KEY NOT NULL,
  batch_id TEXT REFERENCES batches(batch_id) ON DELETE RESTRICT,
  idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 1 AND 128),
  channel TEXT NOT NULL CHECK(channel IN ('images','flux','chat')),
  family TEXT NOT NULL CHECK(family IN ('flare','sunburst')),
  width INTEGER CHECK(width BETWEEN 1 AND 4096),
  height INTEGER CHECK(height BETWEEN 1 AND 4096),
  resolved_model TEXT NOT NULL,
  input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
  resolved_digest TEXT NOT NULL CHECK(length(resolved_digest)=64),
  snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json) AND json_type(snapshot_json)='object'),
  status TEXT NOT NULL CHECK(status IN ('queued','submitting','retry_wait','materializing',
    'recovery_pending','unknown','succeeded','failed','expired','cancelled','closed')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deadline_at INTEGER NOT NULL CHECK(deadline_at=created_at+600000),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
  next_attempt_at INTEGER,
  response_ref TEXT,
  error_category TEXT,
  error_message TEXT,
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
  CHECK((channel='chat' AND width IS NULL AND height IS NULL AND
    resolved_model IN ('gpt-image-2.6-' || family, 'gpt-image-2.6-' || family || '-2k', 'gpt-image-2.6-' || family || '-4k')) OR
    (channel IN ('images','flux') AND width IS NOT NULL AND height IS NOT NULL AND
    resolved_model = 'gpt-image-2.6-' || family ||
    CASE WHEN max(width,height)<=1024 THEN ''
         WHEN max(width,height)<=2048 THEN '-2k' ELSE '-4k' END)),
  CHECK(status <> 'retry_wait' OR next_attempt_at IS NOT NULL)
) STRICT;
CREATE TABLE batch_items (
  batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE RESTRICT,
  input_index INTEGER NOT NULL CHECK(input_index BETWEEN 0 AND 19),
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  reused INTEGER NOT NULL CHECK(reused IN (0,1)),
  PRIMARY KEY(batch_id,input_index)
) STRICT;
CREATE TABLE attempts (
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  submission_certainty TEXT NOT NULL CHECK(submission_certainty IN
    ('prepared','not_sent','unknown','response_received','rejected')),
  http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
  error_category TEXT,
  error_message TEXT,
  response_ref TEXT,
  PRIMARY KEY(task_id,attempt_no),
  CHECK(finished_at IS NULL OR finished_at>=started_at)
) STRICT;
CREATE TABLE reference_assets (
  asset_id TEXT PRIMARY KEY NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  input_index INTEGER NOT NULL CHECK(input_index BETWEEN 0 AND 3),
  local_path TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind='local_file'),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes>0),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  UNIQUE(task_id,input_index)
) STRICT;
CREATE TABLE image_artifacts (
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  image_index INTEGER NOT NULL CHECK(image_index BETWEEN 0 AND 3),
  local_path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes>0),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  revised_prompt TEXT,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(task_id,image_index)
) STRICT;
CREATE TABLE closure_records (
  task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  previous_status TEXT NOT NULL CHECK(previous_status IN ('unknown','recovery_pending')),
  reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1024),
  closed_at INTEGER NOT NULL
) STRICT;
CREATE TABLE task_events (
  event_id INTEGER PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX tasks_history ON tasks(created_at DESC,task_id DESC);
CREATE INDEX tasks_status_history ON tasks(status,created_at DESC,task_id DESC);
CREATE INDEX tasks_model_history ON tasks(resolved_model,created_at DESC,task_id DESC);
CREATE INDEX tasks_ready ON tasks(status,next_attempt_at,created_at,task_id);
CREATE INDEX batch_items_task ON batch_items(task_id);
CREATE INDEX task_events_task ON task_events(task_id,event_id);
PRAGMA user_version = 1;
COMMIT;
```

迁移执行器在同一建库事务内写 schema_migrations(version=1, applied_at, checksum)，checksum 来自发布迁移内容；上方结构 SQL 不硬编码时间或伪造校验和。已有库只能运行明确版本迁移，不用 IF NOT EXISTS 掩盖结构不匹配。主库没有任何 API key 列；snapshot_json 的允许字段由应用白名单限制，禁止把 RuntimeConfig 整体序列化进去。

#### 事务、容量及一致性

1. 入队：准备参考图不可变快照后，BEGIN IMMEDIATE；重查幂等键及摘要，计算新增唯一项，统计 queued/submitting/retry_wait/materializing/recovery_pending/unknown 总数；超 20 全部回滚，否则同时写 tasks、reference_assets、batches/batch_items 和初始事件，再提交。失败后的暂存文件可清理，不能删除已引用快照。容量是事务业务不变量，不使用无法覆盖聚合计数的单行 CHECK。
2. 调度：先取得进程级 6 槽信号量，短事务以 status/revision 条件领取任务；检查截止时间和 attempt_count，再插入 attempt、递增计数、更新状态及事件，一并提交后才能发 HTTP。无事务跨越网络。prepared 在崩溃后保守归 unknown，不能证明未发送就不能重发。
3. 响应：先将完整响应安全写入受控文件，再短事务登记 response_ref、attempt 完结与 materializing；文件写入后事务前崩溃通过 task/attempt 标识和校验恢复，不能仅凭存在任意文件判断响应有效。
4. 图片：验证完整输出集合后发布文件，在一个事务中插入结果集合并标 succeeded；部分下载不得提前成功。available 由文件存在性和完整性计算，不在表内存一个会过期的布尔值。实际文件不符时可报告 ARTIFACT_UNAVAILABLE，不再次生成。
5. 结案：任务级互斥下条件更新 unknown/recovery_pending→closed，插入唯一 closure_records 与事件，同一事务提交；不维护易漂移的独立容量计数器。closed 不重新打开。
6. 模板：比较 version 条件更新；完整展开内容、变量及 template version 存入任务 snapshot，历史任务不依赖可变的模板行。批量筛选通过 batch_items 连接 tasks，按任务去重，不能只筛 tasks.batch_id 而漏掉复用任务。

状态转移由 generation 的显式允许表和 revision 乐观校验控制；DDL 的状态枚举不代替转移规则。任务不可变字段、摘要和原始快照不得普通 UPDATE 修改。配置可调的字节上限及跨行总量由入队/解析层执行，DDL 固化必需结构、路由和不可突破的序号边界。所有 SQL 参数化，不拼接用户筛选内容。

#### 迁移与恢复验收

对建库 SQL 在隔离 SQLite 库执行：检查外键、幂等唯一约束、模型/尺寸匹配、attempt 1–3、图片与参考图序号、JSON 类型校验。实现阶段补充容量并发、条件更新、批量回滚、崩溃窗口和恢复演练。升级持有实例锁，先通过 SQLite 一致性备份生成可恢复副本，再事务迁移；失败回滚并拒绝启动，禁止自动清空原库。

## Non-functional Constraints

用户已批准以下全部非功能约束及优先级，包括总计最多 3 次尝试、仅安全错误自动重试、本地幂等、SQLite 状态恢复及其余补充项。批准不填补尚未提供的供应商契约，也不赋予未确定的配置值默认值。所有验收均为目标，尚未运行测试。

### NFR-01 错误分类与有界重试

- 将 `max_attempts=3` 解释为首次请求加最多两次重试，不是首次加三次。同一逻辑任务固定模型、通道和请求快照，不自动切换模型或通道。
- 由 `generation` 决定是否重试，`scheduler` 安排退避，`repository` 持久化尝试次数、错误类别及下次可执行时间。关闭 HTTP 传输层隐式重试，避免多层重试相乘；重启不重置次数。每次准备发送前先持久化 attempt 记录，崩溃窗口允许保守消耗一次预算，不能多发。
- 仅自动重试明确未发送的临时连接失败，以及供应商明确声明未受理、可重试的错误。鉴权、参数、模型不支持等确定性错误直接结束；证书和配置错误不反复重试。
- 读超时、部分写入后断连、请求中断及未明确语义的 5xx 可能已经产生生成工作，标记结果未知，不自动重提。429 也须结合供应商未受理语义确定重试资格；仅有状态码或 `Retry-After` 不能证明未生成。
- 采用指数退避加随机抖动：两次重试分别等待 1–2 秒、2–4 秒；有效 `Retry-After` 作为最早重试时间，若超过任务总期限则不再尝试。退避释放并发槽，但继续占用未完成任务容量；重试重新经过同一并发控制。
- 图片下载、文件落盘、SQLite 锁等待分别使用独立的有限恢复预算，不能触发重新生成。图片下载重试也须限制次数及总时长。
- 验收：故障注入时同一逻辑任务最多启动三次生成请求；重启后累计不超限；结果未知、鉴权失败不触发下一次生成；重试不会绕过 6 并发和 20 容量限制。

HTTPX 内建 transport 重试仅覆盖连接错误与连接超时，不能代替上述业务策略，见 [HTTPX transports](https://www.python-httpx.org/advanced/transports/)。

### NFR-02 本地幂等与原子接收

- 强制每个生成项提供稳定幂等键，在同一数据目录内唯一。摘要包含 Provider、模型、通道、展开后的提示词、影响结果的参数及参考图内容标识；键和摘要均持久化。参考图 URL 可变时须冻结内容或记录不可验证限制，不能把 URL 相同当成图片相同。
- 同键同摘要返回同一任务及当前结果；同键不同摘要明确冲突。失败或结果未知的任务使用原键仍返回已有状态，不能借重复提交重置重试预算；有意重新生成使用新键。
- 批量内重复键、数据库既有键先校验，容量按实际新增项计算。整批事务提交或拒绝，唯一约束与容量检查在同一写事务内完成。
- 幂等记录不因普通历史展示清理而自动删除；若未来允许删除，必须明确相应去重保证随之结束。
- 验收：并发提交相同键只创建一个任务；冲突不发生 HTTP 调用；重启后同键仍可识别；重复项不重复占容量。

### NFR-03 SQLite 持久化与恢复

- 数据库放在本地磁盘，使用 WAL、`synchronous=FULL`、有限 `busy_timeout`；保持短事务，网络和文件操作不在事务内等待。数据库访问通过专用执行线程/工作队列，避免阻塞 MCP 事件循环；具体连接管理实现后续确定。
- 任务接收必须在事务提交成功后才对调用方承认已接收；状态和尝试记录持久化失败时不开始新的远程请求。
- 启动先取得实例所有权，再检查数据库版本并恢复状态，最后开放接收及调度。数据库损坏、版本不兼容时明确报错，不静默新建空库替换历史。
- 恢复必须区分：未开始提交、请求结果未知、已有完整持久化响应但未完成落盘、已成功。仅恢复可证明安全的步骤；SQLite 只能恢复本地记录，不能找回未收到的远程图片。
- 结果未知任务继续占 20 个未完成任务名额，提供显式结案释放容量的路径并保留记录；结案不是宣称远程生成已取消。该业务取舍已批准，具体工具契约后续细化。
- 验收：在入队、发送前后、响应保存、文件移动、最终状态提交等位置强制终止进程，重启后无重复生成、无虚假成功、尝试次数不回退。

WAL 仍有单写者约束；`FULL` 提高提交持久性但增加同步写开销。备份应使用一致性备份方式，不能在数据库活动时只复制主文件而遗漏 WAL。依据：[SQLite WAL](https://www.sqlite.org/wal.html)、[SQLite PRAGMA](https://www.sqlite.org/pragma.html)。不承诺在硬件故障或磁盘损坏下绝对零丢失。

### NFR-04 至 NFR-11：已批准的补充约束

| 编号/要求 | 约束及验收方式 | 主要负责模块 |
| --- | --- | --- |
| NFR-04 超时与取消 | 分别配置连接、读、写、连接池等待和任务总期限；总期限包含排队、退避、生成及保存。超时不等于远程取消成功；客户端取消后不再新启重试。用慢响应及断开测试验证不会无限等待。任务总期限固定为 600 秒，口径见第 5 节；Host 的实际超时能力仍需验证。 | `generation`、`scheduler`、`providers/t8_star` |
| NFR-05 背压与公平性 | 严守 6 并发与 20 容量；重试、等待恢复及保存中任务纳入容量统计。就绪任务按稳定次序调度，退避任务不阻塞其他就绪任务。输入、参考图数量/字节、响应字节、解码像素、预览及下载并发均设可配置上限；默认值见已批准的第 8 节。 | `scheduler`、`generation`、`artifacts` |
| NFR-06 文件完整性与磁盘异常 | 临时文件与最终文件位于同一文件系统，验证图像类型、大小和完整性后再发布并登记成功；恢复识别孤立文件。磁盘满或无权限时返回可诊断错误，保留可恢复记录，不重发生成。注入磁盘错误及移动后崩溃验证。 | `artifacts`、`repository` |
| NFR-07 进程生命周期与实例隔离 | 同一数据目录单实例并验证锁所有权；关闭先停止接收与重试，再在有限宽限期内收尾，未完成请求记录为待恢复/未知。测试第二实例启动和异常退出，不能突破全局并发上限。 | `bootstrap`、`scheduler` |
| NFR-08 可诊断性与敏感数据处理 | 结构化日志记录任务 ID、attempt、通道、模型、耗时、状态及错误类别；日志到 stderr 或轮转文件，stdout 仅用于 MCP。默认不记录密钥、完整参考图/Base64、完整提示词及带签名 URL。错误包含是否可重试及后续动作；不引入独立监控平台。 | 全模块，`bootstrap` 统一配置 |
| NFR-09 Host 兼容与事件循环响应 | 验证 Codex 的 stdio 初始化、长调用、错误输出及图像展示；生成期间仍可处理本地查询。文件处理和 SQLite 阻塞操作不得长期占用事件循环。不将供应商耗时包装为本地性能保证。 | `mcp_api`、`bootstrap` |
| NFR-10 配置与可复现安装 | 固定 Python、提交依赖锁文件；启动校验模型、超时、输出目录及配置范围。TLS 默认验证，支持明确的代理/CA 配置；凭据从环境或受控本地配置读取，不入库、不写日志。错误配置在付费请求前失败。 | `bootstrap`、`providers/t8_star` |
| NFR-11 数据保留与可维护性 | 数据库记录 schema 版本；升级前一致性备份并提供兼容性检查。日志可轮转，历史/图片清理需明确保留策略，默认不自动删除用户生成图片；清理不触碰活动任务和恢复材料。用备份恢复演练验证，而非仅检查备份文件存在。 | `repository`、`artifacts` |

HTTPX 的四类 I/O 超时不等同于整个任务的墙钟期限，需由应用层另行管理，见 [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)。

### 优先级与验收边界

NFR-01 至 NFR-10 作为首版可靠运行要求；NFR-11 中 schema 版本及升级前备份首版具备，自动清理和定时备份可后续增加。当前不引入分布式锁、服务集群、高可用 SLA 或复杂监控系统。

验收优先使用受控 HTTP 替身、并发提交与进程崩溃注入，覆盖两种生成通道；真实供应商与 Codex 的集成验证另行记录。生成时长、内存峰值及本地查询延迟先测量，再制定数值基线，不在没有响应体样例和运行环境基线时承诺固定吞吐或延迟。

## Risks / Trade-offs

- [参考契约跨模型复用] → 采用 Generations 共享结构并容忍可选元数据差异；保留 Chat 和参考图编码缺口，不把 2.5 实测结果描述为 2.6 实测。
- [Host 对长同步调用的超时策略不同] → 在定稿前确定 MCP 调用生命周期，后续对 Codex 验收，不将后台执行作为未经确认的替代方案。
- [同步请求中断可能已产生远程费用] → 持久化请求开始状态，恢复时区分可重试本地步骤与远程结果未知，不自动重复生成。
- [多 Host 同时使用同一数据目录] → 采用已批准的单实例约束；第二实例明确拒绝启动。多 Host 共享同一活动队列不属于当前架构，若未来需要则另行设计。
- [数据库状态与图片文件不一致] → 为落盘中间状态设计恢复检查，不在文件尚未保存完整时标记任务成功。
- [模块拆分增加导航成本] → 方案 B 采用普通包与明确函数边界，仅在实际隔离需要处引入接口。

## Migration Plan

当前没有既有业务数据库，不涉及数据迁移。模块方案已批准；执行约束明确且契约补齐后，再规划初始数据库版本、数据目录初始化与升级策略。将来的结构升级应先备份数据库，检查版本兼容性；回退时保留图片与数据库，避免旧版本直接写入不兼容结构。

## 尚待补齐的设计信息

模块划分、同目录单实例、整批接收、安全重试、未知结果保留容量并显式结案，以及 NFR-01 至 NFR-11 的规则与优先级均已批准，不再请求重复确认。

1. Chat 已按用户决定采用不可定制尺寸模式，不再等待尺寸参数契约；Flux 目标模型兼容、扩展型号/多图及失败响应仍需验证。
2. 第 6–8 节及当前工具签名均已批准；字段映射见第 12 节，尚未实现。
3. SQLite DDL、事务与迁移规则已在第 13 节补齐；剩余为供应商适配验证门槛及后续实现验收。

上述缺口不影响已批准决策的效力，但完整设计和实现规划仍未就绪。
