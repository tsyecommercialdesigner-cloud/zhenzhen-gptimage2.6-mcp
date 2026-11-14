# Proposal

## Why

Agent 收到的 MCP 工具 Schema 暴露了字段类型，却缺少关键参数含义、条件依赖和示例；现有校验失败提示也不足以指导纠正，导致调用者难以构造有效请求。

## What Changes

- 完善已注册 MCP 工具及参数的机器可见说明、默认值、约束、典型调用示例和结果处理指引，重点覆盖生成、批量、查询、恢复、图片获取与导出，并覆盖其余工具。
- 将现有可表达的条件约束纳入兼容的输入 Schema；不能可靠表达或 Host 不支持的约束明确写入描述并由服务端校验。
- 返回安全、具体、可操作的参数错误，不泄露提示词、路径、密钥或内部异常；保留现有错误类别及恢复语义。
- 使用实际发布安装与已配置目录，在 Codex Desktop、Claude Desktop Cowork 和 DeepSeek Harness Desktop 中验证 Agent 传参，并将实测范围与证据记录；真实生图需另获明确收费授权。
- 保持现有工具名、字段、已支持请求、模型路由、幂等、任务和供应商能力不变。

## Capabilities

### New Capabilities

- `mcp-tool-contracts`: MCP 工具的可发现参数契约、示例、条件约束、错误反馈及 Host 验证。

### Modified Capabilities

无。

## Impact

影响 FastMCP 注册、Pydantic 输入模型、验证错误映射、MCP 资源与提示、工具及 Host 测试、成员手册与验收文档。不会更改供应商接口、配置、数据库或生成策略；JSON Schema 兼容性需在支持的 Host 中实测。
