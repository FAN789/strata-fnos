"""Opt-in host shell running as the Strata application account."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time


async def capture(stream):
    output = bytearray()
    total = 0
    while chunk := await stream.read(8192):
        total += len(chunk)
        output.extend(chunk[:max(0, 16000 - len(output))])
    return output.decode("utf-8", "replace"), total > len(output)


async def run_shell(profile, workspace, command, timeout_seconds=45):
    if not isinstance(command, str) or not command.strip() or len(command) > 16000 or "\x00" in command:
        raise ValueError("命令必须为 1–16000 个字符。")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 90:
        raise ValueError("执行超时必须为 1–90 秒。")
    settings = json.loads(profile.read_bytes())
    if settings.get("_fnos_shell") is not True:
        raise ValueError("Shell 权限已关闭。")
    timeout_seconds = min(timeout_seconds, int(settings.get("_fnos_shell_timeout", 45)))
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected = settings.get("_fnos_shell_cwd", "workspace")
    if selected != "workspace" and "_fnos_shell_dirs" in settings and selected not in settings["_fnos_shell_dirs"]:
        raise ValueError("Shell 工作目录已从候选列表移除，请重新选择。")
    directory = workspace.resolve(strict=True) if selected == "workspace" else Path(selected)
    if directory.resolve(strict=True) != directory or not directory.is_dir():
        raise ValueError("Shell 工作目录已不可用，请重新选择。")
    environment = {name: value for name, value in os.environ.items()
                   if name in {"PATH", "LANG", "LC_ALL", "TZ"}}
    environment.update(PATH="/usr/local/bin:/usr/bin:/bin", HOME=str(workspace))
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        "/bin/bash", "--noprofile", "--norc", "-c", command,
        cwd=directory, env=environment, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    out, err = asyncio.create_task(capture(process.stdout)), asyncio.create_task(capture(process.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout_seconds)
    except TimeoutError:
        timed_out = True
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        stdout, stderr = await asyncio.gather(out, err)
    # Store only execution metadata: commands and their output can contain credentials.
    history = profile.parent / "shell-history.jsonl"
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "command_sha256": hashlib.sha256(command.encode()).hexdigest()[:16],
              "exit_code": process.returncode, "timed_out": timed_out, "seconds": round(time.monotonic() - started, 2)}
    try:
        rows = history.read_bytes().splitlines()[-99:] if history.is_file() else []
        from strata_settings import atomic
        atomic(history, b"\n".join(rows + [json.dumps(record).encode()]) + b"\n")
    except OSError:
        pass
    return {"exit_code": process.returncode, "timed_out": timed_out,
            "stdout": stdout[0], "stderr": stderr[0],
            "stdout_truncated": stdout[1], "stderr_truncated": stderr[1]}


def create_server(profile):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    profile = Path(profile)
    workspace = profile.parent / "shell-workspace"
    server = MCPServer("Strata Shell")
    gate = asyncio.Lock()

    @server.tool()
    async def execute(command: str, timeout_seconds: int = 90) -> dict:
        """在飞牛上以 Strata 应用账号执行 Bash 命令。检查 exit_code 和 stderr；报错时按提示说明原因，勿连续重试或用网页搜索代替本机检查。"""
        async with gate:
            try:
                return await run_shell(profile, workspace, command, timeout_seconds)
            except FileNotFoundError:
                raise ToolError("Shell 配置文件或工作目录不存在。请重新保存 Shell 设置；不要重复执行同一命令。") from None
            except PermissionError:
                raise ToolError("Strata 应用账号无权访问配置或工作目录，或无权启动命令。请检查飞牛文件授权。") from None
            except json.JSONDecodeError:
                raise ToolError("Shell 配置格式无效，请恢复上次可用设置。") from None
            except ValueError as error:
                raise ToolError(str(error)) from None
            except OSError as error:
                raise ToolError(f"Shell 启动或读取失败（系统错误 {error.errno}），请检查工作目录与应用权限。") from None

    return server


if __name__ == "__main__":
    os.umask(0o077)
    create_server(Path(sys.argv[1])).run(transport="stdio")
