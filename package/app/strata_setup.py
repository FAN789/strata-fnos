"""First-run model setup behind the authenticated fnOS gateway."""

import hmac
import hashlib
import fcntl
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from strata_settings import (NUMBERS, atomic, candidate, readback, search_config, search_proxy,
                             validate_values, watch_wizard)


APP = Path(__file__).resolve().parent
APP_ID = os.environ.get("TRIM_APPNAME") or "ai-workstation"
PREFIX = "/app/" + APP_ID
DOWNLOADS = {"q2_0": "Q2_0 · 约 66 GB", "iq2_xs": "IQ2_XS · 约 68 GB",
             "iq3_xxs": "IQ3_XXS · 约 76 GB", "iq3_s": "IQ3_S · 约 84 GB"}
CONTEXTS = {"8192", "32768", "65536", "131072", "262144"}
SHARD = re.compile(r"(.+)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)
MODEL_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")
DOWNLOAD_BYTES = {"q2_0": 66_423_878_624, "iq2_xs": 68_000_000_000,
                  "iq3_xxs": 75_800_000_000, "iq3_s": 83_600_000_000}
LOAD_PHASES = (
    (b"almost ready", "finalizing"),
    (b"filling the gpu's expert cache", "gpu"),
    (b"loading the most-used experts into ram", "memory"),
    (b"reading the model's weights", "weights"),
)


def proxy_endpoint(proxy):
    try:
        parts = urlsplit(proxy)
        host = parts.hostname
        if parts.scheme in {"http", "https", "socks5", "socks5h"} and host and re.fullmatch(r"[a-zA-Z0-9.:%_-]+", host):
            host = f"[{host}]" if ":" in host else host
            port = f":{parts.port}" if parts.port is not None else ""
            return f"{parts.scheme}://{host}{port}"
    except ValueError:
        pass
    return ""


class Setup:
    def __init__(self, engine):
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.worker = None
        self.child = None
        self.job_file = engine.RUN / "model-job.json"
        self.job = json.loads(self.job_file.read_bytes()) if self.job_file.is_file() else None
        if self.job and self.job["result"] == "running":
            if self.stored_model(self.job["id"]).is_file():
                self.job["result"] = "complete"
            else:
                self.job["result"] = "interrupted"
            self.save_job()
        self.change = None
        self.settings_lock = None
        self.restart = False
        self.started_at = None
        self.start_deadline = 0
        self.notice = ""
        self.state = "starting" if engine.PROFILE.is_file() else "empty"

    def profile(self):
        path = self.engine.PROFILE
        return json.loads(path.read_bytes()) if path.is_file() else None

    def stored_model(self, identifier):
        if not MODEL_ID.fullmatch(identifier):
            raise ValueError("请选择模型库中的模型。")
        return self.engine.ETC / "profiles" / f"{identifier}.json"

    def active_id(self, profile):
        value = profile.get("_fnos_model", "")
        return value if isinstance(value, str) and MODEL_ID.fullmatch(value) else "original"

    def remember(self, profile):
        identifier = self.active_id(profile)
        path = self.stored_model(identifier)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        atomic(path, self.encode_profile(profile))

    @staticmethod
    def encode_profile(profile):
        return (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode()

    def save_job(self):
        atomic(self.job_file, self.encode_profile(self.job))

    def switch(self, profile, action):
        if self.change is not None or self.state == "starting":
            raise ValueError("请等待当前模型加载结束。")
        lock = (self.engine.ETC / "fnos-settings.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old = self.profile()
            if old:
                self.remember(old)
            pending = self.engine.ETC / "pending-model-change.json"
            atomic(pending, self.encode_profile({"previous": old, "action": action}))
            try:
                atomic(self.engine.PROFILE, self.encode_profile(profile))
            except OSError:
                pending.unlink(missing_ok=True)
                raise
        except BlockingIOError:
            lock.close()
            raise ValueError("应用中心正在保存设置，请稍后重试。") from None
        except (OSError, ValueError):
            lock.close()
            raise
        self.settings_lock = lock
        self.change = (old, action)
        self.restart = True
        self.notice = ""
        self.started_at = None
        self.state = "starting"

    def release_settings(self):
        if self.settings_lock is not None:
            self.settings_lock.close()
            self.settings_lock = None

    def activate(self, identifier):
        if self.worker is not None:
            raise ValueError("请等待模型准备完成。")
        current = self.profile()
        if current and self.active_id(current) == identifier:
            self.switch(current, "加载模型")
            return
        path = self.stored_model(identifier)
        if not path.is_file():
            raise ValueError("模型不存在。")
        profile = json.loads(path.read_bytes())
        profile["_fnos_model"] = identifier
        profile["api_key"] = self.engine.KEY.read_text().strip()
        for servers in (profile.get("mcp_servers"), profile.get("mcpServers")):
            if servers and "public_search" in servers:
                servers["public_search"] = search_config(servers["public_search"])
        self.switch(profile, "切换模型")

    def settings(self):
        raw = self.engine.PROFILE.read_bytes()
        values, _ = readback(raw)
        steps = json.loads((APP / "strata-wizard.json").read_bytes())
        items = []
        for step in steps:
            for item in step["items"]:
                if "field" not in item:
                    continue
                name = item["field"].removeprefix("wizard_")
                entry = {"id": name, "label": item["label"], "value": values.get(name, "")}
                if "options" in item:
                    entry["options"] = [choice for choice in item["options"] if choice["value"] != "keep"]
                else:
                    _, entry["min"], entry["max"] = NUMBERS[name]
                items.append(entry)
        proxy = search_proxy(json.loads(raw))
        return {"revision": hashlib.sha256(raw).hexdigest(), "items": items,
                "search_proxy_mode": "inherit" if proxy is None else "custom" if proxy else "direct",
                "search_proxy_endpoint": proxy_endpoint(proxy) if proxy else ""}

    def save_settings(self, fields):
        if self.worker is not None or self.state != "ready":
            raise ValueError("请等模型就绪后再保存。")
        raw = self.engine.PROFILE.read_bytes()
        if fields.pop("revision", "") != hashlib.sha256(raw).hexdigest():
            raise ValueError("模型配置已变化，请重新打开运行设置。")
        profile = json.loads(raw)
        before = json.loads(raw)
        mtp_path = self.engine.ETC / "fnos-mtp-path"
        saved = profile.get("_fnos_mtp", "")
        if not saved and self.active_id(profile) == "original" and mtp_path.is_file():
            saved = mtp_path.read_text().strip()
        path = candidate(profile, validate_values(fields), saved)
        if profile != before:
            if path:
                profile["_fnos_mtp"] = path
            self.switch(profile, "保存设置")

    def roots(self):
        candidates = [Path("/var/apps") / APP_ID / "shares/models",
                      self.engine.RUN / "models"]
        for name in ("TRIM_DATA_SHARE_PATHS", "TRIM_DATA_ACCESSIBLE_PATHS"):
            candidates.extend(Path(p) for p in os.environ.get(name, "").split(":") if p.startswith("/"))
        roots = {}
        for path in candidates:
            try:
                real = path.resolve(strict=True)
                if real.is_dir() and os.access(real, os.R_OK | os.X_OK):
                    roots.setdefault(real, str(path) if path in candidates[2:] else
                                     ("Strata 模型共享目录" if path == candidates[0] else "Strata 已有模型"))
            except (OSError, RuntimeError):
                continue
        return roots

    def pick(self, root, path):
        parts = Path(path).parts
        roots = list(self.roots())
        if not root.isascii() or not root.isdecimal() or len(root) > 6 or int(root) >= len(roots):
            raise ValueError("请选择飞牛授权的模型目录。")
        base = roots[int(root)]
        item = base / path
        if Path(path).is_absolute() or ".." in parts or item.resolve(strict=True) != item:
            raise ValueError("请选择授权目录内的实际文件。")
        return item

    def browse(self, query):
        root, path = query.get("root", ["0"])[0], query.get("path", [""])[0]
        folder = self.pick(root, path)
        if not folder.is_dir():
            raise ValueError("请选择目录。")
        rows = []
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_symlink() or entry.name.startswith("."):
                    continue
                directory = entry.is_dir(follow_symlinks=False)
                if directory or (entry.name.lower().endswith(".gguf") and
                                 entry.is_file(follow_symlinks=False)):
                    rows.append({"name": entry.name, "directory": directory})
                if len(rows) >= 500:
                    break
        return sorted(rows, key=lambda row: (not row["directory"], row["name"].casefold()))

    def import_model(self, fields):
        if self.worker is not None:
            raise ValueError("已有模型正在准备。")
        if self.change is not None or self.state == "starting":
            raise ValueError("请等待当前模型加载结束。")
        context = fields.get("context", "8192")
        if context not in CONTEXTS:
            raise ValueError("请选择上下文大小。")
        args = ["--context", context]
        env = dict(os.environ, STRATA_FNOS_PROGRESS="1")
        model = fields.get("model", "")
        if fields.get("source") == "download":
            if model not in DOWNLOADS:
                raise ValueError("请选择要下载的模型。")
            repository = fields.get("repository", "huggingface")
            if repository not in {"huggingface", "modelscope"}:
                raise ValueError("请选择模型下载站点。")
            env["STRATA_SOURCE"] = repository
            args.extend(("--download", "--family", "qwen", "--model", model))
            identity = f"{repository}:{model}"
            label = f"Qwen3.8 Flash Next {model.upper()}"
        elif fields.get("source") == "local":
            item = self.pick(fields.get("root", ""), fields.get("path", ""))
            if not item.is_file() or not os.access(item, os.R_OK) or item.suffix.lower() != ".gguf":
                raise ValueError("请选择 GGUF 文件。分片模型可选择任一分片。")
            if match := SHARD.fullmatch(item.name):
                stem, _, total = match.groups()
                count = int(total)
                if not 1 <= count <= 128:
                    raise ValueError("模型分片数量无效。")
                for index in range(1, count + 1):
                    shard = item.with_name(f"{stem}-{index:05d}-of-{total}.gguf")
                    if shard.is_symlink() or not shard.is_file() or not os.access(shard, os.R_OK):
                        raise ValueError(f"模型分片缺失或不可读：{shard.name}")
            args.append(str(item))
            identity = "local:" + str(item.with_name(stem + ".gguf") if match else item)
            label = item.name
            if model:
                if model not in DOWNLOADS:
                    raise ValueError("请选择支持的模型量化。")
                args.extend(("--family", "qwen", "--model", model))
            if fields.get("bf16") is True:
                args.append("--compat-bf16")
        else:
            raise ValueError("请选择模型来源。")
        gpu = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=6)
        if gpu.returncode or not gpu.stdout.strip():
            raise ValueError("未检测到 NVIDIA GPU。请检查飞牛显卡驱动。")
        identifier = hashlib.sha256(identity.encode()).hexdigest()[:24]
        if self.stored_model(identifier).is_file():
            raise ValueError("该模型已在模型库中，可直接加载。")
        args.extend(("--profile-id", identifier))
        self.job = {"id": identifier, "source": fields["source"], "name": label,
                    "model": model, "result": "running"}
        self.notice = ""
        with (self.engine.RUN / "first-model.log").open("w") as log:
            self.worker = subprocess.Popen(
                [sys.executable, "-B", str(self.engine.APP / "configure_env.py"), *args],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
            )
        self.save_job()
    def job_progress(self):
        if self.job is None:
            return None
        task = dict(self.job)
        log = self.engine.RUN / "first-model.log"
        if log.is_file():
            with log.open("rb") as handle:
                handle.seek(max(log.stat().st_size - 4096, 0))
                lines = handle.read().decode(errors="replace").splitlines()[-10:]
            notes = []
            for line in lines:
                try:
                    record = json.loads(line)
                    task["step"] = record["text"]
                    task["stage"] = record["stage"]
                except (ValueError, TypeError, KeyError):
                    notes.append(line)
            key = self.engine.KEY.read_text().strip()
            task["detail"] = "\n".join(notes[-4:])[-900:]
            if key:
                for name in ("step", "detail"):
                    if name in task:
                        task[name] = task[name].replace(key, "[已隐藏]")
        if task["source"] == "download" and self.worker is not None:
            folder = self.engine.RUN / "library" / task["id"] / "models"
            sizes = []
            for file in folder.glob("*/*.gguf*"):
                try:
                    info = file.stat()
                    if file.name.endswith(".gguf"):
                        sizes.append(info.st_size)
                    elif file.name.endswith(".gguf.part"):
                        sizes.append(min(info.st_size, info.st_blocks * 512))
                except FileNotFoundError:
                    continue
            task.update(bytes=sum(sizes), total=DOWNLOAD_BYTES[task["model"]])
        return task

    def model_info(self, identifier, profile):
        values, _ = readback(self.encode_profile(profile))
        return {"id": identifier, "name": profile.get("model_name") or identifier,
                "context": values.get("context", ""), "source": profile.get("_fnos_source", "existing")}

    def load_progress(self):
        started = self.started_at
        if started is None:
            return {"phase": "starting", "elapsed": 0}
        phase = "starting"
        try:
            with (self.engine.RUN / "model.log").open("rb") as log:
                log.seek(max(0, os.fstat(log.fileno()).st_size - 32768))
                recent = log.read(32768).lower()
            phase = next((name for marker, name in LOAD_PHASES if marker in recent), phase)
        except OSError:
            pass
        return {"phase": phase, "elapsed": max(0, int(time.monotonic() - started))}

    def status(self):
        profile = self.profile()
        active = self.active_id(profile) if profile else None
        models = {}
        for path in sorted((self.engine.ETC / "profiles").glob("*.json")):
            try:
                models[path.stem] = self.model_info(path.stem, json.loads(path.read_bytes()))
            except (OSError, AttributeError, TypeError, ValueError):
                continue
        if profile:
            models[active] = self.model_info(active, profile)
        state = self.state
        if state == "ready":
            try:
                with self.engine.OPENER.open(f"http://127.0.0.1:{self.engine.API_PORT}/health", timeout=0.5) as reply:
                    if not json.load(reply).get("loaded"):
                        state = "unloaded"
            except (OSError, ValueError):
                state = "unavailable"
        return {"state": state, "job": self.job_progress(), "notice": self.notice,
                "loading": self.load_progress() if state == "starting" else None,
                "active": active, "models": list(models.values()), "changing": self.change is not None,
                "port": self.engine.API_PORT, "roots": list(self.roots().values()), "downloads": DOWNLOADS}


class Gateway(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def verify_request(self, request, address):
        _, uid, _ = struct.unpack("3i", request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return uid in {0, pwd.getpwnam("www-data").pw_uid}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, value):
        if isinstance(value, bytes):
            kind, body = "text/html; charset=utf-8", value
        else:
            kind, body = "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def admin(self):
        uid = self.headers.get("X-Trim-Userid", "")
        if uid.isascii() and uid.isdecimal() and self.headers.get("X-Trim-Isadmin") == "true":
            return True
        self.send(403, {"error": "请使用飞牛管理员账号打开 Strata。"})
        return False

    def do_GET(self):
        if not self.admin():
            return
        url = urlsplit(self.path)
        setup = self.server.setup
        path = url.path.removeprefix(PREFIX)
        try:
            if path in {"", "/"}:
                self.send(200, (APP / "strata-setup.html").read_bytes())
            elif path == "/status":
                self.send(200, {**setup.status(), "csrf": setup.token})
            elif path == "/browse":
                self.send(200, setup.browse(parse_qs(url.query)))
            elif path == "/settings" and setup.engine.PROFILE.is_file():
                self.send(200, setup.settings())
            else:
                self.send(404, {"error": "页面不存在。"})
        except (OSError, ValueError, RuntimeError):
            self.send(400, {"error": "目录不可读。请在飞牛应用设置中确认授权。"})

    def do_POST(self):
        if not self.admin():
            return
        setup = self.server.setup
        if not hmac.compare_digest(self.headers.get("X-Strata-Setup", "").encode(), setup.token.encode()):
            self.send(403, {"error": "页面已过期，请刷新后重试。"})
            return
        try:
            path = urlsplit(self.path).path.removeprefix(PREFIX)
            if path == "/chat-key" and setup.state == "ready":
                self.send(200, {"key": setup.engine.KEY.read_text().strip()})
                return
            size = int(self.headers.get("Content-Length", "0"))
            if path not in {"/import", "/activate", "/settings"} or not 0 < size <= 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("请求无效。")
            fields = json.loads(self.rfile.read(size))
            if not isinstance(fields, dict) or any(not isinstance(value, str) for key, value in fields.items() if key != "bf16"):
                raise ValueError("模型选择无效。")
            with setup.lock:
                if path == "/import":
                    setup.import_model(fields)
                elif path == "/activate":
                    setup.activate(fields.get("id", ""))
                else:
                    setup.save_settings(fields)
            self.send(202, {"accepted": True})
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self.send(400, {"error": "无法准备模型。请检查文件权限和 NVIDIA 驱动。"})
        except ValueError as error:
            self.send(400, {"error": str(error)})


class StatusHandler(Handler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send(200, {"service": "strata-native", "model": self.server.setup.state})
        elif self.path == "/":
            self.send(200, b"<!doctype html><meta charset=utf-8><title>Strata</title>"
                           b"<h1>Strata</h1><p>Open Strata from fnOS App Center to select a model or check startup.</p>")
        else:
            self.send(404, {"error": "Open Strata from fnOS App Center."})

    def do_POST(self):
        self.send(404, {"error": "Open Strata from fnOS App Center."})


def serve(server, setup):
    server.setup = setup
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True).start()
    return server


def terminate(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=6)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def finish_job(setup):
    if setup.worker is None or setup.worker.poll() is None:
        return
    identifier = setup.job["id"]
    result = setup.worker.returncode
    setup.worker = None
    setup.job["result"] = "error" if result else "complete"
    setup.save_job()
    if not result and setup.profile() is None:
        try:
            setup.activate(identifier)
        except (OSError, ValueError):
            setup.notice = "模型已准备完成。请从模型库加载。"


def failed_start(setup):
    setup.started_at = None
    if setup.change is None:
        setup.state = "failed"
        setup.release_settings()
        return
    previous, action = setup.change
    setup.change = None
    setup.notice = action + "失败。"
    if previous:
        atomic(setup.engine.PROFILE, setup.encode_profile(previous))
        setup.notice += "正在恢复原模型与设置。"
        setup.state = "starting"
    else:
        setup.engine.PROFILE.unlink(missing_ok=True)
        setup.state = "empty"
        setup.release_settings()
    (setup.engine.ETC / "pending-model-change.json").unlink(missing_ok=True)


def supervise_workstation(engine):
    engine.initialize()
    setup = Setup(engine)
    pending = engine.ETC / "pending-model-change.json"
    if pending.is_file():
        recovery = json.loads(pending.read_bytes())
        setup.change = (recovery["previous"], recovery["action"])
        if not engine.PROFILE.is_file():
            failed_start(setup)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    threading.Thread(target=watch_wizard, args=(engine.PROFILE, engine.ETC.parents[1]), daemon=True).start()
    sock = APP / "strata-setup.sock"
    if sock.exists() and stat.S_ISSOCK(sock.lstat().st_mode):
        sock.unlink()
    fallback = None
    gpu = socket.socket()
    gpu_locked = False
    with Gateway(str(sock), Handler) as gateway, engine.Portal(("127.0.0.1", engine.PORTAL_PORT), StatusHandler) as portal:
        sock.chmod(0o666)
        serve(gateway, setup)
        try:
            serve(portal, setup)
            while not stop.is_set():
                with setup.lock:
                    finish_job(setup)
                    restart, setup.restart = setup.restart, False
                if restart:
                    terminate(setup.child)
                    setup.child = None
                    with setup.lock:
                        setup.restart = False
                start_model = (setup.child is None and setup.state in {"empty", "starting"}
                               and engine.PROFILE.is_file())
                if start_model:
                    if fallback:
                        fallback.shutdown()
                        fallback.server_close()
                        fallback = None
                    try:
                        if not gpu_locked:
                            gpu.bind(("127.0.0.1", engine.GPU_LOCK))
                            gpu.listen()
                            gpu_locked = True
                        profile = json.loads(engine.PROFILE.read_bytes())
                        offline = [] if profile.get("mcp_servers") or profile.get("mcpServers") else ["--offline"]
                        with (engine.RUN / "model.log").open("w") as log:
                            setup.child = subprocess.Popen(
                                [str(engine.APP / "control/bin/strata"), "serve", "--profile", str(engine.PROFILE),
                                 "--host", "0.0.0.0", "--port", str(engine.API_PORT), *offline, "--shutdown-timeout", "5"],
                                env=engine.runtime_env(), cwd=engine.RUN, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                            )
                        setup.started_at = time.monotonic()
                        setup.start_deadline = setup.started_at + 240
                        setup.state = "starting"
                    except (OSError, ValueError):
                        failed_start(setup)
                if setup.child is not None and setup.child.poll() is not None:
                    setup.child = None
                    failed_start(setup)
                if setup.child is not None and setup.state == "starting":
                    try:
                        with engine.OPENER.open(f"http://127.0.0.1:{engine.API_PORT}/health", timeout=0.5) as reply:
                            if json.load(reply).get("loaded"):
                                pending.unlink(missing_ok=True)
                                setup.state = "ready"
                                setup.change = None
                                setup.release_settings()
                    except (OSError, ValueError):
                        pass
                    if setup.state == "starting" and time.monotonic() >= setup.start_deadline:
                        terminate(setup.child)
                        setup.child = None
                        failed_start(setup)
                if setup.child is None and fallback is None:
                    fallback = serve(engine.Portal(("", engine.API_PORT), StatusHandler), setup)
                stop.wait(0.5)
        finally:
            setup.release_settings()
            for child in (setup.worker, setup.child):
                terminate(child)
            if fallback:
                fallback.server_close()
            gpu.close()
            sock.unlink(missing_ok=True)
