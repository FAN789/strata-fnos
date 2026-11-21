"""Linux regression tests for console settings and the opt-in shell."""
import ast
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "package/app"))
import strata_options
from strata_settings import arg_value, candidate, validate_values
from strata_shell import create_server, run_shell
from strata_setup import Setup
from strata_search_default import patch_output_default


class SettingsTest(unittest.TestCase):
    def profile(self):
        return {"args": ["--max-context", "32768", "--kv-resident", "20480"],
                "api_key": "fixture-private-key", "mcp_servers": {"other": {"command": "unchanged"}},
                "env": {"EXISTING": "keep"}, "_fnos_model": "fixture"}

    def test_limits_and_supported_kv(self):
        for bad in ({"kv_resident": "8192"}, {"tool_rounds": "0"}, {"shell_timeout": "91"},
                    {"thinking_budget": "1.5"}, {"ram_keep": "-1"}, {"gpu": "0,0"}):
            with self.assertRaises(ValueError):
                validate_values(bad)
        self.assertEqual(validate_values({"kv_resident": "20480"})["kv_resident"], "20480")

    def test_preserve_and_roundtrip(self):
        profile = self.profile()
        original = deepcopy(profile)
        candidate(profile, validate_values({}), "")
        self.assertEqual(profile, original)
        values = {"ram_keep": "8", "thinking_budget": "4096", "thinking_level": "high",
                  "output_limit": "8192", "tool_rounds": "12", "kv_grow": "on", "gpu": "0"}
        candidate(profile, validate_values(values), "")
        self.assertEqual(profile["api_key"], original["api_key"])
        self.assertEqual(profile["mcp_servers"], original["mcp_servers"])
        self.assertEqual(arg_value(profile["args"], "--ram-keep-gib"), "8")
        self.assertEqual(profile["env"]["EXISTING"], "keep")
        returned = {item["id"]: item["value"] for item in strata_options.fields(profile, arg_value)}
        for key, value in values.items():
            self.assertEqual(returned[key], value)
        candidate(profile, validate_values(values), "")
        self.assertEqual(profile["args"].count("--ram-keep-gib"), 1)

    def test_incompatible_context_rejected(self):
        with self.assertRaises(ValueError):
            candidate(self.profile(), validate_values({"kv_resident": "65536"}), "")

    def test_argument_precedence_and_gpu_guard(self):
        self.assertEqual(arg_value(["--prefill", "512", "--prefill=2048"], "--prefill"), "2048")
        self.assertEqual(arg_value(["--prefill=512", "--prefill", "2048"], "--prefill"), "2048")
        with self.assertRaises(ValueError):
            candidate(self.profile(), validate_values({"gpu": "0,1", "kv_grow": "on"}), "")
        with self.assertRaises(ValueError):
            validate_values({"gpu": "0,00"})

    @unittest.skipUnless(Path("/var/apps/ai-workstation/etc").is_dir(), "requires fnOS volume and application ACLs")
    def test_shell_directory_list_validation_and_removal(self):
        # Use actual volume paths on fnOS, isolated from production settings.
        parent = Path("/var/apps/ai-workstation/etc").resolve()
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            root = Path(folder)
            allowed = root / "allowed"
            allowed.mkdir()
            child = allowed / "child"
            child.mkdir()
            alias = root / "alias"
            alias.symlink_to(child, target_is_directory=True)
            values = validate_values({"shell_dirs": json.dumps([str(child)])})
            profile = self.profile()
            candidate(profile, values, "")
            self.assertEqual(profile["_fnos_shell_dirs"], [str(child)])
            profile["_fnos_shell_cwd"] = str(child)
            candidate(profile, validate_values({"shell_dirs": "[]"}), "")
            self.assertEqual(profile["_fnos_shell_cwd"], "workspace")
            for paths in ([str(child), str(child)], [str(alias)], ["/etc"], [str(child)] * 17):
                with self.assertRaises(ValueError):
                    validate_values({"shell_dirs": json.dumps(paths)})
            (root / "model.json").write_text(json.dumps(self.profile()))
            engine = SimpleNamespace(ETC=root, RUN=root, PROFILE=root / "model.json", KEY=root / "key")
            setup = Setup(engine)
            setup.state = "ready"
            setup.roots = lambda: {allowed: "fixture"}
            setup.switch = lambda profile, action: setattr(setup, "captured", profile)
            import hashlib
            revision = hashlib.sha256(engine.PROFILE.read_bytes()).hexdigest()
            setup.save_settings({"revision": revision, "shell_dirs": json.dumps([str(child)]), "shell_cwd": str(child)})
            self.assertEqual(setup.captured["_fnos_shell_cwd"], str(child))
            with self.assertRaises(ValueError):
                setup.save_settings({"revision": revision, "shell_dirs": json.dumps([str(root)])})
            # fnOS ACLs do not necessarily follow the POSIX mode bits.
            with patch("strata_setup.os.access", return_value=False):
                with self.assertRaises(ValueError):
                    setup.save_settings({"revision": revision, "shell_dirs": json.dumps([str(child)])})
            with self.assertRaises(ValueError):
                setup.pick("0", "../")
            self.assertEqual(setup.shell_directories(self.profile()), [])
            self.assertEqual(setup.directories({"root": ["0"]})["directories"], [{"name": "child", "path": str(child)}])

    def test_default_workspace_through_app_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "real"
            real.mkdir()
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            profile = alias / "model.json"
            profile.write_text(json.dumps({"_fnos_shell": True}))
            result = asyncio.run(run_shell(profile, alias / "workspace", "pwd"))
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["stdout"].strip(), str(real / "workspace"))

    def test_shell_profile_paths_across_entry_points(self):
        from strata_settings import shell_config
        base = Path("/vol1/@appconf/fixture")
        engine = base / "engines/strata"
        for folder in (base, engine):
            with patch.dict(os.environ, {"TRIM_PKGETC": str(folder)}):
                self.assertEqual(shell_config()["args"][-1], str(engine / "model.json"))
                profile = self.profile()
                candidate(profile, {"shell": "on"}, "", engine / "model.json")
                self.assertEqual(profile["mcp_servers"]["strata_shell"]["args"][-1], str(engine / "model.json"))

    def test_shell_tool_errors_remain_actionable(self):
        from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            async def call():
                return await create_server(path).call_tool("execute", {"command": "printf fixture-ok", "timeout_seconds": 5})
            for content, expected in ((None, "配置文件或工作目录不存在"), ("{}", "Shell 权限已关闭"), ("{", "配置格式无效")):
                if content is not None:
                    path.write_text(content)
                with self.assertRaises(ToolError) as caught:
                    asyncio.run(call())
                self.assertNotIsInstance(caught.exception, UnexpectedToolError)
                self.assertIn(expected, str(caught.exception))
            path.write_text(json.dumps({"_fnos_shell": True}))
            result = asyncio.run(call())
            self.assertIn("fixture-ok", str(result))

    def test_shell_migration_preserves_model_settings(self):
        import strata_settings
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            engine = base / "engines/strata"
            (engine / "profiles").mkdir(parents=True)
            original = {**self.profile(), "_fnos_shell": True}
            original["mcp_servers"]["strata_shell"] = {"command": "/usr/bin/python3", "args": ["-B", "strata_shell.py", str(engine / "engines/strata/model.json")]}
            for path in (engine / "model.json", engine / "profiles/saved.json"):
                path.write_text(json.dumps(original))
            previous = {**self.profile(), "_fnos_shell": False}
            (engine / "previous-settings.json").write_text(json.dumps(previous))
            with patch.dict(os.environ, {"TRIM_PKGETC": str(base)}), patch.object(sys, "argv", ["settings", "migrate"]), patch.object(strata_settings, "sync_wizard"):
                strata_settings.main()
            for path in (engine / "model.json", engine / "profiles/saved.json"):
                updated = json.loads(path.read_bytes())
                self.assertEqual(updated["mcp_servers"]["strata_shell"]["args"][-1], str(engine / "model.json"))
                updated["mcp_servers"]["strata_shell"] = original["mcp_servers"]["strata_shell"]
                self.assertEqual(updated, original)
            self.assertEqual(json.loads((engine / "previous-settings.json").read_bytes()), previous)

    def test_output_default_preserves_explicit_and_shared(self):
        source = '''class Service:
    def with_shared(self, req: dict, api: str) -> dict:
        s = self.shared
        effort = self.effort_default()
        if not s and not effort:
            return req
        req = dict(req)
        if "max_tokens" in s and not req.get("max_tokens") and not req.get("max_completion_tokens"):
            req["max_tokens"] = s["max_tokens"]
        return req
def start(cfg, svc):
    if cfg.get("reasoning_budget_tokens") is not None:
        pass
'''
        scope = {}
        exec(patch_output_default(source), scope)
        service = scope["Service"]()
        service.shared, service.effort_default = {}, lambda: None
        scope["start"]({"_fnos_output_limit": 4096}, service)
        self.assertEqual(service.with_shared({}, "openai"), {"max_tokens": 4096})
        self.assertEqual(service.with_shared({"max_tokens": 32}, "openai"), {"max_tokens": 32})
        self.assertEqual(service.with_shared({"max_completion_tokens": 64}, "openai"), {"max_completion_tokens": 64})
        service.shared = {"max_tokens": 128}
        self.assertEqual(service.with_shared({}, "openai"), {"max_tokens": 128})

    def test_restore_revision_and_model_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            profile = self.profile()
            (path / "model.json").write_text(json.dumps(profile))
            (path / "key").write_text("current-private-key")
            engine = SimpleNamespace(ETC=path, RUN=path, PROFILE=path / "model.json", KEY=path / "key")
            setup = Setup(engine)
            setup.state = "ready"
            setup.switch = lambda profile, action: setattr(setup, "captured", profile)
            import hashlib
            revision = hashlib.sha256(engine.PROFILE.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                setup.save_settings({"revision": "stale", "output_limit": "100"})
            previous = deepcopy(profile)
            previous["_fnos_model"] = "different"
            (path / "previous-settings.json").write_text(json.dumps(previous))
            with self.assertRaises(ValueError):
                setup.save_settings({"revision": revision, "action": "restore"})
            previous["_fnos_model"] = "fixture"
            (path / "previous-settings.json").write_text(json.dumps(previous))
            setup.save_settings({"revision": revision, "action": "restore"})
            self.assertEqual(setup.captured["api_key"], "current-private-key")

    def test_shell_gate_timeout_and_private_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            profile = path / "model.json"
            profile.write_text('{}')
            with self.assertRaises(ValueError):
                asyncio.run(run_shell(profile, path / "workspace", "echo should-not-run"))
            profile.write_text(json.dumps({"_fnos_shell": True, "_fnos_shell_timeout": 1}))
            result = asyncio.run(run_shell(profile, path / "workspace", "printf fixture-secret; pwd", 90))
            self.assertEqual(result["exit_code"], 0)
            self.assertIn(str(path / "workspace"), result["stdout"])
            result = asyncio.run(run_shell(profile, path / "workspace", "sleep 10", 90))
            self.assertTrue(result["timed_out"])
            history = (path / "shell-history.jsonl").read_text()
            self.assertNotIn("fixture-secret", history)
            self.assertNotIn("sleep 10", history)
            self.assertEqual((path / "shell-history.jsonl").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
