# 成员使用手册

> 本工作树包含尚未发布的共享后台实现，下文关于共享后台的说明适用于包含该变更的版本；v0.1.1 不具备此能力。发布版及 Desktop 验收状态以 [验收记录](docs/manual-writing-validation.md) 为准。

## 1. 环境准备

本手册面向使用 MCP 的成员。Windows 默认安装目录为 `D:\MCP\zhenzhen-gptimage2.6-mcp`；其他位置可用，但以下命令和 Host 配置的路径必须一致。需要 Git、uv、Python 3.12.14、可访问 GitHub 和 t8-star 的网络、磁盘空间，以及可登录的目标 Desktop Host。Python 与依赖由项目锁文件约束；uv 需能运行 `uv sync --locked`。请根据实际 Host 安装及模型服务条件配置，Host 对话模型的账号或 codeproxy 与本 MCP 的 t8-star 凭据互不相同。

仓库：[zhenzhen-gptimage2.6-mcp](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp)；发行包名 `zhenzhen-gptimage2-6-mcp`，Python 模块 `zhenzhen_gptimage`，可执行入口 `zhenzhen-gptimage`，MCP 服务名 `zhenzhen-gptimage-2.6`，传输方式为 stdio。[v0.1.0 预发布](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tag/v0.1.0) 对应提交 `7d60bde04479c51deba4a82aa3084e7ea1a0fd72`；安装时仍需自行核对标签与 SHA。隔离锁定安装解析出 FastMCP 2.14.7 和 MCP Python SDK 1.30.0；具体版本以目标 Release 锁文件为准，协议协商版本与包版本分别确定。

## 2. 项目初始化

在 [Releases](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases) 核对标签及其完整提交 SHA，替换下方占位符；若尚无经验证的发行版本，应等待验收结果。默认目录已有内容时先检查，不要覆盖。项目不要求 ZIP 分发。

```powershell
git clone --branch '<已验证标签>' --single-branch https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp.git D:/MCP/zhenzhen-gptimage2.6-mcp
Set-Location D:/MCP/zhenzhen-gptimage2.6-mcp
git rev-parse HEAD
uv sync --locked --no-dev
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

核对输出 SHA 与 Release 声明一致。在 `.env` 中为 `ZHENZHEN_GPTIMAGEGEN_API_KEY` 填入自己的 t8-star 密钥，限制文件访问权限，不提交、截图或粘贴密钥。已有 `.env` 保留；若使用环境变量，需从 `.env` 删除此字段，不能留空。读取优先级及错误规则见[配置说明](docs/configuration.md)。密钥改变后重启 MCP 进程。

## 3. 可用性测试

安装后在 PowerShell 中检查入口：

```powershell
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync zhenzhen-gptimage --help
```

预期显示 `--config-dir`、`--env-file` 和 `--data-dir`，退出码为 0。此检查不连接供应商，也不验证 MCP 协议或 Desktop 会话。连接 Host 后用 `get_capabilities` 检查工具可用性；其成功不证明供应商生图可用。服务正常启动后等待 stdio 请求，无交互式提示；不要向其标准输出写入诊断内容。生成期限为 600 秒，Host 超时应略长于该期限。

## 4. 客户端配置

安装依赖后，Host 使用以下等价的 stdio 命令和独立数据目录；不要在每次启动时安装依赖。指定 `--config-dir` 是必要的：未指定时当前实现使用 Host 进程的工作目录，并不自动定位安装目录。

```text
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync zhenzhen-gptimage --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex
```

在每个 Host 的 MCP 配置中添加服务时保留已有条目与认证；使用 `command: uv` 和按空格拆分的参数数组，路径含空格时每个路径仍为一个数组项。支持共享后台的版本允许多个 stdio 接入进程使用相同 `--data-dir`，共享任务、图片、幂等记录和模板，并由一个后台统一执行队列上限；须同时使用兼容的版本、配置目录、凭据和限制。不同数据目录仍各自隔离。旧版 v0.1.1 的同一数据目录只能有一个 Server 实例；不得与新版后台同时占用同一目录。按所用 Host 版本的界面和配置机制合并、启用配置，重启其 MCP 进程或客户端，再分别检查连接、工具发现、会话调用及图片显示；配置成功不等于会话验收成功。具体示例见[Host 配置说明](docs/host-setup.md)。

以下为通用的 JSON 服务条目示例，具体外层结构和可用性须由对应 Desktop 版本确认；不要用它覆盖整个已有配置：

```json
{
  "command": "uv",
  "args": ["--directory", "D:/MCP/zhenzhen-gptimage2.6-mcp", "run", "--no-sync", "zhenzhen-gptimage", "--config-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp", "--data-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex"]
}
```

验收记录见[本次手册验收](docs/manual-writing-validation.md)和[Host 会话验证](docs/host-session-validation.md)。当前 Codex Desktop 曾观察到本项目图片内容块；Claude Desktop 和 DeepSeek Harness Desktop 对本项目的完整实际会话与图片展示尚未完成验证。DSH Desktop 已发现并调用 `get_capabilities`，但会话仅收到“完成”，能力数据未见返回；原因尚待核实。各 Host 的 UI、版本及模型渠道以实际验收为准，不能用其他客户端代替。

对于受影响的 DeepSeek Harness Desktop 0.2.1-rc.5 与 httpx 0.28.1 组合，在此 MCP 服务的 `config` 下合并以下字段：

```yaml
env:
  NO_PROXY: "localhost,127.0.0.1,::1"
  no_proxy: "localhost,127.0.0.1,::1"
```

若已有其他绕过地址，将其保留并一致地追加到两个字段，移除 `[::1]`；不要覆盖其他服务、代理地址或凭据。这只影响该 MCP 子进程。重启后检查插件状态与 `get_capabilities`；当前隔离验证不能代替真实 Desktop 复测，其他版本以实际验证为准。完整配置层级见 [DSH overlay 示例](docs/host-setup.md#deepseek-harness)。

## 5. 启动排障、升级与回滚

先检查绝对路径、uv 可执行文件、锁定安装、密钥来源和各 Host 的 stderr；stdio stdout 必须留给协议。配置错误、空密钥和数据目录锁冲突应修正后重启，不能盲目删除数据库。升级前记录旧标签与完整 SHA，检查 `git status`，停止所有使用该数据目录的 Server，保护 `.env`、权限、数据库、图片及私有配置。按[数据库维护](docs/database-maintenance.md)用 SQLite backup API 创建一致性备份，并验证完整性。

共享后台版本可在 PowerShell 中检查或有序停止指定目录的后台；将路径替换为该 Host 的实际配置：

```powershell
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control status --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control stop --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex
```

`status` 的 `ready` 表示后台握手成功；`not_available` 表示没有可连接后台，`incompatible` 表示正在运行的后台与当前配置或版本不兼容。`stop` 表示已请求有序停止，等待在途任务的宽限期最多 30 秒，状态持久化与资源关闭可能继续。停止所有接入客户端后再检查数据目录已释放，才能升级或回滚。若后台不可用，检查配置、私有运行目录权限和旧版进程占用；不要删除 `server.lock`、数据库或图片。旧版 v0.1.1 不支持此管理命令；其目录锁冲突需停止占用进程，或使用不同数据目录并接受历史隔离。

后台发现信息位于数据目录 `.shared-backend/`，只允许当前用户访问：Windows 需要受限 ACL，POSIX 系统需要目录模式 `0700` 和文件模式 `0600`。Windows 后台通过本机 WMI 隐藏启动，WMI 不可用或权限不足时会报启动错误；需要凭据及代理的环境变量经本机内存传递，密钥不会写入启动参数。权限不符合要求时服务会拒绝使用，不要放宽权限。修改密钥、配置目录或版本后，如提示不兼容，先停止旧接入与后台，再使用新配置启动；不要复制或公开发现文件中的令牌。

核实目标 Release 的标签和 SHA 后，在干净工作树切换到该版本，执行 `uv sync --locked --no-dev`，重新执行本节及第 3、4 节检查。回滚前保存升级后的数据库和图片；schema v2 不能由旧版 v1 程序直接打开。回滚必须恢复并验证迁移前的 v1 备份，旧备份不会包含升级后的任务。不要将切换代码等同于回滚数据；无兼容备份时停止并保留原件。

## 6. 文件清单

源码 `src/`、依赖声明 `pyproject.toml`、锁文件 `uv.lock`、空密钥示例 `.env.example`、OpenSpec 和共享文档由仓库管理。`.env` 是本机私有配置；`.venv/` 为本机依赖；各 `runtime-data/` 保存 SQLite、图片、参考图和恢复材料。`.cache/` 可包含验收原件及脱敏账本，具体证据不应提交。运行数据和私有配置须单独备份，升级清理时不能当作普通构建缓存。参见[数据目录](docs/data-directory.md)。

## 7. 资源清单

实际可发现的工具如下，结果统一包含 `ok`、`data`、`warnings`、`error`；失败时检查 `error.code`、`message`、`retryable` 和 `next_action`。Host 可通过工具 Schema 查看完整参数和约束。

从 v0.1.1 起，工具文本内容提供与结构化结果一致的 JSON，便于仅读取文本的 Host 获取任务状态和 `local_path`；图片附件或预览副本不是原件。v0.1.0 不包含此修复；版本发布与 Host 验证状态见[验收记录](docs/manual-writing-validation.md)。

| 工具 | 用途与主要参数 |
| --- | --- |
| `get_capabilities` | 查询模型、通道、限制及已验证范围。 |
| `generate_image` / `generate_batch` | `request` / `requests`；批量最多 20 项。 |
| `get_task` / `list_tasks` | 按任务 ID 或幂等键查询；列表支持状态、批次、模型、时间及分页筛选。 |
| `get_image` | `task_id`、`image_index`、`include_preview`，获取路径和可用预览。 |
| `export_image` | 开发版本：`task_id`、`image_index`、`destination`，将原件复制到已授权本机导出目录；尚未完成发布及 Desktop 验收。 |
| `preview_cleanup` / `authorize_cleanup` / `execute_cleanup` | 开发版本：预览、请求用户确认、执行具体计划；尚未发布及完成 Desktop 验收。 |
| `get_retention_policy` / `set_retention_policy` | 开发版本：查询或修改 90 天自动清理策略；启用须用户确认。 |
| `recover_task` | `task_id`，恢复同一任务，不新建生成。 |
| `accept_gif_size` | `task_id`、`sha256`、实际 `width` 和 `height`，接受待确认 GIF。 |
| `close_task` | `task_id`、`expected_status`、`reason`；仅处理允许结案的状态。 |
| `save_prompt_template` / `get_prompt_template` / `list_prompt_templates` / `render_prompt_template` | 保存、查询、分页浏览和用变量展开模板；更新使用 `expected_version`。 |

Resources：`gptimage://capabilities`、`gptimage://prompt-guide`、`gptimage://recovery-guide`；Prompt：`optimize_ecommerce_prompt`。是否在界面中显示取决于 Host。模板使用 `{{变量名}}`；详见[模板说明](docs/prompt-templates.md)，其中关于尚未接入的历史文字不代表当前工具注册状态。

## 8. 功能说明

可先让 Agent 依据资源和实际商品事实优化提示词，再提交单项或批量请求。每项需唯一 `idempotency_key`、`family`（`flare` 或 `sunburst`），并且 `prompt` 与 `template_code` 二选一。普通图像的 `images`、`flux` 通道需宽高；`chat` 不接受自定义宽高，尺寸由供应商决定。默认通道 `images`；模型按宽高和 family 路由，`explicit_model` 必须与路由一致。参考图使用 `references` 中的本地 `local_path`，最多 4 张；Flux 不支持参考图。模板可传 `template_variables`。

开发版本可在用户配置 `ZHENZHEN_GPTIMAGEGEN_EXPORT_ROOT` 后调用 `export_image`：`destination` 必须是该目录下的服务器本机绝对文件路径，扩展名与原件一致；已有文件不会覆盖。返回目标路径、类型、字节数及 SHA-256。GIF 和 SVG 按原字节复制。Cowork 内的沙箱路径不一定是 Windows 本机路径，若无法确定对应关系，应由用户提供本机工作区路径；不可自行猜测。此功能尚未发布，Cowork 实际归档及打开验收待完成。配置步骤见[本地配置](docs/configuration.md)。

开发版本支持手动清理：先调用 `preview_cleanup`，提供带时区的 `before` 日期时间，或提供 `keep_latest` 保留最新数量，两者选择一个。预览包含计划 ID、到期时间、候选文件及大小、摘要和跳过原因；确认前不会删除。用户逐项审查后，可由支持 MCP 交互确认的 Host 调用 `authorize_cleanup` 并在确认界面批准，再调用 `execute_cleanup`。若 Host 不支持交互确认，用户可在本机终端执行以下命令，查看完整清单后按提示输入 `APPROVE` 和计划 ID，随后让 Agent 调用 `execute_cleanup`：

```powershell
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control approve-cleanup --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex --plan-id <计划ID>
```

实际运行时将 `<计划ID>` 替换为预览返回的 ID。计划有效期为 10 分钟，后台重启后失效；每个计划只能执行一次，变化的文件会跳过。候选可能包含已完成任务的托管原件，以及在该任务所有原件均符合清理条件时，可核验且不再供其他任务使用的供应商响应、响应清单和参考图快照；预览会列出每个具体文件。任务历史、未完成任务和工作区导出副本保留；无法核验或归属不明的文件保留。中断后如结果不明，历史返回 `cleanup_uncertain`，需检查清理账本及备份，不能自动重试删除。

每个计划最多列出 1000 个候选；若 `has_more` 为 `true`，执行后可使用相同筛选条件重新预览下一批并逐批确认。`skipped_truncated` 为 `true` 表示跳过原因未全部列出，不影响计划中的候选范围。

开发版本的 90 天自动清理默认关闭。先用 `get_retention_policy` 查询；仅在明确接受永久删除超过 90 天的符合条件原件及其可安全清理的供应商响应、响应清单和参考图快照后，调用 `set_retention_policy(enabled=true)` 并在 Host 确认界面批准。Host 不支持确认时，用户可在本机终端运行以下命令，阅读提示并输入 `ENABLE 90 DAYS`；关闭时调用 `set_retention_policy(enabled=false)`。服务只在后台运行时检查，关闭会等待当前正在处理的删除并阻止启动下一次删除；非运行期间不执行清理。该功能尚未发布及完成 Desktop 验收。

```powershell
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control enable-auto-cleanup --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/codex
```

SVG/GIF 仅文生图：通过 `output_format` 指定，`size` 支持 `auto`、规定比例或像素尺寸，也可使用 `width` 和 `height`，两种尺寸形式不能同时使用。SVG 仅允许基础 Flare，默认绘制模型 `gpt-6-luna`；GIF 的 `frame_count` 为 2–16，`frame_duration_ms` 最少 20 且为 10 的倍数。像素尺寸与 GIF 拼图限制、供应商验证范围及实际尺寸不符处理详见 [SVG 和 GIF](docs/svg-gif.md)。GIF 的 JPEG 预览仅为首帧，保存的 GIF 原件保留动画；SVG 原件为矢量，Host 预览可能不可用。

默认同步；只有 `images` 通道基础 Flare GIF 支持显式 `execution_mode: "async"`。用 `get_task` 查询，取得远程任务 ID 后重启可继续恢复该 ID；无 ID 且提交结果未知时不可自动重发。尺寸不符时默认保留待确认原件，可核实哈希及尺寸后调用 `accept_gif_size`，或在提交前明确选择 `size_policy: "accept_actual"`。

## 9. 注意事项

队列最多 20 个未完成任务，最高 6 个并发；同一模型总计最多 3 次尝试，仅对明确安全的错误自动重试。重复幂等键须对应同一请求；结果不明、超时或取消时先查询任务，不能假设供应商取消或重复付费提交。停止接收和等待在途任务有 30 秒宽限期；之后不再启动请求，必要状态持久化和资源关闭可继续。请求可能收费，供应商及 Host 模型费用分别计算；不得在日志、示例或公开文档中放密钥。网络访问、参考图和结果下载涉及数据传输，应只使用有权处理的内容。

## 10. 常见问题

- **没有标签或 Release？** 等待经核实的发布；不要把工作树的包版本当标签。
- **入口找不到或锁不一致？** 确认 uv、Python 3.12.14 和实际目录，重新运行 `uv sync --locked --no-dev`，检查报错，不修改锁文件来掩盖问题。
- **明明设置了用户级密钥仍报错？** 检查更高优先级 `.env` 和进程变量是否已定义为空或非法；修正或删除对应字段，然后重启。切勿输出密钥。
- **Host 没有工具？** 分别检查配置格式、MCP 进程 stderr、`--config-dir`、数据目录权限及 Host 是否重新加载；共享后台版本可先使用第 5 节的 `status`。配置存在不代表连接或调用成功。
- **图片尺寸与请求不同？** Chat 无法定制；GIF 请查看实际尺寸和待确认状态，不要重新生成。参考 [SVG 和 GIF](docs/svg-gif.md)。
- **调用超时或结果未知？** 使用原任务 ID / 幂等键查询，按允许操作恢复；必要时参阅[恢复说明](docs/recovery.md)，不要直接重复提交。
- **升级后旧版无法启动？** 检查数据库 schema 及备份，不要删除 v2 数据；按第 5 节恢复经验证的兼容备份。
