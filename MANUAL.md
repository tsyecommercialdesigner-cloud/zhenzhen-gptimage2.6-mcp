# zhenzhen-gptimage2.6-mcp 成员使用手册

本手册适用于 [v0.1.6 正式版](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tag/v0.1.6)；安装前应核对该 Release 的标签与完整提交。面向 Windows 成员；示例使用 PowerShell 和默认安装目录，使用其他目录时需同时修改安装、配置及命令中的路径。

## 1. 环境准备

本服务运行在本机，通过 stdio 连接 Agent；不需要另行部署 HTTP 服务。准备 Windows、Git、uv（已验证 0.12.9）、Python 3.12.14、可访问 GitHub 和 PyPI 的网络，以及 t8-star 图像服务的有效密钥。uv 可按项目 `.python-version` 下载精确 Python。Claude / Codex / DSH 的登录或对话模型渠道与本服务的图像供应商密钥分别配置。

| 项目 | 值 |
| --- | --- |
| 项目目录 | `D:/MCP/zhenzhen-gptimage2.6-mcp` |
| 仓库 | [zhenzhen-gptimage2.6-mcp](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp) |
| 包名 / Python 模块 | `zhenzhen-gptimage2-6-mcp` / `zhenzhen_gptimage` |
| 命令 / Host 别名 | `zhenzhen-gptimage` / `zhenzhen-gptimage2-6` |
| 服务名称 / 传输 | `zhenzhen-gptimage-2.6` / 本地 stdio |
| 供应商 / 密钥变量 | `https://ai.t8star.org` / `ZHENZHEN_GPTIMAGEGEN_API_KEY` |
| 运行依赖 | FastMCP 2.14.7、MCP SDK 1.30.0；以锁文件为准 |

先在 PowerShell 检查工具；若 `uv` 无法发现，请安装 uv 并确保 Desktop 进程的 PATH 可以找到它：

```powershell
Get-Command git, uv -ErrorAction Stop | Select-Object Name, Source
uv --version
git --version
```

## 2. 项目初始化

### 首次安装

以下可从任意 PowerShell 目录执行；若目标目录已存在，命令会停止，请使用第 5 节升级步骤。不会覆盖已有文件或配置。

```powershell
$ErrorActionPreference = 'Stop'
$ProjectDir = 'D:/MCP/zhenzhen-gptimage2.6-mcp'
$Release = Invoke-RestMethod 'https://api.github.com/repos/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tags/v0.1.6'
if ($Release.draft -or $Release.prerelease -or $Release.tag_name -cne 'v0.1.6' -or $Release.target_commitish -notmatch '^[0-9a-f]{40}$') { throw '正式 Release 或完整提交不可用。' }
$ExpectedCommit = $Release.target_commitish
if (Test-Path -LiteralPath $ProjectDir) { throw '安装目录已存在，请使用升级步骤。' }
New-Item -ItemType Directory -Path (Split-Path -Parent $ProjectDir) -Force | Out-Null
git clone --branch v0.1.6 --single-branch 'https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp.git' $ProjectDir
if ($LASTEXITCODE -ne 0) { throw '克隆失败。' }
$ActualCommit = git -C $ProjectDir rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $ActualCommit -cne $ExpectedCommit) { throw '标签提交不匹配，停止安装。' }
uv --directory $ProjectDir sync --locked --no-dev
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败。' }
```

独立 `.venv` 由 uv 创建；日常启动使用 `--no-sync`。项目通过 GitHub Releases 发布，不需要成员下载 ZIP。

### 设置密钥

下面仅在 `.env` 不存在时复制空模板，然后打开编辑器；不会读取或打印密钥。

```powershell
$ProjectDir = 'D:/MCP/zhenzhen-gptimage2.6-mcp'
$EnvPath = Join-Path $ProjectDir '.env'
if (-not (Test-Path -LiteralPath $EnvPath)) {
  [IO.File]::Copy((Join-Path $ProjectDir '.env.example'), $EnvPath, $false)
}
notepad.exe $EnvPath
```

在文件中填写 `ZHENZHEN_GPTIMAGEGEN_API_KEY=你的密钥`，以 UTF-8 保存；请勿把真实密钥放进配置示例、聊天、日志或 Git。`.env` 是私有文件，确保只有运行服务的用户和必要管理员可读写。已有 `.env` 保留并仅合并字段。

密钥按项目 `.env`、进程环境、Windows 用户级环境的顺序读取；只有文件或字段缺失才回退。若要使用用户级环境变量，删除 `.env` 中的密钥字段，不能保留空值。已定义为空、重复或非法时启动报错，不会回退。配置读取规则见[本地配置](docs/configuration.md)。

## 3. 可用性测试

在 PowerShell 检查已安装入口：

```powershell
uv --directory 'D:/MCP/zhenzhen-gptimage2.6-mcp' run --no-sync zhenzhen-gptimage --help
if ($LASTEXITCODE -ne 0) { throw '入口检查失败。' }
```

输出应包含 `--config-dir`、`--env-file`、`--data-dir`。此命令不生图，也不验证 Host 或供应商。完成第 4 节后，在各客户端的新会话中请 Agent 调用 `get_capabilities`；这是本地能力查询，不提交供应商生图。然后可调用 `list_tasks`、`get_task` 或 `get_image` 查询已有任务。图像生成可能收费，只有用户需要并授权时才提交。

v0.1.5 发布合并提交的 [Windows CI](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/actions/runs/42785369102) 为 285 通过、1 跳过。三个 Desktop 曾分别使用 v0.1.5 和已有 PNG 完成导出会话验收；这不代表 v0.1.6 已重新完成三个 Desktop 会话或所有供应商模型的收费验证。证据见[验收记录](docs/artifact-retention-validation.md)。

## 4. 客户端配置

以下三种配置使用相同的 `runtime-data/shared`，因此共享任务、幂等记录、模板和队列；配置目录、密钥、限制和版本也须一致。如果需要不同历史，可分别改成不同数据目录。示例目录用于新安装；已有用户应保留实际数据目录，避免误以为旧历史丢失。所有路径均为 **运行 MCP 的本机路径**，不是 Agent 的虚拟沙箱路径。

先备份待编辑的 Host 配置，只合并本服务，保留其他服务和登录信息。示例中的 `uv` 需能从 Host 的 PATH 找到；如果客户端找不到命令，使用 `Get-Command uv | Select-Object -ExpandProperty Source` 查询绝对路径并替换 `command`。修改后完全重启对应 Desktop，在会话中检查工具发现和 `get_capabilities`。

### Codex Desktop

在用户配置 `C:/Users/<用户名>/.codex/config.toml`（也可使用项目 `.codex/config.toml`）合并下面的表；已有同名表则修改该表，不要重复添加。

```toml
[mcp_servers.zhenzhen-gptimage2-6]
command = "uv"
args = [
  "--directory", "D:/MCP/zhenzhen-gptimage2.6-mcp",
  "run", "--no-sync", "zhenzhen-gptimage",
  "--config-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp",
  "--data-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared"
]
startup_timeout_sec = 30
tool_timeout_sec = 630
```

保存后重启 Codex Desktop；CLI 可查询注册状态：

```powershell
codex mcp get zhenzhen-gptimage2-6
```

配置存在不等于会话工具可用。此前本机 v0.1.5 的 Codex 会话已成功调用 `export_image`，并核对副本摘要；如 Host 尚未刷新工具列表，重启后再查。

### Claude Desktop Cowork

本机已验证的配置位置是 `%LOCALAPPDATA%/Claude-3p/claude_desktop_config.json`。在已有 JSON 的 `mcpServers` 对象中合并以下**单个服务条目**，保留其他键；如果该对象当前为空，下方完整 JSON 可直接作为文件内容。实际客户端版本的配置位置以其设置界面为准。不要用此完整示例覆盖已有其他服务。

```json
{
  "mcpServers": {
    "zhenzhen-gptimage2-6": {
      "command": "uv",
      "args": [
        "--directory", "D:/MCP/zhenzhen-gptimage2.6-mcp",
        "run", "--no-sync", "zhenzhen-gptimage",
        "--config-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp",
        "--data-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared"
      ]
    }
  }
}
```

用下面命令打开当前用户的文件；文件不存在时先在 Claude Desktop 中初始化设置，不要覆盖其他配置：

```powershell
$ClaudeConfig = Join-Path $env:LOCALAPPDATA 'Claude-3p/claude_desktop_config.json'
if (-not (Test-Path -LiteralPath $ClaudeConfig -PathType Leaf)) { throw "找不到配置文件：$ClaudeConfig" }
notepad.exe $ClaudeConfig
```

保存后完全退出并重启 Claude Desktop，进入 Cowork，在独立工作区中检查服务和工具。v0.1.5 本机 Cowork 已调用导出并打开工作区副本。MCP 可写到服务账号有权限的本机目录，但 Cowork 只有在目标目录已加入会话时才能直接读取该副本；如两者路径映射不同，请用户提供本机路径，不要猜测。

Claude Code 使用自己的项目或用户配置，与 Desktop 配置分别管理；如也使用 Code，请按实际作用域单独合并相同服务启动参数。v0.1.5 本轮未重新验收 Claude Code 会话。

### DeepSeek Harness Desktop

本机 Desktop 的配置位于 `C:/Users/<用户名>/.dsh/profiles/desktop/cordis.patch.yml`；若设置了 `DSH_HOME`，以其为根目录。文件为 YAML 顶层列表：已有其他 patch 时将下面的 `- insert:` 条目合并到同一列表；若已有同 ID 服务则修改该条目，勿重复。仅当文件内容为 `[]` 时可用下面完整示例替换。

```yaml
- insert:
    - id: mcp-zhenzhen-gptimage2-6
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: zhenzhen-gptimage2-6
        transport: stdio
        command: uv
        env:
          NO_PROXY: "localhost,127.0.0.1,::1"
          no_proxy: "localhost,127.0.0.1,::1"
        args:
          - --directory
          - D:/MCP/zhenzhen-gptimage2.6-mcp
          - run
          - --no-sync
          - zhenzhen-gptimage
          - --config-dir
          - D:/MCP/zhenzhen-gptimage2.6-mcp
          - --data-dir
          - D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared
        toolCallTimeoutMs: 630000
        failOnStartupError: true
```

打开实际 Desktop patch：

```powershell
$DshRoot = if ([string]::IsNullOrWhiteSpace($env:DSH_HOME)) { Join-Path $env:USERPROFILE '.dsh' } else { $env:DSH_HOME }
$DshConfig = Join-Path $DshRoot 'profiles/desktop/cordis.patch.yml'
if (-not (Test-Path -LiteralPath $DshConfig -PathType Leaf)) { throw "找不到配置文件：$DshConfig" }
notepad.exe $DshConfig
```

DSH 0.2.1-rc.5 与 httpx 的已观察兼容问题可能让 `[::1]` 触发 `Invalid port: ':1]'`；上述两个字段仅作用于此 MCP 子进程。如已有其他绕过地址，保留并在两个字段一致合并，移除 `[::1]`，不要覆盖其他代理或服务。重启 DSH Desktop，检查插件运行状态，再在会话调用 `get_capabilities`。本机 v0.1.5 DSH 已实际调用导出并读取副本；其他 DSH profile 未在本轮验收。

## 5. 启动排障、升级与回滚

### 日常启动与后台状态

Host 通常自动启动服务。手工启动后等待 stdio 请求是正常现象，标准输出用于协议；不要把日志写入 stdout。

```powershell
uv --directory 'D:/MCP/zhenzhen-gptimage2.6-mcp' run --no-sync zhenzhen-gptimage --config-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp' --data-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared'
```

下面查询后台；先停止全部使用该目录的 Host 接入进程，再运行停止命令。`stopping` 表示请求已接收，必要的持久化和资源关闭可能继续；等待完成后才能升级。不同数据目录需分别检查。

```powershell
uv --directory 'D:/MCP/zhenzhen-gptimage2.6-mcp' run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control status --config-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp' --data-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared'
uv --directory 'D:/MCP/zhenzhen-gptimage2.6-mcp' run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control stop --config-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp' --data-dir 'D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared'
```

`ready` 为可连接，`not_available` 为未发现后台，`incompatible` 表示版本或配置不一致。Windows 后台通过 WMI 启动，并要求私有运行目录的所有者和 ACL 正确；失败时检查日志与权限，不要删除数据库或放宽访问控制。

### 升级到 v0.1.6

先记录并查询未完成任务，停止所有使用安装目录和数据目录的 MCP 接入与后台；不要因停止而重发结果未知的收费请求。备份 `.env`、其权限、全部数据目录、图片及 SQLite 数据；对数据库使用 [SQLite backup API](docs/database-maintenance.md)，保留备份及恢复所需文件。以下步骤不会替你执行备份；完成备份和停止后运行。工作树有已跟踪改动时停止，不覆盖私有文件。

```powershell
$ErrorActionPreference = 'Stop'
$ProjectDir = 'D:/MCP/zhenzhen-gptimage2.6-mcp'
$Release = Invoke-RestMethod 'https://api.github.com/repos/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tags/v0.1.6'
if ($Release.draft -or $Release.prerelease -or $Release.tag_name -cne 'v0.1.6' -or $Release.target_commitish -notmatch '^[0-9a-f]{40}$') { throw '正式 Release 或完整提交不可用。' }
$ExpectedCommit = $Release.target_commitish
$Changes = git -C $ProjectDir status --porcelain
if ($LASTEXITCODE -ne 0 -or $Changes) { throw '工作树不干净或无法读取，请先处理。' }
$PreviousCommit = git -C $ProjectDir rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw '无法读取当前版本。' }
Write-Host "升级前提交：$PreviousCommit（请保存用于回滚）"
git -C $ProjectDir fetch origin tag v0.1.6
if ($LASTEXITCODE -ne 0) { throw '获取标签失败。' }
$TargetCommit = git -C $ProjectDir rev-parse 'refs/tags/v0.1.6^{commit}'
if ($LASTEXITCODE -ne 0 -or $TargetCommit -cne $ExpectedCommit) { throw '标签提交不匹配。' }
git -C $ProjectDir switch --detach --no-overwrite-ignore $TargetCommit
if ($LASTEXITCODE -ne 0) { throw '切换失败，请保留数据并检查。' }
uv --directory $ProjectDir sync --locked --no-dev
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请先检查或回滚。' }
uv --directory $ProjectDir run --no-sync zhenzhen-gptimage --help
if ($LASTEXITCODE -ne 0) { throw '入口复验失败。' }
```

重新启动 Host 并分别调用 `get_capabilities` 和已有任务查询。数据库可能跨版本迁移：v1→v2、v2→v3 时会建立相应备份；旧版不能直接读取较新的 schema。回滚前先保存升级后的数据库和图片，只有确认旧版兼容或具备经过验证的迁移前备份时，才切换回先前记录的提交并重新 `uv sync --locked --no-dev`；恢复旧备份不会带回备份之后的任务。不要使用 `git reset --hard`、`git clean -fdx` 或删除数据库绕过检查。

确认上述数据库兼容或完成经过验证的恢复后，可在服务停止状态下执行以下代码回退程序；它不会自动恢复数据库：

```powershell
$ErrorActionPreference = 'Stop'
$ProjectDir = 'D:/MCP/zhenzhen-gptimage2.6-mcp'
$RollbackCommit = Read-Host '输入升级前记录的完整提交 SHA'
if ($RollbackCommit -notmatch '^[0-9a-fA-F]{40}$') { throw '需要完整的 40 位提交 SHA。' }
$Changes = git -C $ProjectDir status --porcelain
if ($LASTEXITCODE -ne 0 -or $Changes) { throw '工作树不干净或无法读取，请先处理。' }
git -C $ProjectDir switch --detach --no-overwrite-ignore $RollbackCommit
if ($LASTEXITCODE -ne 0) { throw '代码回滚失败。' }
uv --directory $ProjectDir sync --locked --no-dev
if ($LASTEXITCODE -ne 0) { throw '回滚依赖安装失败。' }
uv --directory $ProjectDir run --no-sync zhenzhen-gptimage --help
if ($LASTEXITCODE -ne 0) { throw '回滚入口检查失败。' }
```

恢复数据库前请按 [数据库维护](docs/database-maintenance.md)核对版本及备份；其中早期“开发版本尚未发布”的表述属于历史状态，v0.1.5 已包含 schema v3。

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
| `export_image` | `task_id`、`image_index`、`destination`，将原件复制到指定的本机文件路径。 |
| `preview_cleanup` / `authorize_cleanup` / `execute_cleanup` | 预览、请求用户确认、执行具体计划。 |
| `get_retention_policy` / `set_retention_policy` | 查询或修改 90 天自动清理策略；启用须用户确认。 |
| `recover_task` | `task_id`，恢复同一任务，不新建生成。 |
| `accept_gif_size` | `task_id`、`sha256`、实际 `width` 和 `height`，接受待确认 GIF。 |
| `close_task` | `task_id`、`expected_status`、`reason`；仅处理允许结案的状态。 |
| `save_prompt_template` / `get_prompt_template` / `list_prompt_templates` / `render_prompt_template` | 保存、查询、分页浏览和用变量展开模板；更新使用 `expected_version`。 |

Resources：`gptimage://capabilities`、`gptimage://prompt-guide`、`gptimage://recovery-guide`；Prompt：`optimize_ecommerce_prompt`。是否在界面中显示取决于 Host。模板使用 `{{变量名}}`；详见[模板说明](docs/prompt-templates.md)，其中关于尚未接入的历史文字不代表当前工具注册状态。

## 8. 功能说明

可先让 Agent 依据资源和实际商品事实优化提示词，再提交单项或批量请求。每项需唯一 `idempotency_key`、`family`（`flare` 或 `sunburst`），并且 `prompt` 与 `template_code` 二选一。普通图像的 `images`、`flux` 通道需宽高；`chat` 不接受自定义宽高，尺寸由供应商决定。默认通道 `images`；模型按宽高和 family 路由，`explicit_model` 必须与路由一致。参考图使用 `references` 中的本地 `local_path`，最多 4 张；Flux 不支持参考图。模板可传 `template_variables`。

### 单张生成和查询示例

以下是 `generate_image` 的工具参数，可交给支持工具参数的 Agent；它会向供应商提交生成请求并可能收费，请在明确需要时使用。`idempotency_key` 是此示例请求的稳定标识：再次使用相同内容可查询或复用，新的绘图需求应使用新的唯一值。

```json
{
  "request": {
    "idempotency_key": "example-blue-mug-001",
    "family": "flare",
    "channel": "images",
    "prompt": "一只无品牌蓝色陶瓷马克杯，白色背景，无文字。",
    "width": 1024,
    "height": 1024
  }
}
```

随后调用 `get_task`，可直接使用相同幂等键查询，不创建新任务：

```json
{
  "idempotency_key": "example-blue-mug-001"
}
```

任务成功后调用 `get_image` 查询原件路径和预览；也可将该路径提供给 Agent，或使用 `export_image` 将原件复制到指定目录。请以工具返回的任务 ID 和实际 `local_path` 为准；不同 Host 可能展示预览副本。

`export_image` 的 `destination` 可使用用户指定的服务器本机绝对文件路径，无须预先设置导出目录；扩展名须与原件一致，已有文件不会覆盖。返回目标路径、类型、字节数及 SHA-256。GIF 和 SVG 按原字节复制。Cowork 内的沙箱路径不一定是 Windows 本机路径，若无法确定对应关系，应由用户提供本机工作区路径；不可自行猜测。v0.1.3 及更早版本仍要求配置导出根目录。

支持手动清理：先调用 `preview_cleanup`，提供带时区的 `before` 日期时间，或提供 `keep_latest` 保留最新数量，两者选择一个。预览包含计划 ID、到期时间、候选文件及大小、摘要和跳过原因；确认前不会删除。用户逐项审查后，可由支持 MCP 交互确认的 Host 调用 `authorize_cleanup` 并在确认界面批准，再调用 `execute_cleanup`。若 Host 不支持交互确认，用户可在本机终端执行以下命令，查看完整清单后按提示输入 `APPROVE` 和计划 ID，随后让 Agent 调用 `execute_cleanup`：

```powershell
$PlanId = Read-Host '输入 preview_cleanup 返回的计划 ID'
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control approve-cleanup --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared --plan-id $PlanId
```

命令提示输入预览返回的计划 ID；如果 Host 使用其他数据目录，须先将命令中的 `shared` 改为实际目录。计划有效期为 10 分钟，后台重启后失效；每个计划只能执行一次，变化的文件会跳过。候选可能包含已完成任务的托管原件，以及在该任务所有原件均符合清理条件时，可核验且不再供其他任务使用的供应商响应、响应清单和参考图快照；预览会列出每个具体文件。任务历史、未完成任务和工作区导出副本保留；无法核验或归属不明的文件保留。中断后如结果不明，历史返回 `cleanup_uncertain`，需检查清理账本及备份，不能自动重试删除。

每个计划最多列出 1000 个候选；若 `has_more` 为 `true`，执行后可使用相同筛选条件重新预览下一批并逐批确认。`skipped_truncated` 为 `true` 表示跳过原因未全部列出，不影响计划中的候选范围。

90 天自动清理默认关闭。先用 `get_retention_policy` 查询；仅在明确接受永久删除超过 90 天的符合条件原件及其可安全清理的供应商响应、响应清单和参考图快照后，调用 `set_retention_policy(enabled=true)` 并在 Host 确认界面批准。Host 不支持确认时，用户可在本机终端运行以下命令，阅读提示并输入 `ENABLE 90 DAYS`；关闭时调用 `set_retention_policy(enabled=false)`。服务只在后台运行时检查，关闭会等待当前正在处理的删除并阻止启动下一次删除；非运行期间不执行清理。自动清理的删除行为以隔离测试为证据，Desktop 会话未执行真实清理。

```powershell
uv --directory D:/MCP/zhenzhen-gptimage2.6-mcp run --no-sync python -m zhenzhen_gptimage.mcp_api.backend_control enable-auto-cleanup --config-dir D:/MCP/zhenzhen-gptimage2.6-mcp --data-dir D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared
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
