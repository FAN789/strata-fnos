"""Bounded, credential-free console diagnostics."""
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request


def snapshot(engine):
    result = {"gpus": [], "tools": [], "tool_state": "暂不可用", "experts": "加载日志暂无记录"}
    try:
        memory = dict(re.findall(r"^(MemTotal|MemAvailable):\s+(\d+)", Path("/proc/meminfo").read_text(), re.M))
        result["memory"] = {key: round(int(value) / 1048576, 1) for key, value in memory.items()}
    except OSError:
        pass
    try:
        probe = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True)
        for row in probe.stdout[:8192].splitlines()[:8]:
            parts = [p.strip() for p in row.split(",")]
            if len(parts) == 5:
                result["gpus"].append(dict(zip(("index", "name", "total", "used", "utilization"), parts)))
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with (engine.RUN / "model.log").open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 131072))
            text = handle.read().decode("utf-8", "replace")
        match = re.search(r"filling the gpu's expert cache[^\n]{0,160}", text, re.I)
        if match:
            counts = re.search(r"(\d+) experts,\s*([\d.]+) GiB", match.group(0))
            result["experts"] = f"{counts[1]} 个专家 · {counts[2]} GiB 显存" if counts else "已分配显存专家缓存"
    except OSError:
        pass
    try:
        request = Request(f"http://127.0.0.1:{engine.API_PORT}/mcp",
                          headers={"Authorization": "Bearer " + engine.KEY.read_text().strip()})
        with engine.OPENER.open(request, timeout=2) as response:
            data = json.loads(response.read(131072))
        result["tool_state"] = "已连接"
        result["tools"] = [{"name": str(server.get("name", ""))[:64],
                            "status": str(server.get("status", ""))[:32],
                            "count": len(server.get("tools") or [])} for server in data.get("servers", [])[:16]]
    except (OSError, ValueError):
        pass
    history = engine.PROFILE.parent / "shell-history.jsonl"
    try:
        shared = json.loads(engine.PROFILE.with_suffix(".shared-settings.json").read_bytes())
        result["shared"] = {key: value for key, value in shared.items()
                            if key in {"reasoning_effort", "reasoning_budget_tokens", "max_tokens"}
                            and isinstance(value, (int, str))}
    except (OSError, ValueError):
        result["shared"] = {}
    try:
        with history.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 16384))
            rows = handle.read().decode("utf-8", "replace").splitlines()[-10:]
        result["shell_history"] = [json.loads(row) for row in rows if row.startswith("{")]
    except (OSError, ValueError):
        result["shell_history"] = []
    return result
