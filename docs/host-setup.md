# 本地 stdio MCP 配置

先在项目目录执行 `uv sync --locked`，按 [configuration.md](configuration.md) 设置
`ZHENZHEN_GPTIMAGEGEN_API_KEY`。本地启动命令（将路径替换为实际绝对路径）：

```text
uv run --locked --project E:\mcp-server-workspace\zhenzhen-gptimage2.6-mcp zhenzhen-gptimage --config-dir E:\mcp-server-workspace\zhenzhen-gptimage2.6-mcp --data-dir E:\mcp-server-workspace\zhenzhen-gptimage2.6-mcp\runtime-data
```

以下命令会修改相应 Host 的配置，运行前应根据机器实际路径调整。三个 Host 需使用
不同数据目录，或确保不会同时运行。Claude Code 和 Codex 的命令格式已使用本机 CLI
在隔离配置目录验证，Claude 的隔离 MCP 健康检查显示 Connected；尚未验证会话内生图。

## Codex CLI

```powershell
codex mcp add zhenzhen-gptimage -- uv run --locked --project E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp zhenzhen-gptimage --config-dir E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp --data-dir E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp/runtime-data/codex
codex mcp get zhenzhen-gptimage
```

`codex mcp get` 显示的是注册内容，不代表已连接或已验证图片显示。另见
[OpenAI Docs MCP](https://developers.openai.com/learn/docs-mcp)。

## Claude Code

```powershell
claude mcp add --scope user --transport stdio zhenzhen-gptimage -- uv run --locked --project E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp zhenzhen-gptimage --config-dir E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp --data-dir E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp/runtime-data/claude
claude mcp get zhenzhen-gptimage
```

如只希望当前项目使用，可将 `--scope user` 改成 `--scope project`；以当前
Claude Code 版本的 `claude mcp add --help` 为准。

## DeepSeek Harness

本机 DSH 0.2.1-rc.5 的 `@deepseek-ai/dsh-mcp-client` 使用 Cordis overlay。示例
overlay（保存为本地 YAML 文件，路径根据实际调整）：

```yaml
- insert:
    - id: zhenzhen-gptimage
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: zhenzhen_gptimage
        transport: stdio
        command: uv
        args:
          - run
          - --locked
          - --project
          - E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp
          - zhenzhen-gptimage
          - --config-dir
          - E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp
          - --data-dir
          - E:/mcp-server-workspace/zhenzhen-gptimage2.6-mcp/runtime-data/dsh
        toolCallTimeoutMs: 630000
        failOnStartupError: true
```

以 `dsh headless --patch <overlay绝对路径> --dump-config` 可检查合并后的配置；实际
使用的 profile 应根据本机安装情况选择。隔离 overlay 的合并已验证，但尚未完成 DSH
工具调用及图像展示实测。DSH 默认每次工具调用超时为 60 秒，因此示例设置 630 秒，
以覆盖服务端 600 秒任务期限；它不改变服务端期限。

此 DSH 版本会从子进程环境中剔除包含 KEY/TOKEN 等字样的环境变量，因此建议使用
项目 `.env`；也可按 DSH 的 `env` 配置显式传入。其文档说明 MCP Prompt 模板不支持，
图像展示还依赖当前模型与附件功能。stdio 初始协商会启动临时探测进程；它与本项目
单目录实例锁的实际交互仍需在目标 Host 中验证。

`--config-dir` 用于定位默认 `.env`；如需指定其他文件，可用绝对路径
`--env-file`。同一 `--data-dir` 只允许一个活动 Server，其他 Host 同时启动并
使用同目录会收到启动错误。每个 Host 使用独立目录则任务和历史彼此独立。
Chat Completions 返回尺寸由供应商决定，不支持定制宽高；需要定制时选择
Generations 或 Flux。调用生成工具将请求远程服务并可能产生费用。
