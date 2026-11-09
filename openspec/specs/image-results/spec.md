# image-results Specification

## Purpose

将供应商图像结果转为可校验的本地文件及可展示的会话预览，提供可靠历史定位，并在下载、解析或磁盘异常时保留恢复能力而不是重复生成。

## Requirements

### Requirement: 完整结果落盘
系统 SHALL 验证图片集合后再标记成功，登记实际尺寸、媒体类型、字节数、路径及摘要；Generations/Flux 尺寸不符进入 recovery_pending，Chat 不作请求尺寸比较。

#### Scenario: 部分下载失败
- **WHEN** 多张图片中一张下载失败
- **THEN** 不标记整任务成功，保留恢复材料且不重新生成

### Requirement: 资源限制与预览
系统 SHALL 执行[设计](../../changes/archive/2026-11-09-add-image-generation-mcp/design.md)第 8 节已批准的输入、输出、解码、下载及磁盘限制，每次工具输出最多一张长边 1024、编码后不超过 1 MiB 的预览，完整原图落盘。

#### Scenario: 结果超限
- **WHEN** 结果超过图片数量或字节上限
- **THEN** 明确报告资源错误，不静默截断为成功，不重发生成

### Requirement: 本地查询和历史
系统 SHALL 提供任务、图片及历史查询，默认每页 20 条、最多 100 条，游标绑定筛选条件；读取不触发生成或远程重新下载。

#### Scenario: 原图被外部删除
- **WHEN** 用户查询已登记但缺失的文件
- **THEN** 报告文件不可用而非再次生成图片

### Requirement: 日志和生命周期
系统 SHALL 保持 stdout 为 MCP 协议流，脱敏记录诊断信息；关闭时停止接收并给予在途任务最多 30 秒且不超过剩余期限的宽限期，超时后不再启动请求，必要的状态持久化和资源关闭可以继续完成；不自动删除用户图片。

#### Scenario: 生成中关闭
- **WHEN** Server 接到关闭请求
- **THEN** 停止接收和启动重试，保留未完成任务的恢复状态
