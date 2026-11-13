"""Apply the native fnOS settings to the installed Strata model profile."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlsplit


APP = Path(__file__).resolve().parent
CHOICES = {
    "context": ("--max-context", {"8192", "32768", "65536", "131072", "262144"}),
    "kv": ("--kv", {"int8", "fp16", "q4_0", "k8v4"}),
    "kv_resident": ("--kv-resident", {"4096", "8192", "16384", "32768"}),
    "prefill": ("--prefill", {"512", "1024", "2048", "4096"}),
}
NUMBERS = {
    "experts": ("--expert-cache", 0, 20000),
    "ram": ("--resident-budget-gib", 1, 90),
    "spec": ("--spec", 1, 16),
    "cache_size": ("--conversation-cache-mib", 0, 16384),
    "cache_slots": ("--conversation-cache-slots", 0, 8),
    "cache_free": ("--conversation-cache-min-free-mib", 0, 65536),
}
SEARCH_PROXY = "STRATA_SEARCH_PROXY"
PROXY_KEYS = (SEARCH_PROXY, "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")


def validate_search_proxy(value):
    invalid = "请输入 HTTP 代理地址，例如 http://代理主机:端口。账号和密码中的特殊字符需进行 URL 编码。"
    if len(value) > 1024 or not value.isascii() or re.search(r"[\x00-\x20\x7f\\]|%(?![0-9a-fA-F]{2})", value):
        raise ValueError(invalid)
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "http" and parts.hostname and parts.port not in (None, 0)
                 and parts.path in ("", "/") and not parts.query and not parts.fragment
                 and parts.netloc.count("@") <= 1
                 and (parts.username is None or (parts.username and parts.password)))
    except ValueError:
        raise ValueError(invalid) from None
    if not valid:
        raise ValueError(invalid)
    return value


def fields(revision):
    suffix = "_" + revision
    submitted = {key: value for key, value in os.environ.items()
                 if key.startswith("wizard_") and key.endswith(suffix)}
    if not submitted and any(key.startswith("wizard_") and key.count("_") >= 2
                             and len(key.rsplit("_", 1)[-1]) == 12
                             for key in os.environ):
        raise ValueError("配置已变化，请重新打开运行设置。")
    return validate_values({key.removeprefix("wizard_").removesuffix(suffix): value
                            for key, value in submitted.items()})


def validate_values(submitted):
    values = {}

    def read(name):
        return submitted.get(name, "").strip()
    for name, (_, allowed) in CHOICES.items():
        raw = read(name)
        if raw and raw != "keep":
            if raw not in allowed:
                raise ValueError(f"无效选项：{name}")
            values[name] = raw
    for name, (_, low, high) in NUMBERS.items():
        raw = read(name)
        if raw:
            if len(raw) > 8 or not raw.isascii() or not raw.isdecimal() or not low <= int(raw) <= high:
                raise ValueError(f"{name} 须为 {low} 到 {high} 的整数")
            values[name] = str(int(raw))
    for name in ("search", "mtp", "mmap"):
        raw = read(name)
        if raw and raw != "keep":
            if raw not in ("on", "off"):
                raise ValueError(f"无效选项：{name}")
            values[name] = raw
    mode = read("search_proxy_mode")
    if mode not in ("", "keep", "inherit", "direct", "custom"):
        raise ValueError("请选择有效的搜索代理模式。")
    if mode in ("inherit", "direct"):
        values["search_proxy_mode"] = mode
    elif mode == "custom":
        values["search_proxy_mode"] = mode
        raw = read("search_proxy_url")
        if raw:
            values["search_proxy_url"] = validate_search_proxy(raw)
    return values


def arg_value(args, flag):
    if flag in args:
        i = args.index(flag) + 1
        if i < len(args) and not args[i].startswith("--"):
            return args[i]
    return None


def set_arg(args, flag, value=None, *, switch=False):
    if args.count(flag) <= 1:
        if switch and (flag in args) == bool(value):
            return
        if not switch and arg_value(args, flag) == value:
            return
    while flag in args:
        i = args.index(flag)
        args.pop(i)
        if not switch and i < len(args) and not args[i].startswith("--"):
            args.pop(i)
    if switch:
        if value:
            args.append(flag)
    elif value is not None:
        args.extend((flag, value))


def search_servers(profile):
    return {**(profile.get("mcpServers") or {}), **(profile.get("mcp_servers") or {})}


def search_proxy(profile, server=None):
    if "_fnos_search_proxy" in profile:
        return profile["_fnos_search_proxy"]
    env = ((server or search_servers(profile).get("public_search") or {}).get("env") or {})
    if SEARCH_PROXY in env:
        return env[SEARCH_PROXY]
    return next((env[key] for key in PROXY_KEYS[1:] if env.get(key)), None)


def search_config(previous=None):
    directory = APP / "public-search"
    if not (directory / "search.py").is_file() or not (directory / "vendor/mcp").is_dir():
        raise ValueError("应用内的搜索工具组件缺失。")
    env = dict((previous or {}).get("env") or {})
    env.update(PYTHONPATH=str(directory / "vendor"), PYTHONNOUSERSITE="1")
    return {"command": "/usr/bin/python3", "args": ["-B", str(directory / "search.py")],
            "env": env}


def candidate(profile, values, mtp_saved):
    args = profile["args"]
    mtp_path = arg_value(args, "--mtp") or mtp_saved
    if "search" in values or "search_proxy_mode" in values:
        servers = search_servers(profile)
        previous = servers.get("public_search")
        mode = values.get("search_proxy_mode")
        proxy = search_proxy(profile, previous)
        if mode == "custom":
            proxy = values.get("search_proxy_url") or proxy
            if not proxy:
                raise ValueError("请输入搜索代理地址。")
        elif mode in ("inherit", "direct"):
            proxy = "" if mode == "direct" else None
        enabled = values.get("search", "on" if previous is not None else "off") == "on"
        if mode or (previous is not None and not enabled) or (enabled and previous is None):
            if proxy is None:
                profile.pop("_fnos_search_proxy", None)
            else:
                profile["_fnos_search_proxy"] = proxy
        profile.pop("mcpServers", None)
        if enabled:
            config = search_config(previous)
            if mode or previous is None:
                env = config["env"]
                for key in PROXY_KEYS:
                    env.pop(key, None)
                if proxy is not None:
                    env[SEARCH_PROXY] = proxy
            servers["public_search"] = config
        else:
            servers.pop("public_search", None)
        profile["mcp_servers"] = servers
    if values.get("mtp") == "on" and (not mtp_path or not Path(mtp_path).exists()):
        raise ValueError("当前模型缺少 MTP 草稿权重。")
    flags = CHOICES | NUMBERS
    for key in ("args", "args_written", "args_derived"):
        if key not in profile and key != "args":
            continue
        args = profile[key]
        for name, value in values.items():
            if name in flags:
                set_arg(args, flags[name][0], value)
        if "mmap" in values:
            set_arg(args, "--mmap-experts", values["mmap"] == "on", switch=True)
        if "mtp" in values:
            enabled = values["mtp"] == "on"
            set_arg(args, "--draft", "mtp" if enabled else "off")
            set_arg(args, "--mtp", mtp_path if enabled else None)
            profile["drafting"] = "mtp" if enabled else "off"
            profile["mtp"] = enabled
    args = profile["args"]
    resident = arg_value(args, "--kv-resident")
    context = arg_value(args, "--max-context")
    if resident and context and resident.isdecimal() and context.isdecimal() and int(resident) > int(context):
        raise ValueError("显存常驻 KV 不能超过上下文。")
    return mtp_path


def atomic(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def readback(raw):
    profile = json.loads(raw) if raw else {}
    args = profile.get("args", [])
    values = {name: arg_value(args, spec[0]) for name, spec in (CHOICES | NUMBERS).items()}
    values = {name: value for name, value in values.items()
              if isinstance(value, str) and len(value) <= 16
              and value.isascii() and all(char.isalnum() or char in "_-" for char in value)}
    servers = profile.get("mcp_servers") or profile.get("mcpServers") or {}
    if profile:
        values.update(search="on" if "public_search" in servers else "off",
                      mtp="on" if profile.get("drafting") == "mtp" or arg_value(args, "--draft") == "mtp" else "off",
                      mmap="on" if "--mmap-experts" in args else "off")
    revision = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]
    return values, revision


def sync_wizard(path, folder):
    values, revision = readback(path.read_bytes() if path.is_file() else b"")
    steps = json.loads((APP / "strata-wizard.json").read_bytes())
    for step in steps:
        for item in step["items"]:
            if "field" not in item:
                continue
            name = item["field"].removeprefix("wizard_")
            item["field"] += "_" + revision
            value = values.get(name)
            if value is None:
                continue
            if "options" in item and value not in {option["value"] for option in item["options"]}:
                item["options"][0]["label"] = f"沿用当前设置（{value}）"
            else:
                item["initValue"] = value
    target = folder / "strata-wizard.json"
    payload = (json.dumps(steps, ensure_ascii=False, indent=2) + "\n").encode()
    if not target.is_file() or target.read_bytes() != payload:
        atomic(target, payload)


def watch_wizard(path, folder):
    last = None
    while True:
        try:
            timestamp = path.stat().st_mtime_ns if path.is_file() else 0
            if timestamp != last:
                sync_wizard(path, folder)
                last = timestamp
        except (OSError, ValueError, TypeError):
            pass
        time.sleep(2)


def run_action(action):
    return subprocess.run([sys.executable, "-B", str(APP / "strata_workstation.py"), action],
                          timeout=25, check=False).returncode


def ready(profile):
    opener = build_opener(ProxyHandler({}))
    expected = arg_value(profile["args"], "--max-context")
    for _ in range(150):
        if run_action("status") != 0:
            return False
        try:
            with opener.open("http://127.0.0.1:18180/health", timeout=1) as response:
                status = json.load(response)
                if status.get("loaded") and (not expected or str(status.get("max_context")) == expected):
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return False


def apply(path, folder):
    with (path.parent / "fnos-settings.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        original = path.read_bytes()
        values = fields(readback(original)[1])
        if not values:
            return
        previous = json.loads(original)
        profile = json.loads(original)
        mtp_file = path.with_name("fnos-mtp-path")
        saved = mtp_file.read_text().strip() if mtp_file.is_file() else ""
        mtp_path = candidate(profile, values, saved)
        if profile == previous:
            return
        running = run_action("status") == 0
        if running and run_action("stop") != 0:
            raise RuntimeError("Strata 停止失败。")
        try:
            if mtp_path:
                atomic(mtp_file, (mtp_path + "\n").encode())
            atomic(path, (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode())
            if running and (run_action("start") != 0 or not ready(profile)):
                raise RuntimeError("新配置启动失败，已恢复旧配置。")
            sync_wizard(path, folder)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            if running:
                run_action("stop")
            atomic(path, original)
            sync_wizard(path, folder)
            if running and (run_action("start") != 0 or not ready(json.loads(original))):
                raise RuntimeError("旧配置已恢复，Strata 仍未就绪。") from None
            raise


def main():
    folder = Path(os.environ["TRIM_PKGETC"])
    path = folder / "engines/strata/model.json"
    if sys.argv[1] == "migrate":
        if path.is_file():
            profile = json.loads(path.read_bytes())
            if "public_search" in (profile.get("mcp_servers") or {}):
                servers = profile["mcp_servers"]
                servers["public_search"] = search_config(servers["public_search"])
                atomic(path, (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode())
        sync_wizard(path, folder)
        return
    if sys.argv[1] == "sync":
        sync_wizard(path, folder)
        return
    raw = path.read_bytes() if path.is_file() else b""
    values = fields(readback(raw)[1])
    if not values:
        return
    if not path.is_file():
        raise ValueError("请先导入 Strata 模型。")
    if sys.argv[1] == "validate":
        saved = path.with_name("fnos-mtp-path")
        candidate(json.loads(raw), values, saved.read_text().strip() if saved.is_file() else "")
    else:
        apply(path, folder)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        message = str(error)
        print(message, file=sys.stderr)
        if logfile := os.getenv("TRIM_TEMP_LOGFILE"):
            with open(logfile, "a", encoding="utf-8") as output:
                print(message, file=output)
        sys.exit(1)
