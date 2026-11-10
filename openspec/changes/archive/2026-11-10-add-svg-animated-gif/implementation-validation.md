# 实施验证记录（2026-11-10）

- Codex Desktop 重启后，验证 MCP 的 `get_capabilities` 显示新版 SVG/GIF 能力；`get_task` 查询真实 GIF 任务 `3332e0f6-cf49-4acf-8106-407ff6fc36ff` 为 `succeeded`、尝试数 1，并返回存在的原件路径、16 帧与时长元数据。直接通过当前 Codex Host 调用 `get_image` 成功返回 `ImageContent`（JPEG 静态首帧）、原件路径、摘要及“静态首帧、原文件保留动画”警告，预览在工具结果中可见；未声称 GIF 在 Host 中动态播放，也未验证 SVG 在 Host 中渲染。验收没有新的生成请求。
- 依据用户授权临时切换项目 `.codex/config.toml` 的验证数据目录，事先备份并记录摘要。重启后配置中新增 `get_task` 与 `get_image` 的工具审批设置；恢复时只将数据目录改回原值，保留这些新增设置。运行中的 MCP 进程仍使用临时数据目录，下一次重启后读取已恢复的目录。

- 本轮按用户要求通过独立真实 stdio MCP 提交一次 Flare GIF，精确请求 768×512；供应商返回 378×260 GIF、16 帧、每帧 100 ms、loop=0。MCP 将原件写盘并进入 `recovery_pending`，可用 `accept_gif_size` 显式接受，接受后 `succeeded` 且生成 `attempt_count=1`，没有重复提交。文件 `.cache/gif-mismatch-live-20261110/images/3332e0f6-cf49-4acf-8106-407ff6fc36ff.0.gif`，115510 字节，SHA-256 `2b6beaaabf9a47b05fae9795958a3e0b4be46c8ef440f7373744e9324a87a65b`；脱敏账本 `.cache/gif-mismatch-live-20261110/attempts.jsonl`。本轮发送 1 次生成请求，账单尚未核对。结合此前真实 SVG、GIF 证据，完成任务 5.2。
- 额外使用先前供应商返回的 816×816 GIF 原字节，以本地 HTTP 替身回放请求 512×512：当前 MCP 保存原件进入待确认，确认后成功、尝试数 1、实际供应商提交数 0，字节摘要与原件一致。该回放是补充本地验证，不作为新一次真实调用证据。

- 已接通基础 Flare GIF 的显式异步提交、事务化远程 ID 和状态、本地查询、进程启动恢复及结果落盘；未确认远程终态时保守保留并发容量。完整回归 **179 项通过**，随后新增持久化 ID 后重开数据库并恢复查询测试，相关专项 **6 项通过**；OpenSpec 严格校验通过。使用此前真实 GIF 任务 ID 通过新适配器只读查询得到 `SUCCESS` 和一个图片来源，无新增生成或收费请求。异步新代码尚未用新的真实生成任务端到端验收，离线替身和只读查询不代表真实提交及中断恢复已验收。
- SVG 暂限定路由至 `gpt-image-2.6-flare` 基础型号，其他型号提交前拒绝，不自动切换。用户提供的 Sunburst 失败证据见 [SVG 验证](t8star-svg-validation.md)。

- 按用户要求重试失败项并在用户明确接受未知结果风险后重试 Sunburst 4K，新增 3 次提交：Flare 2K PNG 异步成功；Sunburst SVG 再次报告缺 SVG 绘制模型；Sunburst 4K 再次 503 且无任务 ID。详细证据见 [异步验证矩阵](t8star-async-matrix-20261110.md)。

- 本轮获授权最多 12 次生成请求，扩展测试不同型号、PNG/JPEG/WebP/SVG/GIF 和 Chat。多个 Generations 组合成功；Chat 返回普通同步响应，无任务 ID，另有供应商失败及未知提交。各组合、恢复过程和证据边界见 [异步验证矩阵](t8star-async-matrix-20261110.md)。因此未将全局默认切换为异步。

- 历史阶段：异步适配最初只实现受限执行模式、旧摘要兼容、提交/查询解析及远程 ID 事务写入基础，当时尚未接通调度和重启恢复。该阶段完整回归 173 项通过；之后新增的数据库事务与异步协议专项共 15 项通过。后续实施状态见本记录开头。

- 用户另行授权最多 1 次 GIF 异步测试：对 `https://ai.t8star.org/v1/images/generations?async=true` 提交 `gpt-image-2.6-flare`、`output_format=gif`、`size=512x512`，仅提交一次，HTTP 200 返回顶层 `task_id` 为 `eb46df9af3684ef88a9dd7b13494d269`。只读查询 `/v1/images/tasks/{task_id}` 观察到 `NOT_START` 后 `SUCCESS`；下载原始文件确认 GIF 512×512、9 帧、每帧 200 ms、loop=0、186121 字节，SHA-256 `3af3ec8c41031f873033589d12f56a24828710dd7819ac36c11abdcabf08addf`。证据位于 `.cache/t8-async-gif-20261110/ledger.json` 及 `result.gif`；实际账单未核对。此结果证明该模型与该 GIF 请求组合的异步提交、查询和动画结果，不证明其他模型、SVG 或当前 MCP 已支持异步调用。

- 根据用户最新决定取消可选异步适配和远程 ID 恢复；移除其密钥配置及请求选项，保留已应用的 SQLite v2 扩展表和迁移校验，避免破坏已有数据库。新增格式的 `auto` 不发送尺寸字段，比例映射到 `aspect_ratio`，像素值仍以 `size` 发送；这些新映射通过离线测试，尚未通过新的真实供应商请求验证。
- 本次更改在既有干净锁定环境中回归：**168 passed，2 warnings**，并有 pytest-asyncio 默认作用域弃用提示。首次运行因系统临时目录拒绝访问失败，改用项目内测试临时目录后通过。

- 使用全新 `.cache/svg-final-clean3` 运行 `uv sync --locked` 和全套测试：**170 passed，2 warnings**；汇总的两条警告来自 Authlib 弃用，pytest 启动时另有 asyncio fixture 默认作用域弃用提示。
- `openspec validate --specs` 六项通过，`openspec validate add-svg-animated-gif --strict` 通过，`git diff --check` 通过。PNG/JPEG/WebP、原接口、SQLite 迁移和旧快照由相关离线测试覆盖。
- 本轮 1 次真实 SVG MCP 生成先因无障碍属性被安全白名单拒绝，修复后对原任务本地恢复成功，没有再次生成；详细证据见 [t8-star 验证](t8star-svg-validation.md)。这是恢复后的成功，并非首次立即成功。
- 用户授权本轮 1 次真实 MCP GIF 请求：`gpt-image-2.6-flare` 请求 512×512，任务 `7ee47288-c761-403e-aa35-f09238df29a6` 一次生成即 `succeeded`，原件 `.cache/gif-live-mcp-20261110/images/7ee47288-c761-403e-aa35-f09238df29a6.0.gif`，实际 512×512，9 帧，每帧 200 ms，loop=0，190940 字节，SHA-256 `f1bc3366939edbecacb87087fd0b02a970985f301bbedc3d4e15c68778d167d0`。真实 GIF 此次尺寸一致，未触发尺寸不符分支；该分支的待确认、拒绝篡改、显式接受及无重复提交通过离线替身测试，不能视为真实供应商触发验收。实际账单未核对。
- 可选 `api.seedance.nz` 提交/查询和带远程 ID 的崩溃恢复尚未实现或验收；用户未订阅该服务，当前不会向该端点发送密钥或请求。
- 使用当前 OpenAI 登录的 Codex CLI 0.163.0 对新 MCP 的 `get_image` 做 Host 验收，CLI 已发现 `gifcheck.get_image`，但自动审批拦截该工具调用：工具需要审批，而该运行环境审批策略为 `never`。没有返回 Host 结果；不能证明预览或文件定位。Codex Desktop 对新版本的会话内展示也未验收；旧 MCP 进程需要重启后才会加载新代码。
