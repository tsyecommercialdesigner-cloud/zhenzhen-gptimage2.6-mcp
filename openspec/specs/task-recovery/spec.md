# task-recovery Specification

## Purpose

在同步生成、网络中断与本地写入失败时保留可追溯状态，限制安全重试并阻止未知结果的重复付费提交，使用户能够恢复本地结果或显式结束悬而未决的任务。

## Requirements

### Requirement: 安全重试预算
系统 SHALL 同一任务总计最多 3 次生成尝试，仅重试明确未发送的临时失败或明确未受理的可重试错误；固定模型及通道，重启不重置次数。

#### Scenario: 读取超时
- **WHEN** 请求已发送但响应读取超时
- **THEN** 标记 unknown，不自动重试或跨通道重新生成

#### Scenario: 两次可安全重试失败
- **WHEN** 前两次明确未发送且剩余期限允许
- **THEN** 退避后允许第三次尝试，第三次失败不再自动生成

### Requirement: 状态恢复与本地恢复
系统 SHALL 启动恢复已提交状态，保守处理提交窗口；完整响应已持久化的 recovery_pending 任务可仅恢复解析、下载及保存，单次恢复预算 600 秒。

#### Scenario: 响应已保存但落盘中断
- **WHEN** recover_task 处理具备可靠响应的任务
- **THEN** 只执行本地恢复流程，生成 attempt_count 不增加

#### Scenario: 提交结果未知
- **WHEN** 同步提交可能已送达但结果未知
- **THEN** 标记 unknown，不自动重发或换通道

#### Scenario: 异步远程 ID 已持久化后重启
- **WHEN** GIF 异步任务已持久化远程任务 ID，进程中断并重启
- **THEN** 查询同一远程任务并恢复结果处理，不重新提交生成

### Requirement: 显式结案
系统 SHALL 允许 unknown/recovery_pending 按 expected_status 显式结案，记录原因并释放队列容量；已知远程任务未达终态时拒绝结案，并对远程终态不明的异步提交继续保守限制生成并发。并发状态冲突报错，重复结案不重复释放容量。

#### Scenario: 重复结案
- **WHEN** 已 closed 任务再次收到结案请求
- **THEN** 返回原结案结果，保留原原因及幂等记录

### Requirement: 持久化失败保护
系统 SHALL 在无法持久化接收或尝试状态时不发送生成请求，损坏或不兼容数据库不得静默替换，升级前提供一致性备份。

#### Scenario: 数据库不可写
- **WHEN** 发送前写入尝试记录失败
- **THEN** 返回持久化错误，远程请求次数为零
