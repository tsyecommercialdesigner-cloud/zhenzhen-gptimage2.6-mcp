# t8-star 异步验证矩阵（2026-11-10）

用户授权本轮最多 12 次收费生成请求。以下均仅提交一次，采用用户级或项目配置中既有 t8-star 密钥，密钥未记录。`images` 和 `flux` 均调用 `/v1/images/generations?async=true`；Chat 调用 `/v1/chat/completions?async=true`。只读查询使用 `/v1/images/tasks/{task_id}`。已记录 12 个提交开始事件，其中 Sunburst GIF 在脚本异常时处于发送窗口，是否送达未知；实际账单未核对。

| 请求组合 | 提交及最终结果 | 验证边界 |
| --- | --- | --- |
| Flare，PNG，1024×1024 | 返回任务 ID，SUCCESS，PNG 1024×1024 | 异步端到端成功 |
| Flare 2K，PNG，1536×1024 | 返回任务 ID，FAILURE，原因 `10k pool upstream unavailable` | 查询协议可用；生成结果未成功，不能判定不支持 |
| Flare 4K，PNG，3840×2160 | 返回任务 ID，SUCCESS，PNG 3840×2160 | 请求按项目 4K 路由使用基础 Flare 模型名及 4K 尺寸；不能声称直接发送 `-4k` 型号已成功 |
| Sunburst，PNG，1024×1024 | 返回任务 ID，SUCCESS，PNG 1024×1024 | 异步端到端成功 |
| Sunburst 2K，PNG，1536×1024 | 返回任务 ID，SUCCESS，PNG 1536×1024 | 异步端到端成功 |
| Sunburst 4K，PNG，3840×2160 | HTTP 503，无任务 ID | 提交结果不明，未重试，不能判定不支持 |
| Flare，SVG，1024×1024 | 返回任务 ID，SUCCESS，SVG 1024×1024 | 发送 `svg.model=gpt-6-luna`，原件通过本地安全校验 |
| Sunburst，SVG，1024×1024 | 返回任务 ID，FAILURE；上游提示缺 SVG 绘制模型 | 请求已包含 `svg.model=gpt-6-luna`；原因待供应商核实，不证明不支持 |
| Flare，JPEG，Flux 形态 | 返回任务 ID，SUCCESS，JPEG 1024×1024 | 与 Generations 使用同一路径，非独立接口 |
| Flare，WebP，1024×1024 | 返回任务 ID，SUCCESS，WebP 1024×1024 | 原件格式验证通过 |
| Sunburst，GIF，512×512 | 脚本在提交窗口中断，无已记录响应或任务 ID | 结果未知，未重试 |
| Flare，Chat | HTTP 200 返回普通 `chat.completion`，包含图片 Markdown，无任务 ID | `?async=true` 未返回可查询异步任务；可能被忽略，不证明 Chat 支持异步 |

此前另一次单独授权的 Flare GIF 异步测试返回任务 ID，SUCCESS，得到 9 帧 GIF；见 [实施验证记录](implementation-validation.md)。

测试脚本首次因缺少可选 XML 库而中断；其余已有任务 ID 均只读恢复查询。JPEG 首次结果检查碰到读取帧数字段错误，随后仅查询同一任务并重新下载，未重新生成。脱敏账本和结果文件位于 `.cache/t8-async-matrix-20261110/`，不会提交到 Git。

结论：多个 Generations 组合支持异步，但并非全部组合均已证明；Chat 未取得异步任务，两个模型组合失败或不明。暂不能全局改为异步优先。对已验证组合可设计异步策略，但必须先实现远程 ID 持久化、未知提交处理及重启恢复，并保守控制远程并发。

## 失败项重试（2026-11-10）

用户要求重试失败提交。对已确认 `FAILURE` 的两项各提交一次；Sunburst 4K 上次 HTTP 503 无任务 ID，用户在知悉可能重复生成及收费后另行明确授权重试一次。合计新增 3 次提交，实际账单未核对。

- Flare 2K PNG：任务 `c515e672161049c78708be5766e84ef2` 从 `NOT_START` 到 `SUCCESS`；原件 PNG 1536×1024，1480298 字节，SHA-256 `cf0103040af1590831e00d76cf5e74c145864ddd2cfd404ac89619ecca29bb18`。现已验证该模型及组合异步生成成功。
- Sunburst SVG：任务 `192d3c858a1f4fb38387df2e0cf650f7` 再次 `FAILURE`；供应商仍提示需要 SVG 绘制模型，尽管请求包含 `svg.model=gpt-6-luna`。不能据此确定该模型不支持异步或 SVG。
- Sunburst 4K PNG：再次 HTTP 503，无任务 ID，结果未知；未进一步重试。
- 原 Sunburst GIF 提交处于中断窗口、是否送达未知；本轮未重试。

脱敏账本及 PNG 原件分别位于 `.cache/t8-async-failed-retry-20261110/` 和 `.cache/t8-async-4k-retry-20261110/`。

同步对照：相同 Sunburst、SVG 绘制模型和尺寸通过无 `async` 参数的 Generations 接口提交一次，同样 HTTP 400 提示缺绘制模型。详见 [SVG 验证](t8star-svg-validation.md)；这排除了仅在本次异步路径出现该错误的判断，但不能确定上游根因。
