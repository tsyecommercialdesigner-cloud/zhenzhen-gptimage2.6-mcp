# Design

## Context

见 [proposal](proposal.md)。项目采用 OpenSpec，已确定手册撰写要求与成员手册分离。已接受旧指南的适用部分，拒绝 ZIP 分发和不列 Host 配置路径的额外限制；现有 `--config-dir` 默认工作目录与固定安装目录定位存在差异。

## Goals / Non-Goals

**Goals:** 建立可校验的手册要求、可操作的写作指南及简短入口，准确保留 Host、凭据与验收边界。

**Non-Goals:** 本次不创作成员 README/MANUAL、不修改应用代码、真实 Host 或密钥，也不以文档完成冒充实际验收。

## Decisions

### ADR-001：规范与指南分层

- 状态：已接受。
- 决策：`openspec/specs/manual-writing/spec.md` 保存规范性要求，`guide.md` 保存十节结构、项目参数与写作检查；根目录 `CONVENTIONS.md` 只提供简短入口。
- 备选：将旧指南整体放入 docs 或复制所有旧模板要求；不符合用户指定的职责及适用范围。
- 影响：工程习惯仍由 `engineering-practices` 与各变更 ADR 维护；不修改 OpenSpec 生成的 AGENTS.md 和 CLAUDE.md。

### ADR-002：Host 实际验收与供应商分离

- 状态：已接受。
- 决策：Codex Desktop、Claude Desktop、DeepSeek Harness Desktop 均需实际会话验收；可用已配置的 codeproxy 或其他支持的模型渠道，必要时采用 Windows Sandbox。真实图像生成服务、Host 对话模型及授权范围分开记录。
- 备选：只用 headless 或仅接受官方 API Key；不符合用户决定，也不足以替代实际 Desktop 证据。
- 限制：这项文档决策不自动证明任何 Host、安装流程或 Sandbox 已验收通过。

### ADR-003：DSH 子进程代理绕过列表兼容

- 状态：已接受；适用范围为确认受影响的 DSH Desktop 0.2.1-rc.5 与本项目 httpx 0.28.1 组合，其他版本以实际验证为准。
- 背景：DSH [代理策略源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/util/http-proxy/src/policy.ts)将 `::1` 与 `[::1]` 加入回环绕过列表；本机隔离复现表明 httpx 初始化时带方括号条目触发 `Invalid port: ':1]'`。上游 [Discussion #9606](https://github.com/deepseek-ai/deepseek-harness/discussions/9606) 与 [#8056](https://github.com/deepseek-ai/deepseek-harness/discussions/8056) 为用户问题报告，不代表官方已确认或修复；master 与本机版本不必然相同。
- 决策：手册要求在 DSH MCP 的 `config.env` 示例中为 `NO_PROXY`、`no_proxy` 均设置 `localhost,127.0.0.1,::1`；已有其他绕过项时保留并在两字段一致合并，排除 `[::1]`。仅改变该 MCP 子进程的绕过列表，不覆盖其他服务、代理地址或凭据。
- 验证边界：隔离 DSH 复测未再出现相同启动错误；真实 Desktop 的插件状态、工具发现和会话调用仍需实际验证。不得把本项配置说明写成上游已修复或 Host 验收已通过。

## Risks / Trade-offs

- [实际实现与期望目录定位不一致] → 手册如实说明现有入口并单独规划修复，不能把目标写成现状。
- [示例过时或使用私有密钥] → 根据实际版本、Schema 和脱敏证据核验；不执行付费调用或修改用户 Host 来验证文档。

## Migration Plan

先创建规范和指引，再按需编写成员手册和执行三个 Desktop 的实际验收；验证状态未满足时保持未完成。GitHub Releases 为项目发布方式，ZIP 不适用。
