# prompt-templates Specification

## Purpose

让用户将常用电商提示词保存为可浏览、可查询和可快捷调用的模板，通过明确版本与变量校验确保复用稳定，同时保证历史任务不被模板后续修改影响。

## Requirements

### Requirement: 模板存取与版本
系统 SHALL 按区分大小写的唯一 code 保存模板；新建不带 expected_version，更新必须匹配版本；内容未变不增加版本，列表支持搜索和分页。

#### Scenario: 过期版本更新
- **WHEN** 更新提供的版本不是当前版本
- **THEN** 返回 TEMPLATE_VERSION_CONFLICT，不覆盖其他修改

### Requirement: 安全展开与快捷调用
系统 SHALL 只执行命名占位符替换，不执行表达式；校验变量与必填项，展开不超过 32 KiB，生成前冻结模板版本和结果。

#### Scenario: 模板已更新但任务重试
- **WHEN** 已入队模板任务发生安全重试且模板已更新
- **THEN** 仍使用原快照，不采用新模板内容

#### Scenario: 只展开模板
- **WHEN** 调用 render_prompt_template
- **THEN** 返回 prompt、code、version，不创建生成任务或付费请求
