# 成员手册验收记录

日期：2026-11-10。变更 `add-manual-writing`；本记录为发布准备前的阶段结果，未代表完整验收通过。发行状态以 GitHub Release 为准。

| 范围 | 结果和边界 |
| --- | --- |
| 文档静态检查 | README 与十节 MANUAL 已编写；相对文件链接存在，JSON 示例可解析，OpenSpec 严格验证通过。工作树包含未提交实现，基础提交 `0cbb48e4e2bb1a86819214c892f2d172decc4d1e` 不能代表完整工作树。 |
| Release | GitHub Release 列表及远程标签查询为空；没有经验证的安装版本或真实版本升级/回滚目标。包版本 0.1.0 不证明发布。 |
| 隔离安装 | 将当前工作树的项目元数据、锁和源码复制到 `.cache/manual-writing-install-check`，使用 uv 0.12.9 执行 `uv sync --locked --no-dev` 成功，Python 3.12.14，FastMCP 2.14.7，MCP SDK 1.30.0；`uv run --no-sync zhenzhen-gptimage --help` 成功。此为未提交工作树快照，不是 Release 安装。 |
| 隔离 stdio 协议 | 使用虚构测试密钥启动上述隔离快照；FastMCP 客户端发现 13 个工具、3 个资源、1 个 Prompt，`get_capabilities` 成功。未连接远程供应商，也不代表 Desktop Host 会话验收。 |
| 本地测试 | 配置、数据库和本地 MCP 测试共 37 项通过，含 v1 到 v2 数据迁移与备份。首次使用系统临时目录因访问权限失败，改用项目隔离临时目录后通过；测试替身不代表真实升级/回滚或真实供应商。 |
| 升级与回滚 | 真实 Release 之间的成员升级、回滚及真实用户数据保留尚未验证。数据兼容边界和安全备份步骤见 [数据库维护](database-maintenance.md)；不得以本地迁移测试代替真实版本验收。 |
| Desktop Host | 先前 Codex Desktop 图片内容块与其他 Host 的历史结果见 [Host 会话验证](host-session-validation.md)。本轮针对该手册的三个 Desktop 会话未完成；Claude Desktop 与 DeepSeek Harness Desktop 不能由 CLI 或替身代替。 |
| 真实供应商 | 本轮未提交生成请求，未产生新的图像生成费用；历史证据的范围以其原记录为准。 |

隔离测试仅使用虚构密钥及临时数据；真实 `.env`、用户环境变量、用户数据库和图片不在此次复制或清理范围内。

## v0.1.0 预发布后的隔离验收

2026-11-10，[v0.1.0 预发布](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tag/v0.1.0) 的标签经远程核对指向 `7d60bde04479c51deba4a82aa3084e7ea1a0fd72`。从 GitHub 克隆对应合入提交，在隔离目录以 Python 3.12.14、uv 0.12.9 执行锁定的非开发依赖安装及入口检查成功；另从 v0.1.0 标签克隆执行下列升级和回滚。仓库没有 CI 工作流，不能将本地检查说成 CI 通过。

- 旧版基线为仓库初始提交 `0cbb48e4e2bb1a86819214c892f2d172decc4d1e`，它不是此前的 Release。以虚构凭据启动其 stdio 服务，写入测试模板；SQLite 为 v1，完整性检查通过，并使用 SQLite backup API 创建一致性备份。
- 切换到 v0.1.0 并重新锁定安装后，通过真实 stdio MCP 调用读回模板；数据库迁移至 v2、完整性检查通过，自动生成 v1 备份。测试 `.env` 和代表用户文件的标记内容的哈希保持一致；没有触及真实配置、数据库或图片。
- 切回旧提交后，旧代码明确拒绝打开 v2。先用 SQLite backup API 保存 v2，再恢复迁移前 v1 备份；旧版 stdio 服务可读取原模板，v1 完整性检查通过，标记文件保留。测试未验证不同 Release 间的升级，也未证明迁移后新增的数据会出现在旧备份中。
- 本次不请求真实图像供应商；Host 会话和图片显示仍单独验收。隔离目录及测试凭据可在证据整理后清理，真实用户数据不属于清理范围。

## 带点的 Host 别名检查

2026-11-10：隔离 `CODEX_HOME` 中，Codex CLI 的 `mcp add` 和 `mcp get` 均接受 `zhenzhen-gptimage2.6`；TOML 表名必须加引号。本次不代表 Codex Desktop 已完成会话工具调用。DSH Desktop 0.2.1-rc.5 的内置 `@deepseek-ai/dsh-mcp-client` 将 `serverName` 限定为 `^[A-Za-z0-9_-]{1,32}$`，因此该版本拒绝带点的服务名；这是插件约束，不是 YAML 语法限制。Claude Desktop 的 JSON 文件能解析带点键，但没有在实际 Desktop 中验证其配置加载和工具调用，因此支持情况尚不确定。以上检查未修改实际 Host 配置或提交生图请求。

## 发布版 Desktop 会话检查进行中

2026-11-10：发布安装目录 `D:\MCP\zhenzhen-gptimage2.6-mcp` 指向 `7d60bde04479c51deba4a82aa3084e7ea1a0fd72`，三个 Host 使用别名 `zhenzhen-gptimage2-6`。检查配置时 Codex 和 DSH 启动、配置路径均指向发布安装目录，Claude Code 用户配置中也有该路径；Claude Desktop 原生配置文件中没有 MCP 条目，实际加载路径待会话确认。

- Codex Desktop 当前会话发现发布版服务，`get_capabilities` 成功，`list_tasks` 返回空列表；发布版数据目录没有现成的结果可用于图片展示。本次没有调用收费生图，不能用此前其他安装或数据目录的展示结果替代本次验收。
- DSH Desktop 0.2.1-rc.5 首次会话显示“已停止”；随后用户选择独立测试工作区，新的只读会话完成并报告没有发现 `zhenzhen-gptimage2-6` 或 `get_capabilities`，也没有调用工具。desktop overlay 包含该配置，但检查时未发现指向其数据目录的服务进程。该 Desktop 主进程创建于 12:01，配置文件最后修改于 12:25，进程早于最新配置，待完全退出并重启后复测；不能把文件存在当成连接成功。
- Claude Desktop Code 模式第一次会话使用了该客户端记住的无效旧工作目录，提示 `Folder not found`，因此没有发起 MCP 调用。用户随后选择独立测试工作区，Desktop Cowork 只读会话报告没有发现 `zhenzhen-gptimage2-6` 或 `get_capabilities`，也没有调用工具。当前条目在 Claude Code 用户配置中，Desktop 原生配置文件无对应条目；尚不能证明 Cowork 加载了该服务。

以上只读检查没有新提交 t8-star 图像生成；Host 对话模型使用客户端已有配置，可能产生模型服务费用。三个 Host 的发布版图片展示、原件定位及尚未完成的会话调用均保持未验收。

## DSH 插件启动故障排查

2026-11-10：DSH Desktop 0.2.1-rc.5 在配置更新后启动，插件界面显示对应 mcp-client 启动失败，未观察到该服务子进程。以相同版本的隔离 DSH headless profile、同一发布版及虚构密钥复现启动失败；MCP 子进程在初始化 httpx 0.28.1 客户端时报告 `httpx.InvalidURL: Invalid port: ':1]'`。DSH 的代理继承代码会将 `[::1]` 加入 `NO_PROXY`；独立构造代理环境时仅带方括号的 IPv6 条目触发相同错误，不含该条目的对照组通过。隔离 DSH 插件环境覆盖两个 `NO_PROXY` 大小写字段并去掉该条目后，未再出现相同的端口异常或插件启动失败日志；隔离模型因无测试密钥结束，不能据此认定真实 Desktop 已恢复。需要保留用户其他代理和绕过规则，并在实际 Desktop 应用修正后复测工具发现与调用。未提交图像生成或输出真实密钥。

同日文档检查：DSH overlay 的 YAML 可解析，两个字段位于目标服务的 `config.env`；用示例自定义域名合并并排除 `[::1]` 后，在代理环境下 httpx 客户端初始化通过。这是隔离配置和初始化检查，不证明真实 Desktop 连接。检查现有 Desktop 配置时，目标服务尚未设置这两个字段；等待用户合并配置并重启后复测。未输出密钥或提交生图请求。

同日真实 Desktop 复测：用户配置两个字段后，Desktop 0.2.1-rc.5 插件显示运行中；配置指向发布安装目录，其 HEAD 为 `7d60bde04479c51deba4a82aa3084e7ea1a0fd72`。真实会话显示新增 13 个工具，调用记录为 `mcp__zhenzhen-gptimage2-6__get_capabilities`，会话模型报告工具文本仅有“完成”，未得到结构化能力数据。发布版源码将成功文本设置为“完成”，能力数据位于 `structuredContent`；现象与 Host 未向模型传递该字段一致，但尚未证明丢失发生在哪一层。连接、发现和调用已观察，能力数据可用性、图像展示和原件定位尚未通过；不得据此完成 2.3。该次未提交图像生成，Host 对话模型请求可能产生费用。

## 2026-11-10 发布版真实生图续测

用户授权本轮最多三次 t8-star 生图，每个 Host 最多一次；实际提交两次，均为 `gpt-image-2.6-flare`、1024×1024，均只记录一次尝试。Host 对话模型可能另有费用。

- Codex Desktop 当前会话通过发布版 MCP 成功生成，工具返回图片内容块与原件路径；原件位于 `runtime-data/codex/images/ce52d5d4-b946-45ac-9329-bc39202377b9.0.png`。用户确认能够看到会话中通过本地原件链接展示的图片；该确认不单独证明 Desktop 直接渲染了工具内容块。
- DSH Desktop 0.2.1-rc.5 实际会话调用 `generate_image` 成功；SQLite 记录 `succeeded`、一次尝试，原件 `runtime-data/dsh/images/a03ce092-9dbc-4ddd-90ea-9c00cd1fdf75.0.png` 存在且 SHA-256 与数据库一致。会话报告“图片无法预览”，且模型只给出 DSH 的 JPEG 附件副本路径而非 MCP 保存的 PNG 原件路径；因此会话内展示与原件定位不通过。此前观察到的结构化返回缺失仍需排查，不能断言根因。
- Claude Desktop 4.23118.1.0 的 Code 会话使用独立工作区 `D:\MCP-host-tests\zhenzhen-gptimage2.6`；客户端提示目标 MCP 无法在 Cowork 和 Code 会话中启动，模型报告工具未出现在列表，未进行 Claude 生图。只读调查期间发现已有 Claude 进程启动了同一数据目录的 MCP 实例；目录锁冲突是待验证的可能原因，尚无启动日志证实。卡住的只读会话已停止。

任务 2.3 仍未完成；不得以工具调用成功、数据库落盘或其他 Host 的显示代替各 Desktop 的会话展示验收。

## Desktop 兼容根因排查

Claude Desktop 的目标 MCP 日志包含 `RuntimeError: data directory is already in use`；检查发现 Desktop 进程下已有使用 `runtime-data/claude` 的 MCP 进程，另用同一启动参数复现锁冲突。进一步核对发现 `C:\Users\Administrator\.claude.json` 与 `C:\Users\Administrator\AppData\Local\Claude-3p\claude_desktop_config.json` 两处目标服务均指向相同目录；前文检查了其他 Claude 配置路径，未覆盖 Claude-3p 的实际文件。该证据确认此次启动错误与目录锁争用有关；不能仅凭此确定各内部启动器加载配置的完整机制。

DSH 0.2.1-rc.5 本机内置 MCP 桥接代码保留 `structuredContent`，但模型可见文本从 `content` 提取；发布版文本仅返回“完成”，因此模型看不到原件路径。图像块经附件服务保存为 JPEG 副本，模型能描述内容；对现有原图只读调用 `get_image` 再次显示“图片无法预览”，未发起生图。会话回复中的预览渲染失败的具体原因仍待进一步验证，不能将附件存储或模型识图等同于 Desktop 可见展示。

工作区修复将 JSON 结果放入文本内容，同时保留结构化结果及图片块；针对性测试 14 项与全量测试 193 项通过。首次测试因系统临时目录权限失败，改用项目内临时目录后通过。该修复尚未发布，不能代表三个 Desktop 对修复版验收通过。

2026-11-10 后续复测：用户将 Claude Code 用户配置的数据目录改为 `runtime-data/claude-code` 并重启 Claude Desktop，Desktop 配置继续使用 `runtime-data/claude`。重启后的真实 Desktop Code 会话发现并调用发布版 `get_capabilities`，返回 `ok: true` 和完整能力信息；未生成图片。该结果验证连接与只读调用，不代表修复版及图片展示验收通过。

DSH 预览对照：会话记录显示模型此前生成的 Markdown 使用无扩展名的 DSH 附件对象路径；本机 DSH 文件服务按扩展名推断 MIME，未知时返回 `application/octet-stream` 并设置 `nosniff`。要求会话直接使用该任务已保存的 `.png` 原件路径后，Desktop 实际显示红色杯子图片。该对照证实有扩展名的原件路径可显示；修复版能否让模型自行获取和使用原件路径仍须实际验收，未产生新生图费用。
