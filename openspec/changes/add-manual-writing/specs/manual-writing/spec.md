## Purpose

使项目的成员说明手册与实际实现、已批准的 OpenSpec 和可验证交付范围保持一致，帮助成员安全安装、配置、使用、升级与排障。

## ADDED Requirements

### Requirement: 成员文档职责
项目 SHALL 在 README 提供概述和最短安装入口，以 MANUAL 说明成员完整使用流程；长期撰写要求和指南与成员使用文档分开维护，专题资料按需引用并保持单一详细来源。

#### Scenario: 能力尚未实现
- **WHEN** 需求已规划但能力尚未实现或验收
- **THEN** 文档明确标注状态，不将其描述为已可用或已验证

### Requirement: MANUAL 结构
MANUAL SHALL 包含环境准备、项目初始化、可用性测试、客户端配置、启动排障、文件清单、资源清单、功能说明、注意事项和常见问题；不适用项说明原因。

#### Scenario: 无适用功能
- **WHEN** 项目未提供某一类能力或操作
- **THEN** 如实说明无或不适用，不虚构操作步骤

### Requirement: 项目信息与示例
手册 SHALL 根据项目实际元数据、入口、版本及验证证据分别记录仓库、标签和完整 SHA、发行包、模块、服务名、安装目录、凭据、协议及 Host；配置示例可解析且与实际一致。

#### Scenario: 尚无已验证发布版本
- **WHEN** 项目没有已验证的 Release 或标签
- **THEN** 明确说明状态，不依据包版本推测标签或宣称发布通过

### Requirement: 安装启动与凭据说明
手册 SHALL 说明 Windows 默认安装目录 `D:\MCP\zhenzhen-gptimage2.6-mcp`、锁定依赖安装、日常启动、实际配置定位和密钥来源。仅在来源缺失时回退，空值、非法值、重复及文件读取或解析失败应报告错误。

#### Scenario: 空凭据字段
- **WHEN** 已定义的密钥字段为空且下级环境存在旧值
- **THEN** 文档说明配置报错，不使用旧值；成员可填写该字段或删除字段以启用回退

### Requirement: Host 配置与实际验收
手册 SHALL 说明适用的本地 stdio Host 配置并保留已有配置；Codex Desktop、Claude Desktop 和 DeepSeek Harness Desktop 分别要求实际会话的连接、发现、调用、结果定位及适用图片展示验收，记录版本、范围和实际限制。

#### Scenario: 中转服务与隔离环境
- **WHEN** 使用 Host 支持并正确配置的 codeproxy 或其他模型渠道，或在 Windows Sandbox 中运行真实目标 Desktop Host
- **THEN** 可作为相应 Host 真实会话验收，并单独记录 Host 模型服务和 MCP 图像供应商

#### Scenario: 仅配置检查通过
- **WHEN** 只完成模板解析、进程启动或离线替身检查
- **THEN** 不将真实 Host 会话或真实供应商调用标为通过

### Requirement: 能力与副作用说明
手册 SHALL 从实现和发现结果说明 Tools、Resources、Prompts 和模板的实际能力、参数、结果、错误和费用；记录型号、格式、尺寸、并发、幂等、取消、重试和恢复的验证范围。

#### Scenario: GIF 静态预览
- **WHEN** 向成员说明 GIF 返回与预览
- **THEN** 区分首帧静态预览与保留动画的原件，说明尺寸不符时的处理

### Requirement: 升级回滚与发布
手册 SHALL 以 GitHub Releases 和实际版本、SHA、验证结果为交付依据；升级和回滚保留用户配置、图片和 SQLite 数据，说明迁移兼容和恢复验证。本项目不要求成员 ZIP 分发。

#### Scenario: 数据迁移后回滚
- **WHEN** 旧代码与迁移后的数据库不兼容
- **THEN** 说明已验证的备份恢复步骤及数据保留范围，不宣称切换代码即可恢复数据

### Requirement: 手册维护与验收证据
手册变更 SHALL 按影响核对链接、示例、实现及规范，分开报告静态检查、隔离安装、真实 Host 和供应商验证；验收结论文档化并纳入版本控制，真实验收原件和脱敏账本按工程规范保留。

#### Scenario: Host 无法验证
- **WHEN** 某个要求的 Desktop Host 尚未完成实际验收
- **THEN** 记录未验证及原因，不用另一个 Host 或替身的成功代替
