# 目标 Host 会话验收记录

记录日期：2026-11-09。范围为隔离配置及本地替身；未修改正式 Host 配置、未发起收费图像生成请求。状态为**未通过完整验收**，不得将注册或 MCP SDK 测试视为真实 Host 会话结果。

| Host | 已观察到的结果 | 会话验收缺口 |
| --- | --- | --- |
| Codex CLI 0.163.0 | 隔离 CODEX_HOME 下 MCP add/get 可解析 stdio 配置；尝试 `codex exec --oss --local-provider ollama` 时，本机 127.0.0.1:11434 连接被拒，CLI 报无 Ollama 服务 | 未进入模型会话，工具发现、长调用终止、会话图片渲染均未验证 |
| Claude Code 2.1.303 | 隔离 CLAUDE_CONFIG_DIR 下 MCP add/get 显示 Connected；尝试以虚构密钥和 `ANTHROPIC_BASE_URL=http://127.0.0.1:9` 启动 print 会话，等待期间无输出后中断 | 模型会话未完成，工具发现、长调用终止、会话图片渲染均未验证；Connected 仅表明配置健康检查成功 |
| DeepSeek Harness DSH 0.2.1-rc.5 | headless 配置可用，隔离 MCP overlay 的 `--dump-config` 包含指定条目及 630 秒工具超时 | 未发现可供无收费会话使用的本地模型服务，也未确认能安全将该 profile 的模型请求指向本地替身；未启动真实模型会话，工具发现、长调用终止、会话图片渲染均未验证 |

独立 FastMCP/MCP Client 的本地协议与图片内容块测试已运行，但不是上述三个产品的会话 UI 验收。可用本地模型或明确授权并配置可控模型服务后，应在隔离配置下逐项复测，记录 Host 版本、工具发现结果、长调用中断状态与当前 session window 中实际渲染结果。不得因供应商生成未调用而假设 Host 的模型请求不会产生费用。

## 后续桌面会话检查

用户授权使用 Codex 当前登录，以及 Claude Desktop 与 DeepSeek Harness 现有进程。Codex CLI 使用当前 OpenAI 认证、临时 MCP 命令行配置和独立数据目录，在真实模型会话中调用本项目 `get_capabilities` 成功，返回 Chat 尺寸不可定制；未调用图像生成。该次不证明长调用终止或图片渲染。

Claude Desktop 新建只读验收会话后，模型调用的是现有 `zhenzhen-gptimagegen2.5-mcp` 的 `get_model_guide`，而非本项目 2.6 服务；当前不能据此声称本项目工具发现通过。DeepSeek Harness 桌面新建只读会话显示“已停止”，没有返回工具调用结果；原因未确定。两者均未完成本项目的生图、长调用终止或图片展示验收。未修改桌面应用配置，未调用图像生成；模型会话可能产生模型服务费用。

## Codex 同步生成验收

用户随后将本期 Host 验收范围限定为 Codex。2026-11-09 使用 Codex CLI 当前 OpenAI 登录、临时 MCP 命令行配置和独立数据目录执行一次真实 `generate_image`。Images 通道 `gpt-image-2.6-flare` 返回 `succeeded`、attempt_count=1；图片保存为 `.cache/host-codex-generation/images/4628417b-7c68-425a-aab3-5f9a31a4ff52.0.png`，实测 PNG 1024×1024，人工查看为白底蓝色杯子。Codex CLI 报告工具返回图片内容；本次未观察 Codex Desktop 会话中图像渲染，也未在真实 Codex 中断长调用。该生成请求可能收费；没有重试或切换模型。

随后重启 Codex Desktop，加载项目级 `zhenzhen-gptimage26-validation`，在当前 Desktop 会话中调用 `generate_image` 一次：task_id `b928f9e9-87c2-41ea-ac88-f2556d921a4b`，`succeeded`、attempt_count=1，原图为 `.cache/desktop-validation/images/b928f9e9-87c2-41ea-ac88-f2556d921a4b.0.png`，1024×1024。展开 Desktop 的 MCP 工具结果后，实际观察到蓝色杯子的图片内容块，以及结构化 JSON；它不是仅通过回复 Markdown 引用文件得到的展示。此请求可能收费。Codex Desktop 真实长调用中断尚未验证，不能凭该成功结果勾选 10.3。

## Codex Desktop 长调用中断验收

2026-11-09，加载单独的 `zhenzhen-gptimage26-slow-test`；它运行本项目真实 MCP Server、调度与 SQLite，供应商替身在本地等待 120 秒，不连接远程服务。用户在 Desktop 中工具调用进行时按停止；工具等待被中断。重续后查询 task_id `6e856cef-f2d5-4e6c-86e7-126a21b40351`：开始时为 `submitting`、attempt_count=1。替身结束并返回故意无图片的响应后，任务进入 `recovery_pending`，attempt_count 仍为 1；以相同幂等键再次调用返回原任务，替身账本仍仅有一次 started 记录。没有将停止误称为远程取消；本项不验证真实供应商取消或超时行为，也未发送收费图像请求。
