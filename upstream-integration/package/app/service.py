import fcntl
import html
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import socketserver
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

APP = Path(__file__).resolve().parent
VAR = Path(os.environ["TRIM_PKGVAR"])
ETC = Path(os.environ["TRIM_PKGETC"])
RUN = VAR / "native"
KEY = ETC / "api-key"
PROFILE = ETC / "model.json"
LOCAL_ONLY = ETC / "workstation-local-only"
PID = RUN / "pid"
PORTAL_PORT = 18081
API_PORT = 18082
GPU_LOCK = 18189
OPENER = build_opener(ProxyHandler({}))


def initialize():
    os.umask(0o077)
    for path in (RUN, RUN / "home", RUN / "data", RUN / "install"):
        path.mkdir(mode=0o700, exist_ok=True)
    try:
        with KEY.open("x", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
    except FileExistsError:
        pass


def runtime_env():
    engine = APP / "components/engine/0.1.59-linux-x86_64-cuda13"
    return {
        **os.environ,
        "HOME": str(RUN / "home"),
        "XDG_CONFIG_HOME": str(RUN / "home/config"),
        "XDG_DATA_HOME": str(RUN / "home/data"),
        "XDG_STATE_HOME": str(RUN / "home/state"),
        "XDG_CACHE_HOME": str(RUN / "home/cache"),
        "STRATA_HOME": str(RUN / "home"),
        "STRATA_INSTALL_DIR": str(RUN / "install"),
        "STRATA_DATA_DIR": str(RUN / "data"),
        "STRATA_COMPONENTS_DIR": str(APP / "components"),
        "STRATA_ENGINE": str(engine / "strata"),
        "STRATA_ENGINE_BACKEND": "cuda",
        "LD_LIBRARY_PATH": str(engine),
        "PYTHONPATH": str(APP / "control"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] != "Z" and int(fields[3]) == pid:
            return f"{pid} {fields[19]}"
    except (OSError, IndexError, ValueError):
        pass
    return None


def current_pid():
    try:
        record = PID.read_text().strip()
        pid = int(record.split()[0])
        return pid if record == identity(pid) else None
    except (OSError, IndexError, ValueError):
        return None


class Portal(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        mode = self.server.mode
        if mode == "starting" and time.monotonic() >= self.server.next_probe:
            self.server.next_probe = time.monotonic() + 2
            try:
                with OPENER.open(f"http://127.0.0.1:{API_PORT}/health", timeout=1) as reply:
                    health = json.load(reply)
                    if health.get("status") == "ok":
                        self.server.mode = mode = "ready"
            except (OSError, URLError, ValueError):
                pass
        if self.path == "/healthz":
            body = json.dumps({"service": "strata-native", "model": mode})
            content_type = "application/json"
        elif self.path == "/":
            title, detail = {
                "empty": ("等待导入模型", "在飞牛 SSH 控制台运行下方命令，填入 NAS 上与 Strata 兼容的 GGUF 文件或目录，完成后在应用中心重启 Strata。"),
                "starting": ("正在加载模型", "请稍后刷新。如果一直未就绪，请查看应用日志。"),
                "busy": ("显卡正由 AI 创作使用", "请先在飞牛应用中心停止 AI 创作，再重新启动 Strata。"),
                "ready": ("推理服务已就绪", "打开 Strata 聊天，或将 API 地址填入兼容 OpenAI 的客户端。"),
                "failed": ("模型启动失败", "请检查应用日志中的错误，修正后在应用中心重新启动。"),
            }[mode]
            command = 'sudo /var/apps/strata-native/target/configure "/你的模型目录"'
            log_path = "/var/apps/strata-native/var/native/model.log"
            if mode == "empty":
                extra = f"<pre>{html.escape(command)}</pre>"
            elif mode == "ready":
                extra = (f'<p><a id="chat">打开 Strata 聊天</a></p><p id="api"></p>'
                         f'<script>const base="http://"+location.hostname+":{API_PORT}";'
                         'document.querySelector("#chat").href=base+"/";'
                         'document.querySelector("#api").textContent=base+"/v1";</script>'
                         '<p>API 密钥可在 NAS 上运行以下命令查看。</p>'
                         '<pre>sudo cat /var/apps/strata-native/etc/api-key</pre>')
            else:
                extra = f"<pre>sudo tail -n 80 {log_path}</pre>"
            body = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strata</title><style>
body{{background:#111a27;color:#eaf1fa;font:16px system-ui;margin:10vh auto;padding:0 24px;max-width:680px}}
main{{background:#1b283a;border-radius:18px;padding:28px}} h1{{margin-top:0}}
a{{color:#8dd7ff}} pre{{overflow:auto;background:#101722;padding:12px;border-radius:8px}}
</style><main><h1>Strata</h1><h2>{title}</h2><p>{detail}</p>{extra}</main></html>"""
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def supervise():
    initialize()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with Portal(("", PORTAL_PORT), Handler) as http, socket.socket() as gpu:
        http.timeout = 0.25
        http.mode = "empty"
        http.next_probe = 0
        child = None
        can_launch = False
        if PROFILE.is_file():
            try:
                gpu.bind(("127.0.0.1", GPU_LOCK))
                gpu.listen()
                can_launch = True
            except OSError:
                http.mode = "busy"
        if can_launch:
            http.mode = "starting"
            with (RUN / "model.log").open("w") as log:
                try:
                    child = subprocess.Popen(
                        [str(APP / "control/bin/strata"), "serve", "--profile", str(PROFILE),
                         "--host", "127.0.0.1" if LOCAL_ONLY.is_file() else "0.0.0.0",
                         "--port", str(API_PORT), "--offline",
                         "--shutdown-timeout", "5"],
                        env=runtime_env(), cwd=RUN, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT,
                    )
                except OSError as error:
                    gpu.close()
                    log.write(f"Strata could not start: {error}\n")
                    http.mode = "failed"
        while not stopping:
            if child and child.poll() is not None:
                child = None
                gpu.close()
                http.mode = "failed"
            http.handle_request()
        if child and child.poll() is None:
            try:
                child.wait(timeout=7)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def start():
    if current_pid():
        return 0
    with (RUN / "service.log").open("w") as log:
        child = subprocess.Popen(
            [sys.executable, "-B", __file__, "supervise"], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    record = identity(child.pid)
    if record:
        PID.write_text(record + "\n")
    for _ in range(50):
        if child.poll() is not None:
            break
        try:
            with OPENER.open(f"http://127.0.0.1:{PORTAL_PORT}/healthz", timeout=0.3) as reply:
                if json.load(reply).get("service") == "strata-native" and child.poll() is None:
                    return 0
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.1)
    stop()
    return 1


def stop():
    pid = current_pid()
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(90):
            if not current_pid():
                break
            time.sleep(0.1)
        if current_pid():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    PID.unlink(missing_ok=True)
    return 0


def main(action):
    if action == "supervise":
        supervise()
        return 0
    if action == "status":
        return 0 if current_pid() else 3
    initialize()
    with (RUN / "lifecycle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return {"start": start, "stop": stop}[action]()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    sys.exit(main(action) if action in {"start", "stop", "status", "supervise"} else 1)
