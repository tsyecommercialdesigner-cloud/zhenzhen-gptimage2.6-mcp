# 本地结果恢复

提交后未取得完整响应时，任务可能为 `unknown`，供应商可能已受理并产生费用。用 `get_task` 提供原任务 ID 或幂等键查询。若有同一远程任务 ID，且查询结果列出恢复动作，`recover_task` 可查询该远程任务。另行提交前须取得用户授权。

`recovery_pending` 表示已有响应或材料等待处理。查看 `error_category`、`recovery_mode` 及 `allowed_actions`。对已保存响应，恢复可以重做解析、下载或写入，生成尝试次数保持不变。有效静态图尺寸不符时，结果原样登记为成功，并通过 `SIZE_MISMATCH` 说明请求和实际尺寸。对旧开发版的暂存候选，恢复会重验文件后登记。详见 [MANUAL](../MANUAL.md)。

`close_task` 需要当前状态、结案原因及用户确认。结案释放队列名额并结束常规恢复。远程操作继续由供应商处理。已结案任务可用 `inspect_closed_artifact` 检查现存本地候选，再经确认调用 `export_closed_artifact`。该操作保持结案状态。旧版本只有 URL 响应证据时，工具标为 `legacy_unverified`，由用户核对候选后决定是否导出。
