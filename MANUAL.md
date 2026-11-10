# 成员使用手册

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

在每个 Host 的 MCP 配置中添加服务时保留已有条目与认证；使用 `command: uv` 和按空格拆分的参数数组，路径含空格时每个路径仍为一个数组项。Claude Desktop 与 DeepSeek Harness Desktop 改用分别独立的 `runtime-data/claude` 和 `runtime-data/dsh`。同一数据目录同时只能由一个 Server 实例使用；不同目录的任务、历史与模板互相隔离。按所用 Host 版本的界面和配置机制合并、启用配置，重启其 MCP 进程或客户端，再分别检查连接、工具发现、会话调用及图片显示；配置成功不等于会话验收成功。已有 CLI 和 DSH overlay 参考见[Host 配置说明](docs/host-setup.md)，该文中的 Claude Code 不等于 Claude Desktop，其旧路径和启动选项需按本节调整。

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

Claude Desktop 日志若出现 `data directory is already in use`，先查看 Desktop 和 Claude Code 各自的 MCP 配置与已运行的服务，确认是否有多个实例指向同一 `--data-dir`。保留需要的服务与其他配置：若确需并行运行，为每个实例配置不同的绝对数据目录，例如 `runtime-data/claude-desktop` 与 `runtime-data/claude-code`，并知悉历史与模板不会共享；若属于重复注册，可由使用者移除不需要的注册。修改后完全重启受影响的客户端并检查日志、工具发现与会话调用。不要删除 `server.lock`、数据库或图片来解决占用问题；本机日志证实冲突，但具体配置来源应按客户端实际情况核实。

核实目标 Release 的标签和 SHA 后，在干净工作树切换到该版本，执行 `uv sync --locked --no-dev`，重新执行本节及第 3、4 节检查。回滚前保存升级后的数据库和图片；schema v2 不能由旧版 v1 程序直接打开。回滚必须恢复并验证迁移前的 v1 备份，旧备份不会包含升级后的任务。不要将切换代码等同于回滚数据；无兼容备份时停止并保留原件。

## 6. 文件清单

源码 `src/`、依赖声明 `pyproject.toml`、锁文件 `uv.lock`、空密钥示例 `.env.example`、OpenSpec 和共享文档由仓库管理。`.env` 是本机私有配置；`.venv/` 为本机依赖；各 `runtime-data/` 保存 SQLite、图片、参考图和恢复材料。`.cache/` 可包含验收原件及脱敏账本，具体证据不应提交。运行数据和私有配置须单独备份，升级清理时不能当作普通构建缓存。参见[数据目录](docs/data-directory.md)。

## 7. 资源清单

实际可发现的工具如下，结果统一包含 `ok`、`data`、`warnings`、`error`；失败时检查 `error.code`、`message`、`retryable` 和 `next_action`。Host 可通过工具 Schema 查看完整参数和约束。

正在实施的 Desktop 兼容修复会在工具文本内容中提供与结构化结果一致的 JSON，便于仅读取文本的 Host 获取任务状态和 `local_path`；图片附件或预览副本不是原件。该修复尚未发布，成员请以安装版本和[验收记录](docs/manual-writing-validation.md)为准。

| 工具 | 用途与主要参数 |
| --- | --- |
| `get_capabilities` | 查询模型、通道、限制及已验证范围。 |
| `generate_image` / `generate_batch` | `request` / `requests`；批量最多 20 项。 |
| `get_task` / `list_tasks` | 按任务 ID 或幂等键查询；列表支持状态、批次、模型、时间及分页筛选。 |
| `get_image` | `task_id`、`image_index`、`include_preview`，获取路径和可用预览。 |
| `recover_task` | `task_id`，恢复同一任务，不新建生成。 |
| `accept_gif_size` | `task_id`、`sha256`、实际 `width` 和 `height`，接受待确认 GIF。 |
| `close_task` | `task_id`、`expected_status`、`reason`；仅处理允许结案的状态。 |
| `save_prompt_template` / `get_prompt_template` / `list_prompt_templates` / `render_prompt_template` | 保存、查询、分页浏览和用变量展开模板；更新使用 `expected_version`。 |

Resources：`gptimage://capabilities`、`gptimage://prompt-guide`、`gptimage://recovery-guide`；Prompt：`optimize_ecommerce_prompt`。是否在界面中显示取决于 Host。模板使用 `{{变量名}}`；详见[模板说明](docs/prompt-templates.md)，其中关于尚未接入的历史文字不代表当前工具注册状态。

## 8. 功能说明

可先让 Agent 依据资源和实际商品事实优化提示词，再提交单项或批量请求。每项需唯一 `idempotency_key`、`family`（`flare` 或 `sunburst`），并且 `prompt` 与 `template_code` 二选一。普通图像的 `images`、`flux` 通道需宽高；`chat` 不接受自定义宽高，尺寸由供应商决定。默认通道 `images`；模型按宽高和 family 路由，`explicit_model` 必须与路由一致。参考图使用 `references` 中的本地 `local_path`，最多 4 张；Flux 不支持参考图。模板可传 `template_variables`。

SVG/GIF 仅文生图：通过 `output_format` 指定，`size` 支持 `auto`、规定比例或像素尺寸，也可使用 `width` 和 `height`，两种尺寸形式不能同时使用。SVG 仅允许基础 Flare，默认绘制模型 `gpt-6-luna`；GIF 的 `frame_count` 为 2–16，`frame_duration_ms` 最少 20 且为 10 的倍数。像素尺寸与 GIF 拼图限制、供应商验证范围及实际尺寸不符处理详见 [SVG 和 GIF](docs/svg-gif.md)。GIF 的 JPEG 预览仅为首帧，保存的 GIF 原件保留动画；SVG 原件为矢量，Host 预览可能不可用。

默认同步；只有 `images` 通道基础 Flare GIF 支持显式 `execution_mode: "async"`。用 `get_task` 查询，取得远程任务 ID 后重启可继续恢复该 ID；无 ID 且提交结果未知时不可自动重发。尺寸不符时默认保留待确认原件，可核实哈希及尺寸后调用 `accept_gif_size`，或在提交前明确选择 `size_policy: "accept_actual"`。

## 9. 注意事项

队列最多 20 个未完成任务，最高 6 个并发；同一模型总计最多 3 次尝试，仅对明确安全的错误自动重试。重复幂等键须对应同一请求；结果不明、超时或取消时先查询任务，不能假设供应商取消或重复付费提交。停止接收和等待在途任务有 30 秒宽限期；之后不再启动请求，必要状态持久化和资源关闭可继续。请求可能收费，供应商及 Host 模型费用分别计算；不得在日志、示例或公开文档中放密钥。网络访问、参考图和结果下载涉及数据传输，应只使用有权处理的内容。

## 10. 常见问题

- **没有标签或 Release？** 等待经核实的发布；不要把工作树的包版本当标签。
- **入口找不到或锁不一致？** 确认 uv、Python 3.12.14 和实际目录，重新运行 `uv sync --locked --no-dev`，检查报错，不修改锁文件来掩盖问题。
- **明明设置了用户级密钥仍报错？** 检查更高优先级 `.env` 和进程变量是否已定义为空或非法；修正或删除对应字段，然后重启。切勿输出密钥。
- **Host 没有工具？** 分别检查配置格式、MCP 进程 stderr、`--config-dir`、独立数据目录及 Host 是否重新加载；配置存在不代表连接或调用成功。
- **图片尺寸与请求不同？** Chat 无法定制；GIF 请查看实际尺寸和待确认状态，不要重新生成。参考 [SVG 和 GIF](docs/svg-gif.md)。
- **调用超时或结果未知？** 使用原任务 ID / 幂等键查询，按允许操作恢复；必要时参阅[恢复说明](docs/recovery.md)，不要直接重复提交。
- **升级后旧版无法启动？** 检查数据库 schema 及备份，不要删除 v2 数据；按第 5 节恢复经验证的兼容备份。
