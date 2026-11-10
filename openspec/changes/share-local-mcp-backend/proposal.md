# Proposal

## Why

Claude Desktop 可对同一 stdio 配置启动多个进程，现有单目录独占锁使共享连接池无法启动，Cowork 实际会话未发现服务。需要支持多个接入进程共享同一任务后台，同时保持付费生成的恢复与资源约束。

## What Changes

- 将 stdio MCP 接入与按数据目录唯一的本地后台服务分离，多个接入进程复用一个后台；自动发现、启动、重连与故障恢复。
- 保持同一数据目录的全局队列容量、生成并发、持久化幂等及保守恢复；客户端断连不自动重发收费操作。
- 保留现有工具契约、数据目录、数据库及图片；升级与回滚时阻止新旧后台同时访问同一目录。
- 更新手册、配置说明和真实 Desktop 验收，以 Cowork 为优先场景，继续覆盖 Codex 与 DSH。

## Capabilities

### New Capabilities

- `shared-local-backend`: 本地后台的单一所有权、接入、生命周期、通信与故障边界。

### Modified Capabilities

- `task-queue`: 由每目录单一 Server 改为单一后台、多 stdio 接入，维持全局队列与幂等。
- `image-results`: 区分接入进程断开与后台关闭时的结果和关闭行为。

## Impact

影响 MCP 启动、后台生命周期、进程间通信、配置及手册、进程级测试和 Host 验收。现有数据库与图片需原位兼容；不增加企业服务、远程监听或自动重复收费提交。本变更与尚未完成的 `fix-desktop-mcp-compatibility` 和 `add-manual-writing` 验收相互关联，不能以现有 Code 结果替代 Cowork 验收。
