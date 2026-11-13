# Strata for fnOS

Strata 的飞牛原生第三方 FPK，由 **lufan** 适配与打包。应用中心负责安装、启停和运行设置，提供原版 Strata 聊天网页及 OpenAI 兼容接口。推理在 NAS 上执行。

适用于 x86-64 飞牛和该 Strata CUDA 13 引擎支持的 NVIDIA GPU。引擎声明的最低 NVIDIA 驱动为 580.65。模型权重需单独下载或导入。请按模型、量化和上下文准备内存、显存和存储空间。

## 安装与导入模型

1. 用飞牛管理员账号打开「应用中心 → 手动安装」，选择 `strata-fnos-1.0.fpk`。安装完成后启动 Strata，再点「打开」。
2. 在「选择模型」中选择模型来源。已有 GGUF 时，在飞牛「文件管理 → 应用文件 → strata-models → models」上传或复制文件，然后回 Strata 点「刷新文件」并选择模型。分片放在同一目录，选任一分片即可。也可在飞牛应用设置授权已有目录后，从该目录选择。没有模型时，可选择下载页内的 Qwen3.8 Flash Next 量化及 NAS 能访问的站点（Hugging Face 或 ModelScope）。
3. 首次可用默认 8K 上下文，点击「导入并加载」或「下载并加载」。启动页会显示下载体积、校验或导入状态，关闭页面后任务继续。已有模型时，新模型准备完成后加入模型库，点「切换到此模型」即可使用。遇到投影张量格式错误时，重新选择该 GGUF 并启用 BF16 兼容转换。转换结果写入 Strata 数据目录，保留原文件。
4. 页面显示「模型已就绪」后点「打开聊天」。首次打开聊天时，在管理页点「显示 API 密钥」，再到聊天端的「关于 → 设置 → API 密钥」粘贴，然后回到「聊天」。聊天端默认显示简体中文，也可在「关于」里更换语言。OpenAI 兼容 API 基址是 `http://<NAS地址>:18180/v1`，使用相同密钥。通过受信任的局域网访问。

如自动识别失败，且已确认 GGUF 对应页面支持的 Qwen3.8 Flash Next 量化，可手动选择该量化后重试。需要命令行诊断时，管理员可以在 NAS 上运行 `sudo /var/apps/ai-workstation/target/configure "/你的模型路径"`。如有正在运行的模型，命令执行后从应用中心重启 Strata。

覆盖升级时，飞牛使用 `ai-workstation` 识别同一应用。模型配置位于 `/var/apps/ai-workstation/etc/engines/strata/model.json`，推理日志位于 `/var/apps/ai-workstation/var/engines/strata/native/model.log`。

## 运行设置

在 Strata 启动页展开「运行设置」，调整联网搜索、上下文、KV 缓存和 MTP 等 13 项参数。设置按模型保存，保存时会重新加载当前模型。应用中心的运行设置入口也可用。如果编辑期间配置已变化，重新打开表单后再保存。

首次导入模型后可在运行设置启用联网搜索。启用后，普通 `POST /v1/chat/completions` 请求允许模型按需调用 `search_web`。查询词可能发送给 Bing、DuckDuckGo，或在搜索项目和仓库时发送给 GitHub 的公开仓库搜索接口。可通过 `"strata_mcp": false` 或 `"tool_choice": "none"` 关闭当前请求的 MCP 工具。

在启动页的「运行设置 → 搜索代理」可选择继承运行环境、直接连接，或指定 HTTP 代理。支持 `http://主机:端口` 和 `http://用户名:密码@主机:端口`。账号和密码里的特殊字符需进行 URL 编码。地址写入当前模型配置，页面会回显连接模式及已保存代理的协议、主机和端口。搜索代理仅用于联网搜索，模型下载沿用下载环境的网络配置。

## 从源码构建

用 Python 3.11 或更高版本运行以下命令。下载 Strata v0.2.13 中的 `strata-control-0.1.59.1-linux-x86_64.tar.gz` 和 `strata-engine-0.1.59-linux-x86_64-cuda-cuda13.tar.gz` 到当前目录。构建脚本会核对两个归档的 SHA-256。以下命令为 Linux x86-64 的飞牛系统 Python 3.11 准备网页搜索依赖。 [Strata v0.2.13 下载页](https://github.com/Niko1221/Strata/releases/tag/v0.2.13)

```sh
mkdir -p build
curl -fL https://codeload.github.com/ggml-org/llama.cpp/tar.gz/3cf03257f219afbe7334045ff7c6a06ac68c627d \
  -o build/llama.cpp-3cf0325.tar.gz
python -m pip --isolated install --index-url https://pypi.org/simple \
  --only-binary=:all: --no-deps --no-compile --require-hashes \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --platform manylinux_2_17_x86_64 --implementation cp --python-version 3.11 \
  --abi cp311 --target build/python -r requirements-search-linux-x86_64-cp311.txt
tar --exclude=python/bin -czf build/search-runtime.tar.gz -C build python
python build_fpk.py \
  --control strata-control-0.1.59.1-linux-x86_64.tar.gz \
  --engine strata-engine-0.1.59-linux-x86_64-cuda-cuda13.tar.gz \
  --search-runtime build/search-runtime.tar.gz \
  --llama-source build/llama.cpp-3cf0325.tar.gz
```

## 致谢与许可

上游 Strata 由 Niko1221 和 Strata 贡献者开发。安装包内的 `licenses/` 保留上游署名与许可，随附依赖的许可位于各自的目录。随包提供的 NVIDIA CUDA 运行库适用 NVIDIA 的许可条款。模型权重由用户单独取得，遵循各模型的许可证。 [Strata MIT 许可](https://github.com/Niko1221/Strata/blob/v0.2.13/LICENSE) · [NVIDIA CUDA 13.0 许可](https://docs.nvidia.com/cuda/archive/13.0.0/eula/index.html)
