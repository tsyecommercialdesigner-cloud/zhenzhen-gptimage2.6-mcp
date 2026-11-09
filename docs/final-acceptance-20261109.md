# 实施验收记录（2026-11-09）

## 环境与检查

使用新的 `.cache/final-clean-4k-20261109` 环境执行 `uv sync --locked`，Python 3.12.14、SQLite 3.53.1；全套测试 **135 passed、2 warnings**。测试汇总警告来自 Authlib 弃用提示；pytest 启动时另有 asyncio fixture 默认作用域的弃用提示。`openspec validate --specs` 六项通过，变更 `--strict` 通过，`git diff --check` 通过。

## 六项能力证据

| 能力 | 证据与范围 |
| --- | --- |
| prompt-assistance | `test_prompt_templates.py`、`test_mcp_surface.py`：指引与 Prompt 可发现；实际 Host 自动优化质量未做独立人工验收 |
| image-generation | `test_t8_star_provider.py`、`test_local_end_to_end.py`：三种格式隔离测试及 4k 映射；Codex Desktop 一次真实 Generations 生图；[供应商验收](provider-acceptance-20261109.md) 中修复后的独立 stdio MCP Flux 4k 真实调用与落盘成功 |
| task-queue | `test_repository_tasks.py`、`test_scheduler_engine.py`、`test_local_stress.py`：原子接收、幂等、20 容量及 6 并发；为本地替身测试 |
| image-results | `test_artifact_output.py`、`test_mcp_backend.py`：下载、文件与预览；Codex Desktop 实际 MCP 图片块已展示 |
| prompt-templates | `test_prompt_templates.py`、`test_local_end_to_end.py`：版本、变量和快照复用；本地隔离测试 |
| task-recovery | `test_recovery_service.py`、`test_recovery_crash.py`：进程中断与结案；Codex Desktop 本地慢替身中断无重复提交，见 [Host 验收](host-session-validation.md) |

## 非功能约束证据

| 编号 | 验证范围 |
| --- | --- |
| NFR-01 | `test_scheduler_engine.py`、`test_t8_star_provider.py`：安全重试、上限、退避和未知状态；未证明供应商所有错误语义 |
| NFR-02 | `test_repository_tasks.py`、`test_scheduler_engine.py`：本地幂等、冲突和快照复用 |
| NFR-03 | `test_database.py`、`test_recovery_crash.py`：事务、WAL、备份及进程崩溃窗口；非硬件故障保证 |
| NFR-04 | `test_scheduler_engine.py`：任务期限、取消、持续分块；真实供应商所有耗时未穷尽 |
| NFR-05 | `test_local_stress.py`、`test_artifacts_storage.py`、`test_artifact_output.py`：并发、容量与资源限额；压力数据使用合成负载 |
| NFR-06 | `test_artifact_output.py`、`test_recovery_crash.py`：文件验证、异常与恢复 |
| NFR-07 | `test_mcp_backend.py`、`test_scheduler_engine.py`：目录锁与关闭；30 秒为等待在途任务宽限期，必要持久化和资源关闭允许继续 |
| NFR-08 | `test_bootstrap_io.py`：stderr、轮转、脱敏；不代表已审计所有第三方日志 |
| NFR-09 | `test_local_end_to_end.py` 与 [Host 验收](host-session-validation.md)：Codex Desktop 图片块及中断；Claude/DSH 不属于本期 Host 验收 |
| NFR-10 | `test_config.py`、`test_bootstrap_io.py` 与本次干净安装：密钥来源、TLS/代理配置和锁文件；具体生产网络环境未全覆盖 |
| NFR-11 | `test_database.py`、`test_bootstrap_io.py`：备份恢复、迁移回滚和日志轮转；自动清理/定时备份非首版要求 |

## 未通过与限制

- 后续诊断发现显式 flare-4k 的 503 错误指向重复后缀；基础 flare 型号结合 3072×2048 和 3840×2160 均返回对应尺寸。产品已修正 flare HTTP 映射，独立 stdio MCP 的 Flux 4k 真正端到端调用及落盘成功；sunburst 4k、其他未测型号、多图因果贡献及真实账单仍未核验。Desktop 旧 MCP 进程未重启。
- 本次授权的供应商验收及诊断共 7 次，额度已用完；完整证据见 [供应商验收](provider-acceptance-20261109.md)。
- 用户之后新增最多 10 次收费测试授权，MCP 4k 复验使用 1 次，尚余 9 次。
- MCP 使用项目级 Desktop 测试配置和 `.cache` 数据目录；未执行正式安装、发布或升级。非 4k 验收的成功不代表所有 provider 组合均可用。
- 本报告区分供应商原始接口成功、产品代码离线回归和未覆盖的真实组合，不将其等同于全部型号的真实付费验证。
