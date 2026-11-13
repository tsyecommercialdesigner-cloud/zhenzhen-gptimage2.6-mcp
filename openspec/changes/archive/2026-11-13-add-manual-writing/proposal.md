# Proposal

## Why

项目需要一套与实际 OpenSpec、MCP 能力及成员使用方式一致的说明手册撰写规范，使手册可复现、可验证并准确披露已验证范围。

## What Changes

- 建立 `manual-writing` 长期规范及配套写作指南，按用户逐项确认的边界维护 README、MANUAL、Host 和发布说明。
- 在根目录提供简短 CONVENTIONS.md，引用工程规范和说明手册撰写规范；不修改 AGENTS.md 或 CLAUDE.md。
- 明确三种 Desktop Host 的实际验收要求、已批准的 codeproxy 使用方式及必要时的 Windows Sandbox；不将尚未完成的验收描述为通过。
- GitHub Releases 为发布方式，不要求成员 ZIP 分发；默认安装路径和配置行为以已确认决定及实际实现差异为准。

## Capabilities

### New Capabilities

- `manual-writing`: 维护成员手册编写、交付与验证要求。

### Modified Capabilities

无。

## Impact

影响 OpenSpec 手册规范及根目录约定；不改变业务代码、用户 Host 配置、密钥或真实验收状态。待实施的具体手册及 Host 验收另行列入任务。
