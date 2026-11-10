# 共享后台验证记录

2026-11-10，开发工作树基础提交 `c8993b869e3ee316bec8dd28e5a12b9f069c81f6` 加未提交的 `share-local-mcp-backend` 改动；不是已发布版本。Windows 隔离目录中，以安装版 v0.1.1 代码和当前工作树分别执行 `uv sync --locked --offline --no-dev`。用 v0.1.1 创建的合成 SQLite 任务、模板和图片做升级与回滚演练：旧版占用数据目录时新版拒绝启动；旧版退出后新版可查询同一任务、模板与图片摘要；停止新版后台并确认目录锁释放后，旧版重新查询成功，测试配置文件与图片 SHA-256 未改变。无供应商网络及收费请求。

首次演练暴露 Windows stdio Host 关闭时连同后代后台进程一起终止，直接的进程组 breakaway 未解决。经用户确认，改为通过本机 WMI 在独立进程树启动，使用内存中的有限环境变量；重跑 `tests/test_shared_launch.py`、`tests/test_shared_stdio_integration.py` 和 `tests/test_shared_install_upgrade.py` 结果为 4 项通过。该测试证明隔离 Host 退出后的后台状态和有序停止，不代表 Claude、Codex 或 DSH Desktop 实际会话已通过。

升级、共享并发和故障恢复的实际发布版本与 Desktop 验收仍待完成；不把开发工作树、离线替身或隔离 SDK 结果视为发布版验收。

本地完整测试：`uv run --no-sync pytest -q --basetemp=.cache/shared-final-tests` 为 240 通过、1 跳过（Windows 下不运行 POSIX 文件模式测试）、2 项依赖弃用警告；POSIX 权限通过 WSL 独立检查。随后补充旧入口测试的后台停止收尾并单独复测通过。该检查包括真实 SDK 多进程和受控供应商替身，不包含真实供应商及 Desktop 验收。

候选包版本调整为 0.1.2 后，在独立 uv 环境完整运行得到 239 通过、1 跳过、1 失败；失败源于测试套件的 `UV_PROJECT_ENVIRONMENT` 被隔离安装步骤继承，旧版虚拟环境落在错误位置。修正测试的环境隔离后，对唯一失败的安装升级回滚测试单独复测通过。当前开发版检查不代表已发布版本验收。
