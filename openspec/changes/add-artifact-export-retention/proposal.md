# Proposal

## Why

Cowork 无法直接读取未挂载的 MCP 原件路径，导致 Agent 难以归档图片；运行数据长期累积也会占用大量磁盘。

## What Changes

- 提供将已登记的图片原件导出至指定工作区目录的工具，支持完整字节校验和 Cowork 实际验收。
- 提供按日期或保留数量筛选的清理预览和用户明确授权后的执行，保留历史和恢复必需数据。
- 提供明确启用、默认关闭的超过 90 天产物自动清理，后台运行时执行；支持查询及关闭。
- 不清理导出副本、未完成或待恢复任务，当前不实现视频支持。

## Capabilities

### New Capabilities

- `artifact-export`: 将托管原件安全导出至本地指定目录。
- `artifact-retention`: 产物清理预览、授权、执行及可选保留策略。

### Modified Capabilities

- `image-results`: 明确用户授权的清理例外和清理后的历史查询行为。

## Impact

影响 MCP 工具、共享后台、SQLite 产物元数据、文件存储、配置与成员手册；需验证三种 Host，尤其是 Cowork 路径映射及工作区显示。无需供应商生图或新增视频能力。
