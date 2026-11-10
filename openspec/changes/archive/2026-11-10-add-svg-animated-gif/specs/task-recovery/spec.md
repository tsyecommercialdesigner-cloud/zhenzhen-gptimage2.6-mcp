## MODIFIED Requirements

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
