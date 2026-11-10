# Proposal

## Why

已确认的工程习惯需要成为项目可追溯、可审查的长期要求，同时避免复制旧仓库不适用于本项目的技术栈和业务假设。

## What Changes

- 建立 `engineering-practices` 主规范，覆盖 OpenSpec、ADR、验证、证据、MCP 边界、Git、CI/CD、发布和兼容性。
- 按用户决定区分 `.cache/` 中保留的真实验收原件和脱敏账本、版本控制的验收结论，以及应分类清理的测试临时产物。
- 保留已批准的项目技术选择；不因此创建 CI 工作流、修改运行代码、发布或更改 Host 配置。
- `manual-writing` 另行逐项讨论，不在本变更制定或创建；不改写生成的 AGENTS.md 和 CLAUDE.md。

## Capabilities

### New Capabilities

- `engineering-practices`: 维护项目工程规范和变更、验证、交付的可追溯边界。

### Modified Capabilities

无。

## Impact

OpenSpec 变更材料和工程主规范；当前已存在实现与业务规范保持不变。规范是未来工作的要求，不代表 CI、门禁或发布已实际建立。
