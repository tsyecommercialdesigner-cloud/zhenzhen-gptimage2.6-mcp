# 本地 stdio MCP 配置

以下示例适用于包含共享后台变更的版本，尚需发布版 Desktop 实测；v0.1.1 仍要求每个活动 Server 使用独立数据目录。先完成 [MANUAL 安装与凭据配置](../MANUAL.md#2-项目初始化)，保持现有 Host 条目和认证不变，只合并本服务条目。首次联调前确认配置已应用，并按 Host 要求重启。

示例使用 `D:/MCP/zhenzhen-gptimage2.6-mcp` 和别名 `zhenzhen-gptimage2-6`。想共享任务、幂等和模板时，多个 Host 应使用相同的配置目录、密钥及 `--data-dir`；以下示例采用 `runtime-data/shared`。如需隔离历史，改为不同数据目录。入口未指定 `--data-dir` 时使用启动工作目录下的 `runtime-data`，因此建议在 Host 配置中明确指定绝对路径。

## Codex Desktop

将以下内容合并至 Codex 的 MCP 配置，保留其他表：

```toml
[mcp_servers.zhenzhen-gptimage2-6]
command = "uv"
args = ["--directory", "D:/MCP/zhenzhen-gptimage2.6-mcp", "run", "--no-sync", "zhenzhen-gptimage", "--config-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp", "--data-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared"]
```

## Claude Desktop / Code

在实际 Claude Desktop 使用的配置文件 `mcpServers` 对象中合并此条目，保留其他服务。Claude Code 的配置作用域与 Desktop 不同，按实际使用的客户端分别配置；Cowork 是否可连接须在目标版本实测。

```json
{
  "zhenzhen-gptimage2-6": {
    "command": "uv",
    "args": ["--directory", "D:/MCP/zhenzhen-gptimage2.6-mcp", "run", "--no-sync", "zhenzhen-gptimage", "--config-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp", "--data-dir", "D:/MCP/zhenzhen-gptimage2.6-mcp/runtime-data/shared"]
  }
}
```

## DeepSeek Harness

针对 DSH Desktop 0.2.1-rc.5，在该服务的 Cordis overlay 合并以下配置，不覆盖其他插件：

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

受影响版本的 httpx 可能因 `[::1]` 报 `Invalid port: ':1]'`。两个 `config.env` 字段只影响该 MCP 子进程；若原有绕过列表还有其他域名或地址，保留并一致合并，移除 `[::1]`。DSH 可能过滤含 KEY/TOKEN 的环境变量；建议使用项目 `.env`，或按 DSH 实际行为显式配置。重启后检查插件状态、工具发现和实际调用；`--dump-config` 不代表会话验收。630 秒客户端超时不改变服务端 600 秒期限。

后台状态、受限权限及有序停止见 [MANUAL 排障](../MANUAL.md#5-启动排障升级与回滚)。图片原件路径以工具返回的 `local_path` 为准，Host 附件可能只是预览副本。生成图片可能收费。
