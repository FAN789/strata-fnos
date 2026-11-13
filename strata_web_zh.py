"""Extend the pinned Strata web client's translation catalog for fnOS."""

from html import unescape
import json
import re


STATIC = {
    "Make an image": "生成图片",
    "Describe the image…": "描述你想生成的图片…",
    "Prompt": "提示词",
    "Size": "尺寸",
    "Seed": "随机种子",
    "random": "随机",
    "Generate": "生成",
    "One image at a time; a chat request waits for it (and the other way round).": "每次生成一张图片。图片生成与聊天请求依次处理。",
    "Model state": "模型状态",
    "Idle": "空闲",
    "Unloaded": "未加载",
    "Reading": "读取提示词",
    "Generating": "生成中",
    "Queued": "排队中",
    "Error": "错误",
    "Waiting for a request": "等待请求",
    "Context fill": "上下文占用",
    "Experts in VRAM": "显存中的专家",
    "System RAM": "系统内存",
    "GPU temperature": "GPU 温度",
    "Recent requests": "最近请求",
    "Show all": "显示全部",
    "Time": "时间",
    "Status": "状态",
    "Reused": "复用",
    "Output": "输出",
    "Prefill t/s": "预填充（tok/s）",
    "Decode t/s": "解码（tok/s）",
    "VRAM hit rate": "显存命中率",
    "Duration": "耗时",
    "New prompt tokens per second, excluding reused cache tokens (engine prompt time)": "每秒处理的新提示 token 数，扣除从缓存复用的 token。",
    "While writing the answer: the share of the experts looked up that were already in VRAM. Experts the GPU read over PCIe (--pcie-frac) are not counted in it; their share of all routed experts is shown after it (+N% PCIe)": "生成回复时已在显存中的专家占比。经 PCIe 读取的专家另计。",
    "No requests yet": "暂无请求",
    "Conversation cache": "会话缓存",
    "Parked conversations": "暂存的会话",
    "Their memory (RAM)": "占用内存",
    "MCP servers": "MCP 服务",
    "Their tools run on this PC with your rights, when the model decides to call them (in this page's chat only; switch it off in Sampling).": "模型需要时会在本机调用 MCP 工具。可在聊天设置中关闭此功能。",
    "Model and engine": "模型与引擎",
    "This PC": "本机硬件",
    "Connect your tools": "连接其他客户端",
    "Any OpenAI- or Anthropic-compatible client works with these addresses.": "支持 OpenAI 或 Anthropic 接口的客户端可使用以下地址。",
    "Settings": "设置",
    "API key": "API 密钥",
    "only if the server was started with one": "服务端启用了密钥时填写",
    "Not needed": "按需填写",
    "Dark theme": "深色主题",
    "Chats, settings and the key are kept in this browser only.": "聊天记录、设置和密钥仅保存在此浏览器中。",
    "Strata on GitHub": "在 GitHub 查看 Strata",
    "Model settings": "模型设置",
    "Kept in the model's run config for every client. An empty field is the default. They take effect the next time the model starts (close Strata's window and start it again).": "设置保存在模型配置中，对所有客户端生效。留空使用默认值，重启模型后生效。",
    "Save": "保存",
    "Attach a text file (or drop it here)": "添加文本文件，也可拖到此处",
    "Strata API Monitor": "Strata API 监控",
    "Local inference": "本地推理",
    "Switch color theme": "切换配色主题",
    "Light / dark": "浅色 / 深色",
    "API Monitor": "API 监控",
    "Model status and every request, in one place.": "查看模型状态和 API 请求。",
    "Load model": "加载模型",
    "Unload model": "卸载模型",
    "Only needed if the server has a key": "服务端启用了密钥时填写",
    "Connect": "连接",
    "Model": "模型",
    "Connecting…": "正在连接…",
    "Requests retained": "保留的请求",
    "Waiting for server": "等待服务器响应",
    "Last wall-clock": "上次请求总耗时",
    "Includes queue and model loading": "包含排队和模型加载时间",
    "Average decode speed": "平均解码速度",
    "Run average · tokens / second": "运行平均值 · tok/s",
    "Tool image": "工具生成的图片",
    "Download image": "下载图片",
    "Requests": "请求",
    "Filter requests": "筛选请求",
    "Search ID or endpoint": "搜索请求 ID 或接口",
    "Request status": "请求状态",
    "All statuses": "全部状态",
    "Active": "处理中",
    "Completed": "已完成",
    "Errors": "错误",
    "Request list": "请求列表",
    "Inspect a request": "查看请求",
    "Select a request to see its input, output, and timings.": "选择请求以查看输入、输出和耗时。",
    "Wall-clock": "总耗时",
    "Model load": "模型加载",
    "Queue wait": "排队等待",
    "First token": "首个 token",
    "Prompt tokens": "提示 token 数",
    "Output tokens": "输出 token 数",
    "Decode speed": "解码速度",
    "Response format": "响应格式",
    "Request content": "请求内容",
    "Input": "输入",
    "Reasoning": "推理过程",
    "API response": "API 响应",
    "Copy": "复制",
    "Last 100 requests kept in memory until restart. Inputs and outputs stay on this machine.": "最近 100 条请求保存在内存中，重启后清除。输入和输出保留在本机。",
}

DYNAMIC = {
    "Speed": "速度", "GPU load": "GPU 利用率", "VRAM": "显存", "GPU temp": "GPU 温度",
    "Power": "功耗", "Disk read": "磁盘读取", "Decode": "解码", "Prefill": "预填充",
    "just now": "刚刚", "Loading": "正在加载", "Unloading": "正在卸载",
    "The model is loading.": "正在加载模型。", "Generating image": "正在生成图片",
    "An image is generating. It finishes on its own.": "正在生成图片，完成后会自动显示。",
    "Freeing the GPU.": "正在释放显存。", "Reading prompt": "正在读取提示词",
    "Load brings it back. A message does too.": "点击加载或发送消息即可重新加载。",
    "Decode now": "实时解码", "Decode · run average": "解码 · 运行平均值",
    "Decode last request": "解码 · 上次请求", "Prefill now": "实时预填充",
    "Prefill this request": "预填充 · 本次请求", "Prefill · run average": "预填充 · 运行平均值",
    "Prefill last request": "预填充 · 上次请求", "not available": "不可用",
    "not available on Windows AMD yet": "Windows 上的 AMD 显卡暂不支持此项",
    "needs psutil (setup installs it)": "需安装 psutil",
    "Done": "完成", "Max tokens": "达到 token 上限", "Stopped": "已停止", "Closed": "已断开", "Timeout": "超时",
    "Show fewer": "收起", "stock": "标准",
    "8-bit": "8 位", "4-bit (Hadamard-rotated)": "4 位（Hadamard 旋转）", "16-bit": "16 位",
    "Engine": "引擎", "built from source": "从源码构建", "Context": "上下文", "KV cache": "KV 缓存",
    "Speculation": "推测解码", "Images": "图像", "Experimental speed projection": "实验性速度投影",
    "not readable (NVML)": "无法通过 NVML 读取", "OpenAI base URL": "OpenAI 接口地址",
    "Anthropic base URL": "Anthropic 接口地址", "Model name": "模型名称",
    "Connected": "已连接", "Starting": "正在启动", "Failed": "失败", "Waiting": "等待中",
    "no server is connected yet (see the Monitor)": "暂无已连接的服务，可在监控页查看",
    "Last request": "上次请求", "Reused since start": "启动后累计复用", "Parked / restored": "暂存 / 恢复",
    "Last switch": "上次切换",
    "A request that continues a parked conversation gets its state back instead of reading it again; the oldest goes when the slots or the memory are full.": "继续暂存的会话时，系统会恢复其状态。槽位或内存用满时，最早暂存的会话会被移出。",
    'The engine keeps the last conversation\'s state, so a follow-up reads only what is new. To keep several conversations (agents taking turns), add \\"--conversation-cache-mib\\", \\"8192\\" to the run config\'s args (docs/DETAILS.md).': "引擎会保留上一次会话的状态，后续请求只处理新增内容。可在飞牛运行设置中配置多会话缓存。",
    "Nothing changed.": "没有改动。", "Not saved": "未保存", "Image unavailable": "无法读取图片", "Writing": "正在撰写",
    "Done. Right-click an image to save it.": "已完成。右键单击图片即可保存。", "No image": "图片生成失败",
    "No matching requests.": "没有符合条件的请求。", "No requests yet. API calls will appear here automatically.": "暂无请求。API 调用会自动显示在这里。",
    "stream": "流式响应", "JSON response": "JSON 响应",
    "Streaming response: see Output and the request error, if any.": "流式响应请查看「输出」以及请求错误（如有）。",
    "No content.": "暂无内容。", "Raw model output retained for diagnosis. The API returned an error.": "API 返回错误，已保留模型原始输出供排查。",
    "Original request body.": "原始请求体。", "Model answer. JSON is formatted here for readability.": "模型回复。JSON 已格式化以便阅读。",
    "Separate reasoning content, when enabled.": "启用推理时单独显示的推理内容。", "API response body.": "API 响应体。",
    " Monitor capture truncated at 256K characters; the API response was not shortened.": "监控记录最多保留 256K 字符，API 响应仍为完整内容。",
    "Loading…": "正在加载…", "In use": "使用中", "Loaded": "已加载",
    "Loads automatically on the next request": "收到下一个请求时自动加载", "No active requests": "暂无正在处理的请求",
    "Disconnected · retrying": "已断开，正在重试", "Unloading…": "正在卸载…", "Copied": "已复制",
    "Clipboard unavailable; select the text to copy it.": "无法访问剪贴板，请选中文本后复制。",
    "routed experts the GPU read over PCIe (--pcie-frac) or another GPU computed": "通过 PCIe 读取或由其他 GPU 计算的专家比例",
    "t/s": "tok/s",
    "Image unavailable; try refreshing": "图片无法加载，请刷新后重试",
}

REQUEST_STATES = {"queued": "排队中", "loading": "正在加载", "reading": "读取提示词", "generating": "生成中",
                  "completed": "已完成", "error": "错误", "disconnected": "已断开", "running": "处理中",
                  "thinking": "思考中", "answering": "回答中", "prefill": "预填充", "decode": "解码"}

CONFIG_LABELS = {
    "sampling.temperature": "默认温度（0 为贪心采样，留空使用模型默认值）",
    "sampling.top_p": "默认 Top-p（大于 0，且不超过 1）",
    "sampling.top_k": "默认 Top-k（1 至 64）",
    "sampling.min_p": "默认 Min-p（0 至 1）",
    "reasoning_budget_tokens": "思考 token 上限（0 或留空表示不限）",
    "fit_max_tokens": "输出超出上下文时自动缩短。关闭后返回 HTTP 400。",
    "anthropic_thinking": "Anthropic 请求未指定思考时的默认行为",
    "effort_position": "非默认推理强度的插入位置。放在末尾可保留已有缓存。",
    "aliases": "模型别名，用逗号分隔",
    "idle_unload_s": "空闲多少秒后卸载模型（0 或留空表示始终加载）",
    "mtp": "MTP 草稿层。关闭可降低显存占用，留空或开启时使用安装配置。",
    "lazy_load": "首次请求时才加载模型（仅适用于纯文本模型）",
    "engine_silence_s": "引擎无响应超时（秒，默认 300，0 表示一直等待）",
    "api_monitor": "在 API 监控中保留最近 100 条请求的提示词和回复",
    "open_browser": "模型就绪后自动打开浏览器",
    "vram_reserve_mib": "为其他程序保留的显存（MiB，引擎默认 700）",
}

# Keep English fallbacks next to the generated labels. Other language choices continue
# to use the upstream catalogs. Only UI strings are translated, never request data.
STRINGS = STATIC | DYNAMIC | {"on": "开启", "off": "关闭", "default": "默认",
                              "model": "按模型默认行为", "on_request": "仅在请求指定时思考",
                              "start": "开头", "end": "末尾", "text": "文本",
                              "json_object": "JSON 对象", "json_schema": "JSON 结构定义"}


def key(text):
    return "fnos." + text


def js_string(value):
    return json.dumps(value, ensure_ascii=False)


def translate_literals(source, strings):
    literal = re.compile(r'"(?:\\.|[^"\\\n])*"')

    def replace(match):
        try:
            value = json.loads(match[0])
        except ValueError:
            return match[0]
        if value not in strings:
            return match[0]
        return f"fnText({match[0]})"

    return literal.sub(replace, source)


def mark_html(source):
    def mark_text(match):
        tag, attrs, raw = match.groups()
        label = " ".join(unescape(raw).split())
        if "data-i18n=" in attrs or label not in STATIC:
            return match[0]
        return f'<{tag}{attrs} data-i18n="{key(label).replace(chr(34), "&quot;")}">{raw}</{tag}>'

    source = re.sub(r"<(title|span|label|div|button|p|strong|h1|h2|th|td|option|output|a)(\b[^<>]*)>([^<>]+)</\1>", mark_text, source)

    def mark_attrs(match):
        tag = match[0]
        for attr, suffix in (("placeholder", "placeholder"), ("aria-label", "label"), ("title", "title")):
            value = re.search(fr'(?<![\w-]){attr}="([^"]+)"', tag)
            if value and f"data-i18n-{suffix}=" not in tag and unescape(value[1]) in STATIC:
                label = key(unescape(value[1])).replace('"', "&quot;")
                tag = tag[:-1] + f' data-i18n-{suffix}="{label}">'
        return tag

    return re.sub(r"<[a-z][\w-]*(?:\s[^<>]*)?>", mark_attrs, source)


def span(text):
    return f'<span data-i18n="{key(text)}">{text}</span>'


def patch_web(name, payload):
    source = payload.decode("utf-8")
    if name == "locales/zh.json":
        data = json.loads(source)
        data["settings.languageNote"] = "选择网页界面使用的语言。"
        data["chat.emptyModel"] = "{model} 正在本机运行。"
        data["chat.tokens"] = "{n} tokens"
        data["pill.generating"] = "生成中 · {rate} tok/s"
        data["drawer.maxTokens"] = "最大 token 数"
        data.update({key(en): zh for en, zh in STRINGS.items()})
        data.update({f"fnos.state.{code}": label for code, label in REQUEST_STATES.items()})
        data.update({f"fnos.config.{code}": label for code, label in CONFIG_LABELS.items()})
        data.update({f"fnos.{k}": zh for k, (_, zh) in TEMPLATES.items()})
        source = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    elif name in {"index.html", "monitor.html"}:
        for text, after in (("Size", "\n"), ("Seed", "\n"), ("API key", " <output>"),
                            ("Chats, settings and the key are kept in this browser only.", "\n"),
                            ("Select a request to see its input, output, and timings.", "</div>")):
            source = source.replace(f">{text}{after}", f">{span(text)}{after}")
        if name == "monitor.html":
            source = source.replace('<script defer src="/web/monitor.js">', '<script defer src="/web/i18n.js"></script>\n<script defer src="/web/monitor.js">')
        else:
            source = source.replace("Chat, its settings and the buttons above are translated. The Monitor, Images and About views are still in English.", "Choose the language for the web interface.")
        source = mark_html(source)
    elif name == "app.js":
        source = patch_chat(source)
    elif name == "monitor.js":
        source = patch_monitor(source)
    return source.encode("utf-8")


TEMPLATES = {
    "age.minutes": ("{count} min ago", "{count} 分钟前"),
    "age.hours": ("{count} h ago", "{count} 小时前"),
    "cache.summary": ("{reused} of {total} requests reused part of their prompt", "{total} 个请求中有 {reused} 个复用了部分提示词"),
    "cache.share": (" ({pct}% of all prompt tokens)", "（占提示 token 总数的 {pct}%）"),
    "cache.parked": ("Parked {count} tokens, {age}", "暂存了 {count} tokens，{age}"),
    "cache.restored": ("Restored {count} tokens, {age}", "恢复了 {count} tokens，{age}"),
    "cache.last": ("{reused} of {total} prompt tokens reused", "复用 {reused} / {total} 个提示 token"),
    "cache.tokens": ("{count} tokens", "{count} tokens"),
    "cache.evicted": (" · {count} evicted", " · 已移出 {count} 个"),
    "chat.rate": ("{rate} tok/s", "{rate} tok/s"),
    "monitor.rate": (" at {rate} tok/s", "，{rate} tok/s"),
    "monitor.totals": ("Since {since}: {requests} requests · {read} prompt tokens read{prefill} ({reused} reused) · {output} written{decode}", "自 {since} 起：{requests} 个请求 · 读取 {read} 个提示 token{prefill}（复用 {reused} 个）· 生成 {output} tokens{decode}"),
    "monitor.reading": ("{read} / {total} tokens · {pct}%", "{read} / {total} tokens · {pct}%"),
    "monitor.generating": ("{count} tokens · {rate} tok/s", "{count} tokens · {rate} tok/s"),
    "monitor.last": ("last: {count} tokens{rate}", "上次：{count} tokens{rate}"),
    "monitor.experts": ("{count} experts cached", "已缓存 {count} 个专家"),
    "monitor.limit": ("of {power} W limit", "功耗上限 {power} W"),
    "monitor.pcie": ("to GPU {rate} MB/s", "传入 GPU：{rate} MB/s"),
    "monitor.pcieIdle": (" · idle Gen{generation}", " · 空闲时 Gen{generation}"),
    "monitor.cores": ("{count} cores · ", "{count} 核 · "),
    "monitor.threads": ("{count} threads", "{count} 线程"),
    "monitor.write": ("write {rate} MB/s", "写入 {rate} MB/s"),
    "monitor.showAll": ("Show all ({count})", "显示全部（{count}）"),
    "monitor.duration": ("{seconds} s", "{seconds} 秒"),
    "monitor.projection": ("Experimental speed projection: {state}", "实验性速度投影：{state}"),
    "about.projection": ("Projection control vector on layers {first}–{last}", "对第 {first}–{last} 层应用投影控制向量"),
    "about.additive": ("Additive control vector on layers {first}–{last}", "对第 {first}–{last} 层应用加法控制向量"),
    "about.projectionSingle": (" (layer {layer}'s direction)", "（第 {layer} 层的方向）"),
    "about.projectionNote": (". Per chat in Sampling. Its package describes the vector as a refusal-direction projection; measure the speed yourself", "。可在聊天设置中单独调整。上游称其为拒绝方向投影，速度以实测为准。"),
    "about.kvStream": (", streamed: {count} positions per layer in VRAM, the rest in RAM", "，每层 {count} 个位置常驻显存，其余放在内存"),
    "about.kvResident": (", all in VRAM", "，全部常驻显存"),
    "about.spec": ("MTP drafts up to {count} tokens", "MTP 最多预生成 {count} tokens"),
    "about.lookup": (", prompt lookup on", "，已启用提示词查找"),
    "mcp.summary": ("{tools} tools · {ready} of {total} servers connected", "{tools} 个工具 · 已连接 {ready} / {total} 个服务"),
    "mcp.drawer": ("{tools} tools from {servers}; the model calls them when it decides to", "来自 {servers} 的 {tools} 个工具，模型按需调用"),
    "mcp.tools": ("{count} tools", "{count} 个工具"),
    "config.saved": ("Saved ({keys}); the earlier file is {file}.bak. Start the model again to use it.", "已保存（{keys}）。原文件备份为 {file}.bak，重启模型后生效。"),
    "image.working": ("Generating… (a minute or more on a small GPU)", "正在生成图片…低性能 GPU 可能需要一分钟以上"),
    "image.caption": ("{size}, seed {seed}, {seconds} s: {prompt}", "{size} · 种子 {seed} · {seconds} 秒 · {prompt}"),
    "api.request": ("Request {id}", "请求 {id}"),
    "api.active": ("{count} active / queued", "{count} 个请求正在处理或排队"),
    "api.updated": ("Live · updated {time}", "实时 · 更新于 {time}"),
}

CHAT_TEMPLATES = {
    '`${fmt(s / 60)} min ago`': ("age.minutes", "{count:fmt(s / 60)}"),
    '`${fmt(s / 3600, 1)} h ago`': ("age.hours", "{count:fmt(s / 3600, 1)}"),
    '`${fmt(c.requests_reused)} of ${fmt(c.requests)} requests reused part of their prompt`': ("cache.summary", "{reused:fmt(c.requests_reused),total:fmt(c.requests)}"),
    '` (${fmt((100 * c.reused_tokens) / c.prompt_tokens)}% of all prompt tokens)`': ("cache.share", "{pct:fmt(100 * c.reused_tokens / c.prompt_tokens)}"),
    '`${fmt(c.last_reused || 0)} of ${fmt(c.last_prompt)} prompt tokens reused`': ("cache.last", "{reused:fmt(c.last_reused || 0),total:fmt(c.last_prompt)}"),
    '` at ${fmt(read / (t.prompt_ms / 1000))} tok/s`': ("monitor.rate", "{rate:fmt(read / (t.prompt_ms / 1000))}"),
    '` at ${fmt(t.output_tokens / (t.decode_ms / 1000), 1)} tok/s`': ("monitor.rate", "{rate:fmt(t.output_tokens / (t.decode_ms / 1000), 1)}"),
    '`${fmt(live.prompt_read)} / ${fmt(live.prompt_total)} tokens · ${fmt(pct)}%`': ("monitor.reading", "{read:fmt(live.prompt_read),total:fmt(live.prompt_total),pct:fmt(pct)}"),
    '`${fmt(live.generated)} tokens · ${fmt(live.tok_s, 1)} tok/s`': ("monitor.generating", "{count:fmt(live.generated),rate:fmt(live.tok_s, 1)}"),
    '`${fmt(eng.expert_slots)} experts cached`': ("monitor.experts", "{count:fmt(eng.expert_slots)}"),
    '`of ${fmt(hw.gpu_power_limit)} W limit`': ("monitor.limit", "{power:fmt(hw.gpu_power_limit)}"),
    '`to GPU ${fmt(hw.gpu_pcie_rx_mb, hw.gpu_pcie_rx_mb < 10 ? 1 : 0)} MB/s`': ("monitor.pcie", "{rate:fmt(hw.gpu_pcie_rx_mb, hw.gpu_pcie_rx_mb < 10 ? 1 : 0)}"),
    '` · idle Gen${hw.gpu_pcie_gen}`': ("monitor.pcieIdle", "{generation:hw.gpu_pcie_gen}"),
    '`write ${fmt(hw.disk_write_mb, 1)} MB/s`': ("monitor.write", "{rate:fmt(hw.disk_write_mb, 1)}"),
    '`Show all (${kept})`': ("monitor.showAll", "{count:kept}"),
    '`, streamed: ${fmt(eng.kv_resident)} positions per layer in VRAM, the rest in RAM`': ("about.kvStream", "{count:fmt(eng.kv_resident)}"),
    '`${fmt(mcpInfo.tools)} tools · ${ready.length} of ${servers.length} servers connected`': ("mcp.summary", "{tools:fmt(mcpInfo.tools),ready:ready.length,total:servers.length}"),
    '`${fmt(mcpInfo.tools)} tools from ${ready.map((s) => s.name).join(", ")}; the model calls them when it decides to`': ("mcp.drawer", '{tools:fmt(mcpInfo.tools),servers:ready.map(s => s.name).join(", ")}'),
    '`Saved (${b.changed.join(", ")}); the earlier file is ${b.file}.bak. Start the model again to use it.`': ("config.saved", '{keys:b.changed.join(", "),file:b.file}'),
}


def call(name, values="{}"):
    return f"fnFormat({js_string(name)}, {js_string(TEMPLATES[name][0])}, {values})"


def literal(value):
    return f"fnText({js_string(value)})"


def patch_chat(source):
    helper = '''const fnText = (english) => tr("fnos." + english, english);
const fnFormat = (key, english, vars) => tr("fnos." + key, english, vars);
const fnState = (code, fallback) => tr("fnos.state." + code, fallback);
'''
    source = source.replace('"use strict";', '"use strict";\n' + helper, 1)
    start, end = source.index("function since("), source.index("// ------------------------------------------------------------------ Markdown")
    region = source[start:end]
    for old, (name, values) in CHAT_TEMPLATES.items():
        region = region.replace(old, call(name, values))
    cache_event = "{count:fmt(c.last_tokens),age:since(c.last_at)}"
    region = region.replace('`${c.last_event === "parked" ? "Parked" : "Restored"} ${fmt(c.last_tokens)} tokens, ${since(c.last_at)}`',
                            '(c.last_event === "parked" ? ' + call("cache.parked", cache_event) + " : " + call("cache.restored", cache_event) + ")")
    region = region.replace('` · ${fmt(c.evictions)} evicted`', call("cache.evicted", "{count:fmt(c.evictions)}"))
    for expr in ("live.prompt_tokens", "c.reused_tokens", "eng.max_context"):
        region = region.replace('`${fmt(' + expr + ')} tokens`', call("cache.tokens", "{count:fmt(" + expr + ")}"))
    region = region.replace('`${fmt(c.reused_tokens)} tokens${share}`', call("cache.tokens", "{count:fmt(c.reused_tokens)}") + " + share")
    region = region.replace('`last: ${fmt(last.output_tokens)} tokens${last.decode_tok_s ? ` at ${fmt(last.decode_tok_s, 1)} tok/s` : ""}`',
                            call("monitor.last", '{count:fmt(last.output_tokens),rate:last.decode_tok_s ? ' + call("monitor.rate", "{rate:fmt(last.decode_tok_s, 1)}") + ' : ""}'))
    totals_start = region.index("  return `Since")
    totals_end = region.index(";\n", totals_start)
    region = region[:totals_start] + "  return " + call("monitor.totals", "{since,requests:fmt(t.requests),read:fmt(read),prefill:pSpeed,reused:fmt(t.reused),output:fmt(t.output_tokens),decode:oSpeed}") + region[totals_end:]
    projection_start = region.index("  return `${mode ===")
    projection_end = region.index(";\n", projection_start)
    region = region[:projection_start] + (
        '  return (mode === "project" ? ' + call("about.projection", "{first:a,last:b}") + " : " +
        call("about.additive", "{first:a,last:b}") + ") + (single ? " +
        call("about.projectionSingle", '{layer:single.replace("single", "")}') + ' : "") + ' + call("about.projectionNote")
    ) + region[projection_end:]
    region = region.replace('live.phase[0].toUpperCase() + live.phase.slice(1)', 'fnState(live.phase, live.phase[0].toUpperCase() + live.phase.slice(1))')
    region = region.replace('class="muted">No requests yet</td>', 'class="muted">${esc(fnText("No requests yet"))}</td>')
    region = region.replace('aria-label="Copy">${icon("copy")}', 'aria-label="${esc(fnText("Copy"))}">${icon("copy")}')
    region = region.replace('>default</option>', '>${esc(fnText("default"))}</option>')
    region = region.replace('placeholder="default"', 'placeholder="${esc(fnText("default"))}"')
    region = region.replace('[["true", "on"], ["false", "off"]]', '[["true", fnText("on")], ["false", fnText("off")]]')
    region = region.replace('eng.images ? "on" : "off"', 'eng.images ? fnText("on") : fnText("off")')
    region = region.replace('esc(k.help)', 'esc(tr("fnos.config." + k.key, k.help))')
    region = region.replace('k.choices.map((x) => [x, x])', 'k.choices.map((x) => [x, fnText(x)])')
    region = region.replace('", all in VRAM"', call("about.kvResident"))
    region = region.replace('`MTP drafts up to ${Math.max(0, (eng.mtp_max || eng.spec) - 1)} tokens${eng.lookup ? ", prompt lookup on" : ""}`',
                            '(' + call("about.spec", "{count:Math.max(0, (eng.mtp_max || eng.spec) - 1)}") + " + (eng.lookup ? " + call("about.lookup") + ' : ""))')
    region = region.replace('${fmt(s.tools.length)} tools', '${esc(' + call("mcp.tools", "{count:fmt(s.tools.length)}") + ')}')
    region = region.replace('`${st.cores ? `${st.cores} cores · ` : ""}${st.threads} threads`',
                            '(st.cores ? ' + call("monitor.cores", "{count:st.cores}") + ' : "") + ' + call("monitor.threads", "{count:st.threads}"))
    region = region.replace('`, ${st.threads} threads`', '`, ${' + call("monitor.threads", "{count:st.threads}") + '}`')
    region = region.replace('title="experimental speed projection ${r.projection ? "on" : "off"}"',
                            'title="${esc(' + call("monitor.projection", '{state:fnText(r.projection ? "on" : "off")}') + ')}"')
    region = region.replace('title="routed experts the GPU read over PCIe (--pcie-frac) or another GPU computed"',
                            'title="${esc(fnText("routed experts the GPU read over PCIe (--pcie-frac) or another GPU computed"))}"')
    region = region.replace('${fmt(r.duration_s, 1)} s', '${' + call("monitor.duration", "{seconds:fmt(r.duration_s, 1)}") + '}')
    # Only standalone literals in these sections are replaced. The replacements
    # inside template markup above are added after this pass.
    existing_calls = {}
    def protect(match):
        token = f"__FNOS_TEXT_{len(existing_calls)}__"
        existing_calls[token] = match[0]
        return token
    region = re.sub(r'fnText\("[^"\n]+"\)', protect, region)
    region = translate_literals(region, (STATIC | DYNAMIC).keys())
    for token, expression in existing_calls.items():
        region = region.replace(token, expression)
    # Resolve the badge text when rendering, after the language catalog has loaded.
    start_mcp = region.index("const MCP_STATE =")
    end_mcp = region.index("function renderMcp()", start_mcp)
    mcp_state = re.sub(r'fnText\(("[^"]+")\)', r'\1', region[start_mcp:end_mcp])
    region = region[:start_mcp] + mcp_state + region[end_mcp:]
    region = region.replace('esc(text)}</span>` +\n      `<strong>', 'esc(fnText(text))}</span>` +\n      `<strong>')
    source = source[:start] + region + source[end:]
    source = source.replace('${esc(m.label)}</span>', '<span data-i18n="fnos.${esc(m.label)}">${esc(m.label)}</span></span>')
    source = source.replace('id="ms-speed">Decode', 'id="ms-speed" data-i18n="fnos.Decode">Decode')
    source = source.replace('id="ms-prefill">Prefill', 'id="ms-prefill" data-i18n="fnos.Prefill">Prefill')
    source = source.replace('store.get("lang", "en")', 'store.get("lang", "zh")')
    source = source.replace("{model} runs on this PC. Nothing leaves it.", "{model} runs on this device.")
    source = source.replace('  if (lastMetrics) render(lastMetrics);\n}\n$("lang").onchange', '  if (lastMetrics) render(lastMetrics);\n  renderMcp();\n  if (tab === "about") loadConfig();\n}\n$("lang").onchange')
    source = source.replace('"Generating\\u2026 (a minute or more on a small GPU)"', call("image.working"))
    source = source.replace('`${j.size}, seed ${d.seed}, ${((performance.now() - t0) / 1000).toFixed(0)} s: ${prompt}`',
                            call("image.caption", "{size:j.size,seed:d.seed,seconds:((performance.now() - t0) / 1000).toFixed(0),prompt}"))
    for value in ("Image unavailable", "No image", "Done. Right-click an image to save it."):
        source = source.replace(js_string(value), literal(value))
    source = source.replace('class="muted cursor">Writing</span>', 'class="muted cursor">${esc(tr("fnos.Writing", "Writing"))}</span>')
    source = source.replace('alt="Tool image"', 'alt="${esc(fnText("Tool image"))}"')
    source = source.replace('>Download image</a>', '>${esc(fnText("Download image"))}</a>')
    source = source.replace('img.alt = "Image unavailable; try refreshing"', 'img.alt = fnText("Image unavailable; try refreshing")')
    source = source.replace('${fmt(t.ms / 1000, 1)} s', '${' + call("monitor.duration", "{seconds:fmt(t.ms / 1000, 1)}") + '}')
    source = patch_chat_metadata(source)
    return source


def patch_chat_metadata(source):
    # Keep new message statistics as data, so changing languages redraws existing messages too.
    display = r'''function messageMeta(m) {
  const info = m.stats;
  if (!info) {
    return (m.meta || "").split(" · ").map((part) => {
      const count = part.match(/^([\d.,\s]+)\s+(?:tokens?|个\s*(?:token|词元))$/);
      if (count) return tr("chat.tokens", "{n} tokens", {n: count[1].trim()});
      const rate = part.match(/^([\d.,\s]+)\s+(?:tok\/s|词元\/秒)$/);
      return rate ? fnFormat("chat.rate", "{rate} tok/s", {rate: rate[1].trim()}) : part;
    }).join(" · ");
  }
  const labels = [];
  if (info.tokens) labels.push(tr("chat.tokens", "{n} tokens", {n: fmt(info.tokens)}));
  if (info.rate != null) labels.push(fnFormat("chat.rate", "{rate} tok/s", {rate: fmt(info.rate, 1)}));
  if (m.stopped) labels.push(m.interrupted ? tr("chat.interruptedLower", "interrupted") : tr("chat.stoppedLower", "stopped"));
  if (info.projection != null) labels.push(info.projection ? tr("chat.projectionOn", "projection on") : tr("chat.projectionOff", "projection off"));
  const ran = (m.tools || []).filter((t) => t.state === "done" || t.state === "error").length;
  if (ran) labels.push(tr("chat.toolCalls", {one: "{n} tool call", other: "{n} tool calls"}, {n: ran}));
  if (m.limit) labels.push(tr("chat.toolLimit", "stopped at the limit of {n} tool rounds (mcp.max_rounds)", {n: m.limit}));
  return labels.join(" · ");
}
'''
    source = source.replace("function updateAssistant(", display + "function updateAssistant(", 1)
    source = source.replace('textContent = m.meta || (streaming', 'textContent = messageMeta(m) || (streaming', 1)
    start = source.index('  const ended = cut ? tr("chat.interruptedLower"')
    end = source.index("  busy = null;", start)
    finalize = '''  const secs = firstAt ? (performance.now() - firstAt) / 1000 : 0;
  m.stats = {
    tokens: secs ? n : null,
    rate: n && secs > 0.25 ? n / secs : null,
    projection: n && secs && projectionLoaded() ? settings.esp : null
  };
  for (const t of m.tools || []) if (t.state === "writing" || t.state === "running") { t.state = "skipped"; t.ms = null; }
'''
    return source[:start] + finalize + source[end:]


def patch_monitor(source):
    source = source.replace('"use strict";', '''"use strict";
const fnText = (english) => tr("fnos." + english, english);
const fnFormat = (key, english, vars) => tr("fnos." + key, english, vars);
const fnState = (code) => tr("fnos.state." + code, code);
''', 1)
    source = translate_literals(source, (STATIC | DYNAMIC).keys())
    source = source.replace('`Request ${r.id}`', call("api.request", "{id:r.id}"))
    source = source.replace('tag.textContent = r.state', 'tag.textContent = fnState(r.state)')
    source = source.replace('text("detail-status", value.state)', 'text("detail-status", fnState(value.state))')
    source = source.replace('${r.stream ? "stream" : "JSON response"}', '${r.stream ? fnText("stream") : fnText("JSON response")}')
    source = source.replace('value.response_format || "text"', 'fnText(value.response_format || "text")')
    source = source.replace('`${inflight} active / queued`', call("api.active", "{count:inflight}"))
    source = source.replace('`Live · updated ${new Date().toLocaleTimeString()}`', call("api.updated", "{time:new Date().toLocaleTimeString()}"))
    source = source.replace('`${n.toFixed(2)} s`', call("monitor.duration", "{seconds:n.toFixed(2)}"))
    source = source.removesuffix("poll();\n") + '''let language = new URLSearchParams(location.search).get("lang");
if (!language) {
  try { language = JSON.parse(localStorage.getItem("strata.lang")) || "zh"; }
  catch (_) { language = "zh"; }
}
StrataI18n.setLanguage(language).then(poll);
'''
    return source
