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
