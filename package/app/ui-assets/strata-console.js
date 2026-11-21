const byId = (id) => document.getElementById(id);
if (window.parent !== window) {
  function setWindowClip(left, right, bottom) {
    const style = document.documentElement.style;
    style.setProperty("--window-clip-left", Math.max(0, left) + "px");
    style.setProperty("--window-clip-right", Math.max(0, right) + "px");
    style.setProperty("--window-clip-bottom", Math.max(0, bottom) + "px");
  }
  const frame = window.frameElement;
  if (frame) {
    // fnOS can move part of the app window off-screen. Read the visible area
    // from its desktop without changing the host window or its saved position.
    const desktop = frame.ownerDocument.documentElement;
    const view = frame.ownerDocument.defaultView;
    const fit = () => {
      const box = frame.getBoundingClientRect();
      const left = Math.max(0, -box.left), right = Math.max(0, box.right - desktop.clientWidth);
      if (box.width > left + right) setWindowClip(left, right, box.bottom - desktop.clientHeight);
    };
    const resize = new ResizeObserver(fit);
    resize.observe(frame);
    resize.observe(desktop);
    const movement = new MutationObserver(fit);
    for (let node = frame; node; node = node.parentElement) {
      movement.observe(node, {attributes: true, attributeFilter: ["style", "class"]});
    }
    view.addEventListener("scroll", fit, {capture: true, passive: true});
    window.addEventListener("pagehide", () => {
      resize.disconnect();
      movement.disconnect();
      view.removeEventListener("scroll", fit, true);
    }, {once: true});
    fit();
  } else {
    const viewport = byId("window-viewport");
    const clip = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      const full = entry.boundingClientRect, visible = entry.intersectionRect;
      setWindowClip(visible.left - full.left, full.right - visible.right, full.bottom - visible.bottom);
    }, {threshold: Array.from({length: 101}, (_, i) => i / 100)});
    clip.observe(viewport);
  }
}
const form = byId("form"), root = byId("root"), files = byId("files"), source = byId("source");
let folder = "", picked = "", csrf = "", options = {}, roots = [], state = "";
let status = {}, adding = false, libraryKey = "", settingsRevision = "", settingsActive = "";
let settingsGroup = "思考与回答", runtimeBusy = false, unsavedSettings = false;
let libraryLayout = "grid";
try { libraryLayout = localStorage.getItem("strata.console.layout") === "list" ? "list" : "grid"; } catch (_) {}
const base = location.pathname.replace(/\/$/, "") + "/";
const states = {
  empty: "请选择一个模型，Strata 会准备并自动加载它。",
  starting: "正在加载模型。大模型首次加载可能需要几分钟。",
  failed: "模型启动失败。可从模型库重新加载或切换模型。",
  unavailable: "暂时无法读取推理服务状态。",
  unloaded: "当前模型已卸载。",
  ready: "模型已就绪。"
};
function error(message) { byId("message").textContent = message; }
function modelDisplay(name = "") {
  const quant = name.match(/(?:^|[-_])((?:ud[-_])?(?:iq|q)\d[\w_]*?)$/i)?.[1];
  const label = /^qwen3[.]8[-_]flash[-_]next/i.test(name) ? "Qwen3.8 Flash Next" : name.replace(/[-_]/g, " ");
  return {label, quant: quant ? quant.replace(/^ud[-_]/i, "UD ").toUpperCase() : "GGUF"};
}
function setPage(view) {
  const previous = document.body.dataset.view;
  document.body.dataset.view = view;
  if (previous !== view) window.scrollTo({top: 0, behavior: "auto"});
  byId("settings").hidden = view !== "settings";
  byId("ready").hidden = view !== "api";
  byId("toggle-settings").setAttribute("aria-expanded", String(view === "settings"));
  byId("toggle-api").setAttribute("aria-expanded", String(view === "api"));
  if (view === "models") byId("nav-models").setAttribute("aria-current", "page");
  else byId("nav-models").removeAttribute("aria-current");
  byId("page-title").textContent = {models: "模型管理", settings: "运行设置", api: "API 工具"}[view];
  const active = status.models?.find(model => model.id === status.active);
  byId("page-description").textContent = view === "models" ? "管理本地模型，查看资源与准备任务" :
    view === "settings" ? "当前模型：" + (active ? modelDisplay(active.name).label : "尚未选择") : "连接本地推理服务与其他客户端";
  if (view !== "api") { setKeyVisible(); byId("api-copy-status").textContent = ""; }
}
byId("nav-models").onclick = () => setPage("models");
document.querySelector(".console-brand").onclick = event => { event.preventDefault(); setPage("models"); };
byId("theme-toggle").onclick = () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("strata.theme", theme); } catch (_) {}
};
function renderRuntime(runtime) {
  const memory = runtime.memory, gpu = runtime.gpus?.[0];
  byId("stat-memory").textContent = memory ? `${memory.MemAvailable} GiB 可用` : "暂不可用";
  byId("stat-memory-note").textContent = memory ? `系统总量 ${memory.MemTotal} GiB` : "无法读取系统内存";
  byId("memory-meter").value = memory ? 100 * (1 - memory.MemAvailable / memory.MemTotal) : 0;
  byId("memory-meter").hidden = !memory;
  byId("stat-gpu").textContent = gpu ? `${(Number(gpu.used) / 1024).toFixed(1)} / ${(Number(gpu.total) / 1024).toFixed(0)} GiB` : "暂不可用";
  byId("stat-gpu-note").textContent = gpu ? gpu.name.replace(/^NVIDIA GeForce /, "") + ` · 使用率 ${gpu.utilization}%` : "等待 NVIDIA 显卡数据";
  byId("gpu-meter").value = gpu ? 100 * Number(gpu.used) / Number(gpu.total) : 0;
  byId("gpu-meter").hidden = !gpu;
  byId("stat-experts").textContent = runtime.experts?.match(/^\d+ 个专家/)?.[0] || "等待模型载入";
  byId("stat-experts-note").textContent = runtime.experts?.split(" · ")[1] ? runtime.experts.split(" · ")[1] + " · 载入记录" : "取自本次启动日志";
  const tools = runtime.tools || [];
  byId("stat-tools").textContent = tools.some(tool => tool.status === "ready") ? "工具已就绪" : tools.length ? "工具待连接" : runtime.tool_state || "未连接";
  const names = {public_search: "联网搜索", strata_shell: "Shell 命令"};
  byId("stat-tools-note").textContent = tools.length ? tools.map(tool => `${names[tool.name] || tool.name} · ${tool.count} 项`).join(" / ") : "没有可用工具连接";
  byId("runtime-updated").textContent = "资源状态更新于 " + new Date().toLocaleTimeString("zh-CN", {hour12: false}) + " · 每 10 秒刷新";
}
async function refreshRuntime() {
  if (runtimeBusy || document.hidden) return;
  runtimeBusy = true;
  try { renderRuntime(await api("runtime")); }
  catch (_) { byId("runtime-updated").textContent = "资源状态暂时无法刷新，可点击右上角重试。"; }
  finally { runtimeBusy = false; }
}
byId("refresh-dashboard").onclick = async () => {
  const button = byId("refresh-dashboard"); button.disabled = true;
  try { await refreshStatus(); await refreshRuntime(); } finally { button.disabled = false; }
};
setInterval(refreshRuntime, 10000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshRuntime(); });
async function api(path, body) {
  const request = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Strata-Setup": csrf},
    body: JSON.stringify(body)
  };
  const response = await fetch(base + path, request);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "无法连接 Strata。");
  return data;
}
function canSubmit() {
  byId("submit").disabled = status.job?.result === "running" || status.changing || state === "starting" ||
                            (source.value === "local" && !picked);
}
function changeSource() {
  const local = source.value === "local";
  byId("local").hidden = local === false;
  byId("download-note").hidden = local;
  byId("repository-field").hidden = local;
  const choices = Object.entries(options).map(([id, label]) => new Option(label, id));
  if (local) choices.unshift(new Option("自动识别", ""));
  byId("model").replaceChildren(...choices);
  const verb = local ? "导入" : "下载";
  byId("submit").textContent = status.active ? verb + "模型" : verb + "并加载";
  canSubmit();
}
async function browse() {
  const requestedFolder = folder, requestedRoot = root.value;
  files.replaceChildren();
  byId("folder").textContent = folder || "模型目录";
  byId("up").disabled = !folder;
  if (!roots.length) return;
  try {
    const rows = await api("browse?" + new URLSearchParams({root: requestedRoot, path: requestedFolder}));
    if (folder !== requestedFolder || root.value !== requestedRoot) return;
    for (const row of rows) {
      const item = document.createElement("li"), button = document.createElement("button");
      button.type = "button";
      if (row.directory) button.classList.add("folder-row");
      if (!row.directory) button.dataset.file = folder ? folder + "/" + row.name : row.name;
      if (!row.directory) button.setAttribute("aria-pressed", String(button.dataset.file === picked));
      button.textContent = row.directory ? row.name + "/" : row.name;
      button.onclick = () => {
        const path = folder ? folder + "/" + row.name : row.name;
        if (row.directory) { folder = path; selectFile(""); browse(); }
        else selectFile(path);
      };
      item.append(button);
      files.append(item);
    }
    if (!rows.length) byId("folder").textContent += " · 没有可选的 GGUF";
  } catch (reason) { error(reason.message); }
}
function selectFile(path) {
  picked = path;
  for (const button of files.querySelectorAll("[data-file]")) {
    button.setAttribute("aria-pressed", String(button.dataset.file === path));
  }
  byId("picked").textContent = path ? "已选 " + path : "请选择 GGUF 文件。";
  canSubmit();
}
root.onchange = () => { folder = ""; selectFile(""); browse(); };
source.onchange = changeSource;
byId("refresh").onclick = () => { error(""); browse(); };
byId("up").onclick = () => { folder = folder.split("/").slice(0, -1).join("/"); selectFile(""); browse(); };
form.onsubmit = async (event) => {
  event.preventDefault();
  error("");
  byId("fields").disabled = true;
  try {
    await api("import", {source: source.value, model: byId("model").value, repository: byId("repository").value, root: root.value,
                         path: picked, context: byId("context").value, bf16: byId("bf16").checked});
    adding = false;
    form.hidden = true;
    await refreshStatus();
  } catch (reason) { error(reason.message); }
  finally { byId("fields").disabled = false; }
};
function setKeyVisible(value = "") {
  const input = byId("key"), button = byId("show-key");
  input.value = value;
  input.type = value ? "text" : "password";
  button.setAttribute("aria-expanded", String(Boolean(value)));
  button.textContent = value ? "隐藏 API 密钥" : "显示 API 密钥";
  if (value) input.select();
}
const apiBase = new URL("http://" + location.hostname + ":18180/v1");
byId("api-base").value = apiBase.href;
const copyIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';
async function copyApiValue(value) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (_) {
    const field = document.createElement("textarea");
    field.value = value;
    field.style.cssText = "position:fixed;left:-9999px;top:0";
    field.setAttribute("readonly", "");
    document.body.appendChild(field);
    try {
      field.select();
      return document.execCommand("copy");
    } catch (_) {
      return false;
    } finally {
      field.remove();
    }
  }
}
for (const [id, getValue, showValue] of [
  ["copy-base", async () => byId("api-base").value, () => byId("api-base").select()],
  ["copy-key", async () => byId("key").value || (await api("chat-key", {})).key, setKeyVisible]
]) {
  const button = byId(id);
  button.innerHTML = copyIcon;
  button.onclick = async () => {
    const status = byId("api-copy-status");
    button.disabled = true;
    try {
      const value = await getValue();
      if (byId("ready").hidden) return;
      if (!value) throw new Error("当前没有可复制的内容。");
      if (await copyApiValue(value)) status.textContent = "已复制。";
      else {
        showValue(value);
        status.textContent = "浏览器无法自动复制，请手动复制选中的内容。";
      }
    } catch (reason) {
      status.textContent = reason.message;
    } finally {
      button.disabled = false;
    }
  };
}
function showPanel(id, visible) {
  const view = id === "ready" ? "api" : "settings";
  if (visible) setPage(view);
  else if (document.body.dataset.view === view) setPage("models");
  else byId(id).hidden = true;
}
byId("toggle-api").onclick = () => {
  showPanel("ready", true);
};
byId("show-key").onclick = async () => {
  const button = byId("show-key");
  if (byId("key").value) return setKeyVisible();
  button.disabled = true;
  try {
    const {key} = await api("chat-key", {});
    if (!byId("ready").hidden) setKeyVisible(key);
  } catch (reason) { error(reason.message); }
  finally { button.disabled = false; }
};
const modelSources = { local: "本地 GGUF", existing: "已有配置", huggingface: "Hugging Face", modelscope: "ModelScope" };
const gigabytes = (bytes) => (bytes / 1000000000).toFixed(1) + " GB";
const taskSteps = {
  "Getting the helper packages ready": "正在准备依赖组件",
  "Checking the engine for this PC": "正在检查本机推理引擎",
  "Getting the model files": "正在获取模型文件",
  "Downloading the model files": "正在下载模型文件",
  "The model files are on this computer; checking them": "正在校验本地模型文件",
  "Preparing your model for Strata (one time)": "正在准备模型（仅首次需要）",
  "Preparing the model data for the engine (one time)": "正在转换推理引擎所需的数据（仅首次需要）",
  "Saving the model's settings": "正在保存模型设置",
  "Writing this launch's settings…": "正在写入启动配置…",
  "Settings are saved.": "模型设置已保存。",
  "Model registered. Select it on the workstation homepage.": "模型已加入模型库。"
};
function localizeTaskLine(line) {
  const verification = line.match(/^Checking that the model files are complete.*?(?:\:\s*([\d.]+) of ([\d.]+) GB)?$/);
  if (verification) return verification[1] ? "正在校验模型文件（" + verification[1] + " / " + verification[2] + " GB）" : "正在校验模型文件";
  const downloading = line.match(/^(.+?):\s*([\d.]+) of ([\d.]+) GB$/);
  if (downloading && taskSteps[downloading[1]]) return taskSteps[downloading[1]] + "（" + downloading[2] + " / " + downloading[3] + " GB）";
  return taskSteps[line] || line;
}
function showJob(job) {
  byId("task").hidden = !job;
  byId("task-empty").hidden = Boolean(job) || state === "starting";
  for (const id of ["stage-files", "stage-prepare", "stage-load"]) byId(id).dataset.current = "false";
  if (state === "starting") byId("stage-load").dataset.current = "true";
  if (!job) return;
  byId("task").dataset.result = job.result;
  const downloading = job.source === "download";
  const label = downloading ? "下载" : "导入";
  byId("task-name").textContent = label + " · " + job.name;
  const done = job.result === "complete", failed = job.result === "error";
  const interrupted = job.result === "interrupted";
  const step = job.step || "";
  const verifying = /Checking that the model files are complete/i.test(step);
  const preparing = job.stage === "config" || /Preparing.*model|Saving the model/i.test(step);
  if (job.result === "running") byId(preparing || verifying || !downloading ? "stage-prepare" : "stage-files").dataset.current = "true";
  byId("task-status").textContent = done ? label + "完成，模型已加入模型库。" :
    failed ? label + "失败，可重新提交。" : interrupted ? label + "已中断，可重新提交继续。" :
    verifying ? "正在校验模型文件…" :
    preparing || !downloading ? "正在准备模型…" : "正在下载模型文件…";
  const showBytes = job.result === "running" && Number.isFinite(job.bytes) && job.total > 0;
  byId("task-progress").hidden = !showBytes;
  byId("task-bytes").hidden = !showBytes;
  if (showBytes) {
    byId("task-progress").value = Math.min(100, 100 * job.bytes / job.total);
    byId("task-bytes").textContent = gigabytes(job.bytes) + " / 约 " + gigabytes(job.total);
  }
  byId("task-details").hidden = !step && !job.detail;
  byId("progress").textContent = [step, job.detail].filter(Boolean).join("\n").split("\n").map(localizeTaskLine).join("\n");
}
function showLibrary(data) {
  if (!Array.isArray(data.models)) return;
  const query = byId("model-search").value.trim().toLocaleLowerCase();
  const filter = byId("model-filter").value;
  const key = JSON.stringify([data.models, data.active, data.state, data.changing, data.job?.result, query, filter, libraryLayout]);
  if (key === libraryKey) return;
  libraryKey = key;
  byId("model-empty").hidden = data.models.length > 0;
  byId("model-count").textContent = `${data.models.length} 个模型`;
  const models = data.models.filter(model => (!query || model.name.toLocaleLowerCase().includes(query)) &&
    (filter === "all" || (filter === "active") === (data.active === model.id)));
  byId("model-no-match").hidden = Boolean(models.length) || !data.models.length;
  byId("library").dataset.layout = libraryLayout;
  byId("library-view").setAttribute("aria-label", libraryLayout === "grid" ? "切换为列表视图" : "切换为网格视图");
  byId("library-view").setAttribute("aria-pressed", String(libraryLayout === "list"));
  byId("library-view").innerHTML = libraryLayout === "grid" ?
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M8 6h12M8 12h12M8 18h12M4 6h.1M4 12h.1M4 18h.1"/></svg>' :
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>';
  const rows = models.map((model) => {
    const row = document.createElement("div");
    row.className = "model-row";
    const info = document.createElement("div"), name = document.createElement("strong"), meta = document.createElement("div");
    const display = modelDisplay(model.name);
    name.className = "model-name";
    name.textContent = display.label;
    const tags = document.createElement("div"), quant = document.createElement("span");
    tags.className = "model-tags"; quant.className = "model-tag"; quant.textContent = display.quant; tags.append(quant);
    meta.className = "model-meta";
    meta.textContent = [modelSources[model.source], model.context && Number(model.context).toLocaleString("zh-CN") + " tokens"].filter(Boolean).join(" · ");
    const identity = document.createElement("details"), summary = document.createElement("summary"), code = document.createElement("code");
    identity.className = "model-identifier"; summary.textContent = "完整配置名称"; code.textContent = model.name;
    identity.append(summary, code);
    info.append(tags, name, meta, identity);
    row.append(info);
    const active = data.active === model.id;
    row.dataset.current = active;
    const actions = document.createElement("div"); actions.className = "model-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = active && data.state === "ready" ? "当前模型" : active ? "加载当前模型" : "切换到此模型";
    button.disabled = (active && data.state === "ready") || data.state === "starting" || data.changing || data.job?.result === "running";
    button.onclick = async () => {
      button.disabled = true;
      error("");
      try { await api("activate", {id: model.id}); await refreshStatus(); }
      catch (reason) { error(reason.message); button.disabled = false; }
    };
    if (active && data.state === "ready") {
      const badge = document.createElement("span");
      badge.className = "model-current";
      badge.textContent = "当前使用";
      const settings = document.createElement("button"); settings.type = "button"; settings.textContent = "运行设置";
      settings.onclick = () => byId("toggle-settings").click();
      actions.append(badge, settings);
    } else {
      actions.append(button);
    }
    row.append(actions);
    return row;
  });
  byId("library").replaceChildren(...rows);
}
byId("model-search").oninput = () => showLibrary(status);
byId("model-filter").onchange = () => showLibrary(status);
byId("library-view").onclick = () => {
  libraryLayout = libraryLayout === "grid" ? "list" : "grid";
  try { localStorage.setItem("strata.console.layout", libraryLayout); } catch (_) {}
  showLibrary(status);
};
async function loadSettings() {
  const active = settingsActive;
  const data = await api("settings");
  if (active !== settingsActive || byId("settings").hidden) return;
  const categories = {
    context: "上下文与缓存", kv: "上下文与缓存", kv_resident: "上下文与缓存", kv_grow: "上下文与缓存",
    cache_size: "上下文与缓存", cache_slots: "上下文与缓存", cache_free: "上下文与缓存",
    thinking_level: "思考与回答", thinking_budget: "思考与回答", output_limit: "思考与回答",
    shell: "工具与权限", shell_cwd: "工具与权限", shell_timeout: "工具与权限", search: "工具与权限",
    tool_rounds: "工具与权限", tool_timeout: "工具与权限", tool_output: "工具与权限"
  };
  const groups = new Map([["思考与回答", []], ["搜索代理", []], ["推理与资源", []], ["上下文与缓存", []], ["工具与权限", []]]);
  for (const field of data.items) {
    const name = categories[field.id] || "推理与资源";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(field);
  }
  const fields = [], nav = [], extras = byId("tool-extras"), proxy = byId("search-proxy-fields");
  if (!extras || !proxy) throw new Error("界面组件未完整加载，请刷新页面后重试。");
  const descriptions = {
    "思考与回答": "设置默认思考与输出预算，也可先选择场景预设，再按需微调。",
    "搜索代理": "配置联网搜索的连接方式与 HTTP 代理。模型下载沿用下载环境的网络设置。",
    "推理与资源": "管理模型在内存与显存中的资源分配，修改后需要重新载入。",
    "上下文与缓存": "调整上下文容量、KV 格式与会话缓存。更大的容量需要更多资源。",
    "工具与权限": "管理联网搜索开关、MCP 工具限制与可选 Shell。"
  };
  let index = 0;
  for (const [name, items] of groups) {
    const group = document.createElement("section"), heading = document.createElement("h2"), grid = document.createElement("div");
    group.className = "settings-group"; group.dataset.group = name; group.id = "settings-group-" + index;
    group.setAttribute("role", "tabpanel"); group.setAttribute("aria-labelledby", "settings-tab-" + index);
    heading.textContent = name;
    const description = document.createElement("p"); description.className = "group-description"; description.textContent = descriptions[name] || "";
    grid.className = "settings-grid"; group.append(heading, description, grid);
    const tab = document.createElement("button"); tab.type = "button"; tab.id = "settings-tab-" + index;
    tab.textContent = name; tab.dataset.group = name; tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", group.id);
    tab.onclick = () => { settingsGroup = name; byId("settings-filter").value = ""; filterSettings(); };
    nav.push(tab); index++;
    for (const field of items) {
    const wrapper = document.createElement("div"), label = document.createElement("label");
    wrapper.className = "setting-field";
    wrapper.dataset.search = [field.label, field.id, field.help || "", name, name === "工具与权限" ? "MCP" : ""].join(" ").toLocaleLowerCase();
    label.className = "setting-name"; label.textContent = field.label;
    if (field.defaulted) {
      const badge = document.createElement("span"); badge.className = "setting-default";
      badge.textContent = "默认"; badge.title = "未单独设置，当前显示默认值";
      badge.setAttribute("aria-hidden", "true"); label.append(badge);
    }
    const input = document.createElement(field.options ? "select" : "input");
    input.name = field.id; input.id = "setting-" + field.id; label.htmlFor = input.id;
    if (field.options) {
      const current = field.options.find((choice) => choice.value === field.value);
      if (field.value && !current) input.append(new Option("当前值（" + field.value + "）", field.value));
      if (!field.value) input.append(new Option("自动（引擎默认）", ""));
      for (const choice of field.options) input.append(new Option(choice.label, choice.value));
      input.value = field.value || "";
    } else {
      input.type = field.type || "number";
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
      input.value = field.value;
      input.placeholder = field.placeholder || "自动（引擎默认）";
    }
    input.disabled = Boolean(field.disabled);
    input.dataset.initialValue = input.value;
    wrapper.append(label, input);
    const helpText = field.defaulted ? (field.help || "").replace(/^未单独设置，显示默认值。/, "") : field.help;
    if (helpText) {
      const help = document.createElement("small");
      help.className = "setting-help"; help.id = input.id + "-help";
      help.textContent = helpText;
      input.setAttribute("aria-describedby", help.id);
      wrapper.append(help);
    }
      grid.append(wrapper);
    }
    if (name === "搜索代理") group.append(proxy);
    if (name === "工具与权限") group.append(extras);
    fields.push(group);
  }
  byId("settings-fields").replaceChildren(...fields);
  byId("settings-nav").replaceChildren(...nav);
  filterSettings();
  const preset = byId("settings-preset");
  preset.replaceChildren(new Option("选择预设", ""));
  for (const [key, item] of Object.entries(data.presets || {})) preset.append(new Option(item.label, key));
  preset.onchange = () => {
    for (const [name, value] of Object.entries(data.presets[preset.value]?.values || {})) {
      const input = byId("settings-form").elements.namedItem(name);
      if (input) input.value = value;
    }
    updateDirty();
  };
  byId("settings-restore").disabled = !data.restorable || status.state !== "ready";
  const runtime = data.runtime || {};
  renderRuntime(runtime);
  const lines = [];
  if (runtime.memory) lines.push(`系统内存 ${runtime.memory.MemTotal} GiB · 可用 ${runtime.memory.MemAvailable} GiB`);
  for (const gpu of runtime.gpus || []) lines.push(`GPU ${gpu.index} ${gpu.name} · 显存 ${gpu.used}/${gpu.total} MiB · 使用率 ${gpu.utilization}%`);
  lines.push("专家缓存（本次加载记录）：" + (runtime.experts || "暂无记录"));
  const toolNames = {public_search: "联网搜索", strata_shell: "Shell 命令"};
  const toolStates = {ready: "已就绪", starting: "连接中", error: "连接失败", stopped: "已停止", disabled: "已关闭"};
  lines.push("工具连接：" + (runtime.tools?.map(t => `${toolNames[t.name] || t.name} ${toolStates[t.status] || t.status}（${t.count} 项）`).join(" · ") || runtime.tool_state));
  const sharedLabels = {reasoning_effort: "思考强度", reasoning_budget_tokens: "思考 token", max_tokens: "输出 token"};
  if (Object.keys(runtime.shared || {}).length) lines.push("聊天页共享设置优先于下方启动默认值：" +
    Object.entries(runtime.shared).map(([key, value]) => `${sharedLabels[key]} ${value}`).join(" · ") + "。可在聊天页的设置中调整共享值。");
  byId("runtime-summary").replaceChildren(...lines.map(text => { const p = document.createElement("p"); p.textContent = text; return p; }));
  byId("shell-history").textContent = runtime.shell_history?.length ? runtime.shell_history.map(row =>
    `${row.time} · ${row.command_sha256} · 退出 ${row.exit_code} · ${row.seconds} 秒${row.timed_out ? " · 超时" : ""}`).join("\n") : "暂无记录";
  const mode = byId("search-proxy-mode");
  mode.value = data.search_proxy_mode;
  mode.dataset.initialValue = mode.value;
  byId("search-proxy-endpoint").textContent = data.search_proxy_endpoint || "";
  byId("search-proxy-current").hidden = true;
  const proxyUrl = byId("search-proxy-url");
  proxyUrl.value = data.search_proxy_url ?? data.search_proxy_endpoint ?? "";
  proxyUrl.dataset.initialValue = proxyUrl.value;
  proxyUrl.placeholder = "http://proxy.example.com:7890";
  byId("search-proxy-fields").hidden = false;
  mode.onchange();
  initShellDirectories(data);
  settingsRevision = data.revision;
  updateDirty();
}
let shellDirectories = [], shellFolder = "", shellSelection = new Set(), shellBrowseVersion = 0;
function syncShellDirectories(dirty = true) {
  const hidden = byId("shell-dirs-value"), select = byId("setting-shell_cwd");
  const selected = select.value;
  hidden.value = JSON.stringify(shellDirectories.map(item => item.path));
  select.replaceChildren(new Option("Strata 工作区（默认）", "workspace"), ...shellDirectories.map(item => {
    const option = new Option(item.label + (item.available === false ? "（不可访问）" : ""), item.path);
    option.disabled = item.available === false; return option;
  }));
  select.value = shellDirectories.some(item => item.path === selected) ? selected : "workspace";
  const fixed = document.createElement("p"); fixed.className = "small muted"; fixed.textContent = "暂无目录，勾选后添加。";
  const rows = shellDirectories.map(item => {
    const row = document.createElement("div"), path = document.createElement("span"), remove = document.createElement("button");
    row.className = "shell-dir-item"; path.textContent = item.label + (item.available === false ? " · 不可访问，请重新授权或移除" : ""); path.title = item.path;
    remove.type = "button"; remove.textContent = "移除"; remove.setAttribute("aria-label", "移除 " + item.label);
    remove.onclick = () => { shellDirectories = shellDirectories.filter(value => value.path !== item.path); syncShellDirectories(); };
    row.append(path, remove); return row;
  });
  byId("shell-dir-list").replaceChildren(...(rows.length ? rows : [fixed]));
  if (dirty) updateDirty();
}
function setShellRoots(items, preserve = false) {
  const current = byId("shell-dir-root").selectedOptions[0]?.textContent;
  shellBrowseVersion++;
  byId("shell-dir-root").replaceChildren(...items.map(item => new Option(item.label, item.id)));
  byId("shell-dir-permissions").textContent = items.length ? `${items.length} 个位置 · 可多选，最多 16 个目录` : "暂无位置，请先授权。";
  const previous = preserve && items.find(item => item.label === current);
  if (previous) byId("shell-dir-root").value = previous.id;
  else shellFolder = "";
  if (!preserve) shellSelection.clear();
  updateShellSelection();
  byId("shell-dir-folders").replaceChildren();
  byId("shell-dir-location").textContent = "";
}
function updateShellSelection() {
  byId("shell-dir-selection").textContent = shellSelection.size ? `已选择 ${shellSelection.size} 个目录` : "未选择目录";
  byId("shell-dir-selection").title = [...shellSelection].join("\n");
  byId("shell-dir-add").disabled = !shellSelection.size;
}
async function browseShellDirectories() {
  const version = ++shellBrowseVersion, targetRoot = byId("shell-dir-root").value;
  if (!targetRoot) return;
  byId("shell-dir-location").textContent = "正在读取目录…";
  byId("shell-dir-folders").replaceChildren();
  try {
    const data = await api("directories?" + new URLSearchParams({root: targetRoot, path: shellFolder}));
    if (version !== shellBrowseVersion) return;
    byId("shell-dir-location").textContent = data.path;
    byId("shell-dir-up").disabled = !shellFolder;
    const rows = [{name: "选择当前目录", path: data.path}, ...data.directories];
    byId("shell-dir-folders").replaceChildren(...rows.map((item, index) => {
      const row = document.createElement("div"), label = document.createElement("label"), check = document.createElement("input"), text = document.createElement("span");
      row.className = "shell-dir-folder"; check.type = "checkbox"; check.checked = shellSelection.has(item.path); text.textContent = item.name;
      check.onchange = () => { if (check.checked) shellSelection.add(item.path); else shellSelection.delete(item.path); updateShellSelection(); };
      label.append(check, text); row.append(label);
      if (index) { const enter = document.createElement("button"); enter.type = "button"; enter.textContent = "打开"; enter.setAttribute("aria-label", "打开目录 " + item.name); enter.onclick = () => { shellFolder = [shellFolder, item.name].filter(Boolean).join("/"); browseShellDirectories(); }; row.append(enter); }
      return row;
    }));
  } catch (reason) {
    if (version === shellBrowseVersion) { byId("shell-dir-location").textContent = reason.message; byId("shell-dir-permissions").textContent = "读取失败，请检查授权后刷新。"; }
  }
}
function initShellDirectories(data) {
  shellDirectories = (data.shell_dirs || []).map(item => ({...item}));
  syncShellDirectories(false);
  byId("shell-dirs-value").dataset.initialValue = byId("shell-dirs-value").value;
  setShellRoots(data.shell_roots || []);
  byId("shell-dir-homefn").href = location.origin + "/";
  const cwd = byId("setting-shell_cwd").parentElement;
  cwd.querySelector("label").textContent = "默认工作目录";
  const help = cwd.querySelector(".setting-help");
  if (help) help.textContent = "默认工作区无需额外授权。";
  byId("shell-default-directory").replaceChildren(cwd);
  browseShellDirectories();
  byId("shell-dir-root").onchange = () => { shellFolder = ""; browseShellDirectories(); };
  byId("shell-dir-up").onclick = () => { shellFolder = shellFolder.split("/").slice(0, -1).join("/"); browseShellDirectories(); };
  byId("shell-dir-reload-roots").onclick = async () => {
    try { setShellRoots(await api("directory-roots"), true); await browseShellDirectories(); } catch (reason) { byId("shell-dir-permissions").textContent = reason.message; }
  };
  byId("shell-dir-add").onclick = () => {
    const paths = new Map(shellDirectories.map(item => [item.path, item]));
    for (const path of shellSelection) paths.set(path, {path, label: path});
    if (paths.size > 16) { byId("shell-dir-selection").textContent = "最多可添加 16 个目录，请减少选择。"; return; }
    shellDirectories = [...paths.values()]; shellSelection.clear(); updateShellSelection(); syncShellDirectories(); browseShellDirectories();
  };
}

function filterSettings() {
  const query = byId("settings-filter").value.trim().toLocaleLowerCase();
  let visible = 0;
  for (const group of byId("settings-fields").querySelectorAll(".settings-group")) {
    let matches = 0;
    for (const field of group.querySelectorAll(".setting-field")) {
      field.hidden = Boolean(query) && !field.dataset.search.includes(query);
      if (!field.hidden) matches++;
    }
    for (const extras of group.querySelectorAll("#tool-extras, #search-proxy-fields")) {
      extras.hidden = Boolean(query) && !extras.textContent.toLocaleLowerCase().includes(query);
      if (!extras.hidden) matches++;
    }
    group.hidden = query ? !matches : group.dataset.group !== settingsGroup;
    if (!group.hidden) visible++;
  }
  for (const tab of byId("settings-nav").querySelectorAll("button")) {
    const selected = !query && tab.dataset.group === settingsGroup;
    tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
  }
  byId("settings-no-match").hidden = Boolean(visible);
}
function updateDirty() {
  let count = 0;
  for (const input of byId("settings-fields").querySelectorAll("input[name], select[name]")) {
    if (!input.disabled && input.value !== input.dataset.initialValue) count++;
  }
  unsavedSettings = Boolean(count);
  byId("settings-dirty").textContent = count ? `${count} 项修改尚未保存` : "没有未保存的修改";
}
byId("settings-filter").oninput = filterSettings;
byId("settings-filter").onkeydown = event => { if (event.key === "Enter") event.preventDefault(); };
byId("settings-form").addEventListener("input", updateDirty);
byId("settings-form").addEventListener("change", updateDirty);
byId("settings-nav").onkeydown = event => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...byId("settings-nav").querySelectorAll("button")], current = tabs.indexOf(event.target);
  if (current < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
    (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].click(); tabs[next].focus();
};
window.addEventListener("beforeunload", event => { if (unsavedSettings) { event.preventDefault(); event.returnValue = ""; } });
byId("search-proxy-mode").onchange = () => {
  const custom = byId("search-proxy-mode").value === "custom";
  const url = byId("search-proxy-url");
  byId("search-proxy-address").hidden = !custom;
  url.disabled = !custom;
};
byId("settings-refresh").onclick = async () => {
  try { await loadSettings(); updateSaveButton(); } catch (reason) { error(reason.message); }
};
byId("settings-restore").onclick = async () => {
  try {
    byId("settings-restore").disabled = true;
    await api("settings", {action: "restore", revision: settingsRevision});
    unsavedSettings = false; settingsRevision = "";
    showPanel("settings", false);
    await refreshStatus();
  } catch (reason) { error(reason.message); }
};
byId("toggle-settings").onclick = async () => {
  showPanel("settings", true);
  if (unsavedSettings && settingsRevision) return;
  settingsRevision = "";
  byId("settings-fields").inert = true;
  byId("settings").setAttribute("aria-busy", "true");
  byId("settings-filter").value = "";
  byId("settings-no-match").hidden = true;
  byId("search-proxy-fields").hidden = true;
  byId("search-proxy-url").value = "";
  byId("settings-save").disabled = true;
  try { await loadSettings(); } catch (reason) { error(reason.message); }
  finally {
    byId("settings-fields").inert = false;
    byId("settings").setAttribute("aria-busy", "false");
  }
  updateSaveButton();
};
byId("settings-form").onsubmit = async (event) => {
  event.preventDefault();
  error("");
  try {
    const values = Object.fromEntries(new FormData(event.target));
    for (const input of byId("settings-fields").querySelectorAll("input, select")) {
      if (input.value === input.dataset.initialValue) delete values[input.name];
    }
    if (byId("search-proxy-mode").value === "custom") {
      if (!byId("search-proxy-url").value.trim()) {
        settingsGroup = "搜索代理"; byId("settings-filter").value = ""; filterSettings();
        byId("search-proxy-url").focus();
        throw new Error("请输入 HTTP 代理地址，或选择其他连接方式。");
      }
      if (Object.hasOwn(values, "search_proxy_url")) values.search_proxy_mode = "custom";
    }
    await api("settings", {...values, revision: settingsRevision});
    unsavedSettings = false; settingsRevision = "";
    byId("search-proxy-url").value = "";
    showPanel("settings", false);
    await refreshStatus();
  } catch (reason) { error(reason.message); }
};
byId("toggle-add").onclick = async () => {
  adding = !adding;
  renderAdd();
  if (adding) {
    await browse();
    byId("source").focus({preventScroll: true});
    form.scrollIntoView({block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
  }
};
function renderAdd() {
  const busy = status.job?.result === "running" || state === "starting" || status.changing;
  form.hidden = busy || (!adding && Boolean(status.models?.length));
  byId("toggle-add").hidden = !status.models?.length || busy;
  byId("toggle-add").textContent = adding ? "收起添加表单" : "添加模型";
  byId("toggle-add").setAttribute("aria-expanded", String(!form.hidden));
}
function updateSaveButton() {
  byId("settings-save").disabled = !settingsRevision || state !== "ready" || status.changing || status.job?.result === "running";
}
const loadPhases = {
  starting: "正在启动推理引擎",
  weights: "正在读取模型权重",
  memory: "正在将模型数据载入内存",
  gpu: "正在填充 GPU 专家缓存",
  finalizing: "正在等待模型服务就绪"
};
function showLoadProgress(loading) {
  byId("load-progress").hidden = !loading;
  if (!loading) return;
  const phase = loadPhases[loading.phase] || loadPhases.starting;
  if (byId("load-phase").textContent !== phase) byId("load-phase").textContent = phase;
  byId("load-elapsed").textContent = "已用 " + loading.elapsed + " 秒";
}
async function refreshStatus() {
  try {
    const data = await api("status");
    const previous = state;
    status = data;
    state = data.state;
    csrf = data.csrf;
    byId("state").dataset.state = state;
    const active = data.models.find((model) => model.id === data.active);
    byId("active-summary").hidden = !active;
    if (active) {
      const display = modelDisplay(active.name);
      byId("active-summary").textContent = display.label;
      byId("current-meta").textContent = [display.quant, active.context && Number(active.context).toLocaleString("zh-CN") + " token 上下文", modelSources[active.source]].filter(Boolean).join(" · ");
    } else {
      byId("active-summary").hidden = false;
      byId("active-summary").textContent = "准备你的第一个模型";
      byId("current-meta").textContent = "从本地导入 GGUF，或让 NAS 下载模型";
    }
    byId("state").textContent = [states[state] || state, data.notice].filter(Boolean).join(" ");
    showLoadProgress(data.loading);
    showJob(data.job);
    showLibrary(data);
    renderAdd();
    byId("chat").hidden = state !== "ready";
    byId("toggle-api").hidden = state !== "ready";
    byId("toggle-settings").hidden = !data.active;
    if (state !== "ready") showPanel("ready", false);
    if (settingsActive !== data.active) {
      showPanel("settings", false);
      settingsRevision = "";
      unsavedSettings = false;
      settingsActive = data.active;
    }
    updateSaveButton();
    if (state === "ready") {
      const chatUrl = new URL("http://" + location.hostname + ":" + data.port + "/");
      chatUrl.searchParams.set("console", new URL(base, location.href).href);
      byId("chat").href = chatUrl.href;
    }
    if (!previous || JSON.stringify(roots) !== JSON.stringify(data.roots)) {
      roots = data.roots;
      options = data.downloads;
      root.replaceChildren(...roots.map((label, index) => new Option(label, String(index))));
      folder = "";
      selectFile("");
      changeSource();
      if (!form.hidden) browse();
    }
    canSubmit();
    const verb = source.value === "local" ? "导入" : "下载";
    byId("submit").textContent = data.active ? verb + "模型" : verb + "并加载";
  } catch (reason) { byId("state").textContent = reason.message; }
}
async function poll() {
  await refreshStatus();
  setTimeout(poll, 1800);
}
poll();
refreshRuntime();
