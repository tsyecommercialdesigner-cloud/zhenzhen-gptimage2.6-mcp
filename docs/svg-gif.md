# SVG 和 GIF

默认通过 t8-star `images` 通道生成。`generate_image` 的 `request` 新增
`output_format`（`svg` 或 `gif`）、`size`（`auto` 或比例）、GIF 的
`frame_count`、`frame_duration_ms` 和 `size_policy`，以及 SVG 的
`svg_model`、`svg_reasoning_effort`。像素尺寸也可用 `width`、`height`，
或 `size: "1024x1024"`；不得同时传两种尺寸形式。省略尺寸时使用 `auto`。
新格式只接受文本，不接受参考图、蒙版或标注层。SVG 默认绘制模型为 `gpt-6-luna`。
SVG 暂只允许基础型号 `gpt-image-2.6-flare`；其他型号请求会在提交前拒绝。
比例尺寸映射到供应商的 `aspect_ratio`；`auto` 时省略尺寸字段，像素尺寸
通过可选的 `size` 发送。供应商可能将 `size` 转换为比例，实际尺寸以返回结果为准。

GIF 在原件落盘时保留动画；工具显示的 JPEG 是静态首帧，并有提示。
SVG 原件必须通过安全校验；由于不在 Host 中执行 SVG，预览可能不可用。
查询返回路径、SHA-256、实际尺寸和 GIF 帧时长、循环信息。

精确尺寸或比例不符时，GIF 默认保存待确认原件、返回 `recovery_pending`
和实际尺寸；检查结果后，可使用 `accept_gif_size` 提交 `task_id`、原件
`sha256`、实际 `width` 和 `height`。该操作只处理本地数据，不重发生成。
也可在首次请求显式设置 `size_policy: "accept_actual"`，有差异时直接返回
实际尺寸及警告。同一幂等键不得用于不同格式、供应商或尺寸策略。

目前已实测 t8-star flare 的一个 SVG 组合及一个 GIF 组合，其余组合的
供应商支持仍需验证。本项目仅使用 t8-star，不接入其他供应商。

对于基础 Flare 的 GIF，`execution_mode: "async"` 可提交供应商异步任务；
工具立即返回本地任务信息，使用 `get_task` 查询，远程 ID 和状态在取得后显示。
默认仍为 `sync`；其他组合的异步请求会在提交前拒绝。远程任务 ID 已保存时，
服务重启后在原期限内继续查询；本地期限超时后可对 `unknown` 任务调用
`recover_task` 查询同一远程 ID，不会重新生成。提交结果未知且没有远程 ID 时
不能自动重发，可能继续占用并发容量，需要人工核实。
