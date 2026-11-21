# Strata for fnOS

**1.0.13 最终整理版** · 上游 Strata v0.2.16 · Control / CUDA 13 引擎 0.1.62

Strata 的飞牛原生第三方 FPK，由 **fan789** 适配与打包。应用中心负责安装、启停和运行设置，提供原版 Strata 聊天网页及 OpenAI 兼容接口。推理在 NAS 上执行。

适用于 x86-64 飞牛和该 Strata CUDA 13 引擎支持的 NVIDIA GPU。引擎声明的最低 NVIDIA 驱动为 580.65。模型权重需单独下载或导入。请按模型、量化和上下文准备内存、显存和存储空间。

## 安装与导入模型

1. 用飞牛管理员账号打开「应用中心 → 手动安装」，选择当前的 Strata FPK。安装完成后启动 Strata，再点「打开」。
2. 在模型管理页点「添加模型」并选择来源，首次使用时添加表单会自动显示。已有 GGUF 时，在飞牛「文件管理 → 应用文件 → strata-models → models」上传或复制文件，然后回 Strata 点「刷新文件」并选择模型。分片放在同一目录，选任一分片即可。也可在飞牛应用设置授权已有目录后，从该目录选择。没有模型时，可选择下载页内的 Qwen3.8 Flash Next 量化及 NAS 能访问的站点（Hugging Face 或 ModelScope）。
3. 首次可用默认 8K 上下文，点击「导入并加载」或「下载并加载」。启动页会显示下载体积、校验或导入状态，关闭页面后任务继续。已有模型时，新模型准备完成后加入模型库，点「切换到此模型」即可使用。遇到投影张量格式错误时，重新选择该 GGUF 并启用 BF16 兼容转换。转换结果写入 Strata 数据目录，保留原文件。
4. 页面显示「模型已就绪」后点「打开聊天」。首次打开聊天时，在管理页「API 工具」复制密钥，再到聊天端的「关于 → 设置 → API 密钥」粘贴，然后回到「聊天」。聊天端默认显示简体中文，也可在「关于」里更换语言。OpenAI 兼容 API 基址是 `http://<NAS地址>:18180/v1`，使用相同密钥。管理页「API 工具」可分别复制接口地址和密钥。通过受信任的局域网访问。

如自动识别失败，且已确认 GGUF 对应页面支持的 Qwen3.8 Flash Next 量化，可手动选择该量化后重试。需要命令行诊断时，管理员可以在 NAS 上运行 `sudo /var/apps/ai-workstation/target/configure "/你的模型路径"`。如有正在运行的模型，命令执行后从应用中心重启 Strata。

覆盖升级时，飞牛使用 `ai-workstation` 识别同一应用。模型配置位于 `/var/apps/ai-workstation/etc/engines/strata/model.json`，推理日志位于 `/var/apps/ai-workstation/var/engines/strata/native/model.log`。

## 运行设置

模型工作台首页并列显示模型库与准备任务，并展示当前模型、内存、显存和工具状态。模型支持搜索、筛选、网格和列表视图。界面会根据飞牛浮窗宽度调整排布，窄屏将导航移至顶部。聊天、监控和关于页使用相同的字体、配色与控件规范，支持深浅色主题。

在工作台导航中点「运行设置」，调整联网搜索、Shell 命令权限、上下文、KV 缓存和 MTP 等参数。设置按模型保存，按思考、资源、上下文和工具分类，也可直接搜索名称或说明。未保存的修改会显示数量，在工作台内切换页面时保留。保存实际变更时会重新加载当前模型；没有修改时不触发重载。应用中心保留基本运行设置入口，完整选项以工作台为准。如果编辑期间配置已变化，重新读取后再保存。

运行设置按用途分组，支持思考强度、思考 token 预算、默认输出上限、系统预留内存、GPU 编号、KV 按需增长及 MCP 轮数、超时和结果长度。未单独指定的项目显示「默认」标记。系统预留内存越大，专家可用内存越少；它不等于固定专家常驻预算。显存常驻 KV 支持关闭或 20,480、32,768、65,536 token，且不能超过上下文。KV 按需增长限单 GPU。

「日常聊天、长文档分析、代码与工具」预设只填入表单，点击保存才应用。每次设置保存并成功加载后保留前一份可用配置，可通过「恢复上次可用设置」回退。新配置启动失败时自动恢复原配置。内存、GPU 和工具状态由页面定时更新；「重新读取设置」会丢弃未保存的表单修改。专家缓存数量取自本次启动日志，并非实时命中率。

聊天页共享设置优先于启动默认值，客户端请求中明确指定的参数优先级最高。运行状态会列出影响思考和输出的共享值，避免将启动值误认为实际请求值。

「Shell 命令权限」默认关闭。开启后，启用 MCP 的聊天客户端可让模型以 Strata 应用账号执行 Bash 命令，访问该账号有权限读取和修改的文件并联网。可在常显目录面板中多选添加或移除候选目录，再选择默认位置。飞牛目录需先通过「应用设置 → 可访问的文件」授权，默认使用独立的 shell-workspace；工作目录不是文件访问沙箱。默认最长执行 45 秒，可设置为 1–90 秒，工具请求可以进一步缩短。工具返回退出码、标准输出与错误输出，每路最多返回 16000 字节。执行记录最多保留 100 条元数据，不记录原始命令和输出。关闭并保存后，后续命令会被拒绝。

首次导入模型后可在运行设置启用联网搜索。启用后，普通 `POST /v1/chat/completions` 请求允许模型按需调用 `search_web`。查询词可能发送给 Bing、DuckDuckGo，或在搜索项目和仓库时发送给 GitHub 的公开仓库搜索接口。可通过 `"strata_mcp": false` 或 `"tool_choice": "none"` 关闭当前请求的 MCP 工具。

在启动页的「运行设置 → 搜索代理」可选择继承运行环境、直接连接，或指定 HTTP 代理。支持 `http://主机:端口` 和 `http://用户名:密码@主机:端口`。账号和密码里的特殊字符需进行 URL 编码。地址写入当前模型配置，管理员页面会回显连接模式及完整代理地址（含地址中填写的凭据），请勿在截图中泄露。搜索代理仅用于联网搜索，模型下载沿用下载环境的网络配置。

## 隐私与权限

发布包不包含个人配置、API 密钥、代理凭据、聊天记录、模型权重或实机截图。联网搜索、模型下载和可选 Shell 的数据边界见 [PRIVACY.md](PRIVACY.md)。

## 从源码构建

用 Python 3.11 或更高版本运行以下命令。下载 Strata v0.2.16 中的 `strata-control-0.1.62-linux-x86_64.tar.gz` 和 `strata-engine-0.1.62-linux-x86_64-cuda-cuda13.tar.gz` 到当前目录。构建脚本会核对两个归档的 SHA-256。以下命令为 Linux x86-64 的飞牛系统 Python 3.11 准备网页搜索依赖。 [Strata v0.2.16 下载页](https://github.com/Niko1221/Strata/releases/tag/v0.2.16)

```sh
mkdir -p build
python -m pip --isolated install --index-url https://pypi.org/simple \
  --only-binary=:all: --no-deps --no-compile --require-hashes \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --platform manylinux_2_17_x86_64 --implementation cp --python-version 3.11 \
  --abi cp311 --target build/python -r requirements-search-linux-x86_64-cp311.txt
tar --exclude=python/bin -czf build/search-runtime.tar.gz -C build python
python build_fpk.py \
  --control strata-control-0.1.62-linux-x86_64.tar.gz \
  --engine strata-engine-0.1.62-linux-x86_64-cuda-cuda13.tar.gz \
  --search-runtime build/search-runtime.tar.gz
```

## 回归测试

使用 Linux Python 3.11 和上面安装的 MCP 依赖：

```sh
STRATA_CONTROL_ARCHIVE="$PWD/strata-control-0.1.62-linux-x86_64.tar.gz" \
PYTHONPATH="$PWD/build/python" \
python3.11 -B -m unittest test_strata_options test_strata_search_default -q
```

通用 Linux 上会跳过 1 项需要 fnOS 应用目录与 ACL 的测试；其他 17 项覆盖设置、Shell、迁移和联网搜索回复处理。

## 致谢与许可

上游 Strata 由 Niko1221 和 Strata 贡献者开发。安装包内的 `licenses/` 保留上游署名与许可，随附依赖的许可位于各自的目录。随包提供的 NVIDIA CUDA 运行库适用 NVIDIA 的许可条款。模型权重由用户单独取得，遵循各模型的许可证。 [Strata MIT 许可](https://github.com/Niko1221/Strata/blob/v0.2.16/LICENSE) · [NVIDIA CUDA 13.0 许可](https://docs.nvidia.com/cuda/archive/13.0.0/eula/index.html)
