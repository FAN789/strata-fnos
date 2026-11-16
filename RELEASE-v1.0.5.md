Strata 1.0.5 是适用于飞牛 fnOS（x86-64）的本地模型推理应用。

- 同步上游 Strata v0.2.14，内置 Linux Control 0.1.60.1 和 NVIDIA CUDA 13 引擎 0.1.60。新版引擎在 NVIDIA 上使用 Strata 自有内核处理输入。
- 明确要求联网搜索时，服务端先执行搜索。搜索关闭、不可用或没有结果时直接显示对应状态。修复网页聊天与流式 API 的正文或思考内容出现原始工具调用标签的问题。
- 已在飞牛实机使用 RTX 3080 20 GB 从 1.0.4 覆盖升级。6 个配置文件、6 个 GGUF 文件路径通过保留校验，原模型和 262,144 tokens 上下文正常加载。网页聊天和流式 API 的普通对话与联网搜索均通过。

下载 `strata-fnos-1.0.5.fpk` 和同名 `.sha256` 文件。在下载目录运行 `sha256sum -c strata-fnos-1.0.5.fpk.sha256`，然后在飞牛应用中心选择「手动安装」并上传 FPK。已安装 1.0.4 的设备可覆盖升级。

[上游 Strata v0.2.14 发行说明](https://github.com/Niko1221/Strata/releases/tag/v0.2.14)
