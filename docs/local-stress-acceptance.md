# 本地压力与限额验收记录

日期：2026-11-09。使用 Windows 本地 Python 3.12.14、SQLite 数据库及隔离临时目录；未访问真实供应商，也未产生付费请求。

命令：

```powershell
uv run --locked pytest -q -s tests/test_local_stress.py --basetemp=.cache/local-stress
```

测试接收 20 个任务，验证第 21 个新任务被拒绝、8 个并发同键请求复用既有任务。阻塞进程内 provider 替身使 6 个生成请求同时执行，期间连续查询 20 次历史，释放后验证 20 项全部完成且仅执行 20 次请求；同时验证日志文件轮转。材料化替身只生成数据库所需的合成图片元数据，不读取或生成真实图片文件。

一次独立运行结果：

| 项目 | 实测 |
| --- | ---: |
| 未完成任务 | 20 |
| 同时执行请求峰值 | 6 |
| 历史查询平均 / 最大 | 0.302 / 0.452 ms |
| pytest 进程峰值工作集 | 63,848,448 字节 |

进程峰值包括整个测试进程；数值因机器负载和运行环境变化，不是 SLA，不代表真实大图、供应商网络或三个 Host 的性能。测试使用临时目录，运行证据可在该次 pytest 输出及临时目录 `stress-result.json` 中查看，重跑会生成新的测量结果。

其他限额由独立测试覆盖：

- `tests/test_config.py::test_invalid_limits_fail_during_construction`：并发、容量和重试硬上限及无效配置。
- `tests/test_artifacts_storage.py::test_reference_limits_and_partial_cleanup` 与 `test_budget_enforces_reserve`：参考图和磁盘预算。
- `tests/test_artifact_output.py::test_limits_and_write_failure`：图片输出限制及写入故障。
- `tests/test_t8_star_provider.py::test_stream_counts_decompressed_bytes_and_sends_once`：响应解压后字节限额。
- `tests/test_bootstrap_io.py::test_file_rotation`：日志大小和备份数量。

大图场景下的进程峰值仍需在有代表性的真实图片负载上测量，不能从本次合成元数据测试推算。
