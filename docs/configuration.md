# 本地配置

将项目根目录 `.env.example` 复制为 `.env`，设置 `ZHENZHEN_GPTIMAGEGEN_API_KEY`。
默认只读取配置目录内 `.env`；指定其他文件时须提供绝对路径，不搜索父目录。
非空 `.env` 值优先，其次为进程环境变量，最后为 Windows 用户级环境变量。
进程环境不会被修改，密钥不应提交、写入日志或任务数据。
环境变量在非 Windows 系统仅使用进程级来源。当前配置模块尚未接入 Server。

Chat Completions 的图片尺寸由供应商决定，不能指定宽高。Chat 请求中不应提供
`width` 或 `height`；保存结果的宽高以实际图片为准。需要指定尺寸时使用
Generations 或 Flux 格式。
