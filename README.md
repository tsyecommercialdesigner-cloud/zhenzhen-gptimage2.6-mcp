# Zhenzhen GPT Image 2.6 MCP

本地 stdio MCP Server，为支持 MCP 的 Agent 提供电商图像生成、任务查询、本地保存和提示词模板。默认供应商为 t8-star；调用生成接口可能收费。GIF 原件保留动画，SVG 原件保留矢量内容；各格式的已验证范围见[手册](MANUAL.md)。

Windows 默认安装位置为 `D:\MCP\zhenzhen-gptimage2.6-mcp`。项目使用 Python 3.12.14 和 uv；准备有效凭据后，按[手册的初始化步骤](MANUAL.md#2-项目初始化)从 GitHub Release 中确认标签和提交后安装。工作树中的未提交实现不等同于已发布版本；请勿凭包版本号推测标签。

完整说明：[MANUAL.md](MANUAL.md)；发行入口：[GitHub Releases](https://github.com/tsyecommercialdesigner-cloud/zhenzhen-gptimage2.6-mcp/releases)。

当前工作树正在实现共享本地后台：同一数据目录可由多个 stdio 接入进程使用。此能力尚未完成发布版 Desktop 验收；v0.1.1 的目录锁行为仍以该版本手册和发布记录为准。
