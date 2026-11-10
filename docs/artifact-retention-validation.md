# 原件导出与保留策略验证记录

2026-11-10，在开发工作树、Windows 和 Python 3.12.14 的隔离 uv 环境中运行完整测试，结果为 284 通过、1 跳过（Windows 不适用的 POSIX 文件权限测试）、2 个依赖弃用警告；使用 WSL 验证 POSIX 原件导出、变更文件保护以及隔离目录中断恢复。上述结果不代表已发布版本或 Desktop 会话验收。

隔离测试覆盖 PNG、两帧 GIF、SVG 字节及摘要，冲突与不完整复制；通过两个 MCP 客户端和共享 IPC 测试导出、读取与清理的互斥。受控供应商替身和真实调度/恢复流程并发运行时，自动清理仅删除隔离环境中符合条件的已完成产物；未完成任务及其恢复响应被保留。启用策略需要模拟 Host 用户确认或模拟本机终端确认；默认关闭，恰好 90 天不清理，关闭后不启动下一项删除。

已完成任务的登记响应正文、校验清单和独占参考快照可进入已审查的清理清单；其他任务共享的快照、无法核验的文件和活动任务材料保留。测试覆盖部分失败、实际进程中断前后、清理状态查询，以及原件/关联材料的结果不明时禁止自动重删。SQLite v2 升级到 v3 先备份；隔离升级回滚使用 SQLite 备份恢复并核对原任务、模板和图片。所有删除均为测试创建的合成文件，未删除用户原件，也未发起供应商生图。

候选版本为 0.1.3；发布、安装、三个 Desktop 的实际会话和 Cowork 工作区路径映射仍待验证。完整工作树版本的测试不代替最终合入提交或发布标签的复核。

2026-11-10 发布及安装：PR #4 合并提交 `7b0ae11d47cdf5429991ff0cabec60a6432a1068` 与通过检查的候选代码树一致；该合并提交独立检出的完整测试为 284 通过、1 跳过，OpenSpec 严格校验通过，仓库未配置 CI。[v0.1.3 预发布](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases/tag/v0.1.3) 标签指向该提交。确认四个数据目录没有未完成任务后，仅停止旧 MCP 接入及共享后台；将实际安装目录升级到发布标签并以离线锁定依赖安装。升级前用 SQLite backup API 备份四个数据库，记录逻辑内容摘要及 9 个图片、响应和参考快照摘要；升级后重新核对均一致，原 `.env` 不存在。最终备份与脱敏账本保存在 Git 忽略的 `.cache/upgrade-v013-final/`。这些检查发生在新服务首次启动及数据库迁移之前；三个 Desktop 的发布版会话验收仍待用户设置导出根目录并重启。

发布版 Claude Desktop Cowork 验收：配置授权导出根目录并重新启动后，通过实际会话调用 `export_image` 导出既有蓝杯 PNG，成功在 Cowork 的工作区文件查看器中打开。副本本机路径和该会话报告的沙箱路径均为 `D:\MCP-host-tests\zhenzhen-gptimage2.6\assets\generated\cowork-v013-blue-mug.png`；1,114,124 字节，原件与副本 SHA-256 均为 `5b834ee871edbd45c3fb5e309021cf52890ea8a23c72dc6ba49b54f143a2703f`，已另以本机文件哈希独立核对。未重新生成图片；该次验收只覆盖此会话和 PNG，不能推断其他 Cowork 沙箱的路径映射。

发布版 DeepSeek Harness Desktop 验收：在既有工作区会话调用 `export_image`，成功导出并在会话中展示蓝杯图片，副本位于 `D:\MCP-host-tests\zhenzhen-gptimage2.6\assets\generated\dsh-v013-blue-mug.png`；本机独立计算的 SHA-256 与上述原件一致。会话中 `get_retention_policy` 返回 `enabled: false`、`retention_days: 90`，未启用或执行清理，也未重新生成图片。此项验证不代表已完成 Codex Desktop 的导出与共享权限验收。

DSH 补充权限检查：通过同一会话将目标指定为授权根目录外的 `D:\MCP-host-tests\unauthorized-boundary-check.png`，`export_image` 返回 `ARTIFACT_UNAVAILABLE`，独立检查该目标文件不存在；未执行生图或清理。

发布版 Codex Desktop 验收：重新加载 MCP 后，从当前会话调用 `export_image`，将同一既有原件导出至 `D:\MCP-host-tests\zhenzhen-gptimage2.6\assets\generated\codex-v013-blue-mug.png`；工具返回成功，本机文件 SHA-256 与原件一致。`get_retention_policy` 返回 `enabled: false`、`retention_days: 90`；指定授权根目录外的目标时返回 `ARTIFACT_UNAVAILABLE`。三个 Host 使用同一配置数据目录；检查到共享后台是同一条父子进程链，Codex 和 DSH 均读到关闭的策略。此次验证未启用或执行清理，未发起新的生图请求；共享后台的并发及清理授权细节另由隔离自动化测试覆盖。

v0.1.4 候选开发环境验证：取消导出根目录限制后，在 Windows 和 Python 3.12.14 上运行完整测试，285 通过、1 个 POSIX 权限测试跳过；其中通过隔离的 v0.1.2 标签安装副本验证旧数据升级和回滚。测试覆盖未配置根目录和已有根目录时导出到其他路径、原件哈希、文件冲突、GIF/SVG 原字节及并发清理。该记录不代表发布版安装或 Desktop 会话已验收。

v0.1.4 发布版安装及协议验证：发布标签指向合并提交 `396dce31e98534d94c74127b3d5ad111f4d9a7b5`，其代码树与独立检出验证的 PR 提交一致；该独立检出完整测试 285 通过、1 跳过，OpenSpec 严格校验通过。升级前核对无未完成任务并备份四个 SQLite 数据库；升级后核对数据库逻辑内容、完整性及 7 个持久化配置和产物文件摘要一致，备份和脱敏账本保存在 `.cache/upgrade-v014/`。实际安装目录以发布标签及离线锁文件升级，并启动新版共享后台；用实际安装的 stdio MCP 客户端导出已有蓝杯原件到旧配置根目录之外的 `D:\MCP-host-tests\v014-export-verification\blue-mug.png`，副本摘要与原件一致，自动清理策略保持关闭。该协议测试未调用供应商；不代表新版在三个 Desktop 会话中分别完成验收。

v0.1.4 三个 Desktop 会话导出验证：Codex Desktop、Claude Desktop Cowork 和 DeepSeek Harness Desktop 分别调用 `export_image`，将同一个既有 PNG 导出到 `D:\MCP-host-tests\v014-codex\assets\blue-mug.png`、`D:\MCP-host-tests\v014-claude\assets\blue-mug.png` 和 `D:\MCP-host-tests\v014-dsh\assets\blue-mug.png`，均位于旧导出根目录之外。独立核对三个副本与原件的 SHA-256 一致（`5b834ee871edbd45c3fb5e309021cf52890ea8a23c72dc6ba49b54f143a2703f`）。DSH 会话读取了其副本；Cowork 因该次目标目录未挂载而无法在沙箱内读取，文件存在和摘要由本机独立核对，未验证 Cowork 对该目录的直接访问。本轮未生成新图片或执行清理。
