import ast
from dataclasses import dataclass, field
from html import escape
import json
import os
from pathlib import Path
import re
import tarfile
import threading
import time
from typing import Iterator
import unittest
import uuid

from build_fpk import CONTROL_ASSET
from strata_search_default import patch_server


QUERY = "Starta LLM inference optimization technique 2026"
HYBRID = f'''<tool_call>
{{"public_search__search_web>
<parameter=query>
{QUERY}
</parameter>
<parameter=max_results>
10
</parameter>
</function>
</tool_call>'''


class SearchRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = Path(os.environ.get("STRATA_CONTROL_ARCHIVE", str(Path(__file__).resolve().parent / CONTROL_ASSET)))
        with tarfile.open(archive) as bundle:
            server = patch_server(bundle.extractfile("serve/server.py").read().decode())
            frontend = ast.parse(bundle.extractfile("serve/frontend.py").read())
            openai_api = ast.parse(bundle.extractfile("serve/server_parts/openai_api.py").read())
        tree = ast.parse(server)
        service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Service")
        service.body = [node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == "run"]
        event_names = {"ToolCall", "Event"}
        names = {"run_with_mcp", "search_arguments", "SearchMarkupFilter", "filter_search_events",
                 "openai_chunks", "openai_collect", "explicit_search", "search_notice", "search_outcome",
                 "latest_user_text", "tool_payload", "search_sources"}
        nodes = [node for node in frontend.body if isinstance(node, ast.ClassDef) and node.name in event_names]
        nodes += [node for node in openai_api.body if getattr(node, "name", None) == "openai_collect"]
        nodes += [node for node in tree.body if (
            node is service or getattr(node, "name", None) in names
            or isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in
                {"PUBLIC_SEARCH", "SEARCH_NAMES", "SEARCH_REQUEST", "SEARCH_NOTICES"}
                for target in node.targets
            )
            or isinstance(node, ast.ImportFrom) and node.module == "html"
        )]
        cls.runtime = dict(globals(), top_logprobs=lambda _: None)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "serve/server.py", "exec"), cls.runtime)

    def filtered(self, channel, text, *, recover=True, finish="stop", native=False):
        event = self.runtime["Event"]
        items = [("event", event(channel, character)) for character in text]
        if native:
            items.append(("event", event("tool_call", call=self.runtime["ToolCall"]("client_tool", {}))))
        items.append(("done", {"finish": finish}))
        return [item for kind, item in self.runtime["filter_search_events"](items, recover) if kind == "event"]

    def test_real_failure_and_other_wire_formats_in_both_channels(self):
        xml = HYBRID.replace('{"public_search__search_web>', "<function=web_search>")
        basic_json = "<tool_call>" + json.dumps({"name": "web_search", "arguments": {"query": QUERY}}) + "</tool_call>"
        for text in (HYBRID, xml, escape(xml), xml.replace("<", "\\<"), basic_json):
            for channel in ("content", "reasoning"):
                with self.subTest(text=text[:45], channel=channel):
                    items = self.filtered(channel, text)
                    self.assertEqual([item.kind for item in items], ["tool_start", "tool_call"])
                    self.assertEqual(items[-1].call.name, "public_search__search_web")
                    self.assertEqual(items[-1].call.arguments["query"], QUERY)
                    self.assertLessEqual(items[-1].call.arguments.get("max_results", 5), 8)

    def test_disabled_unfinished_invalid_and_quoted_calls_never_execute(self):
        cases = (
            (HYBRID, {"recover": False}), (HYBRID, {"finish": "cancel"}),
            (HYBRID.removesuffix("</tool_call>"), {}),
            (HYBRID.replace(QUERY, ""), {}),
            (HYBRID.replace("public_search__search_web", "unrelated_tool"), {}),
            (HYBRID.replace("<parameter=query>", "<parameter=url>"), {}),
            (HYBRID.replace(QUERY, "x" * 9000), {}),
            (f"Example:\n```\n{HYBRID}\n```", {}),
        )
        for text, options in cases:
            with self.subTest(text=text[:35], options=options):
                items = self.filtered("content", text, **options)
                self.assertTrue(all(not item.call and "<tool_call" not in item.text for item in items))

    def test_ordinary_text_and_native_tool(self):
        items = self.filtered("content", "保留文本。\\", native=True)
        self.assertEqual("".join(item.text for item in items), "保留文本。\\")
        self.assertEqual([item.call.name for item in items if item.call], ["client_tool"])
        calls = [item.call.name for item in self.filtered("content", HYBRID, native=True) if item.call]
        self.assertEqual(calls, ["client_tool"])

    def test_explicit_search_is_derived_from_latest_user_turn(self):
        explicit = self.runtime["explicit_search"]
        for prompt in (f'请用联网搜索核实这条查询："{QUERY}"。请用中文回答。',
                       f"Please search the web for \"{QUERY}\". Cite sources."):
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            self.assertEqual(explicit(messages)[0], f'"{QUERY}"')
            self.assertIsNone(explicit(messages + [{"role": "user", "content": "是什么？"}]))
        self.assertIsNone(explicit([{"role": "user", "content": "不要联网搜索，直接回答。"}]))
        for prompt in ("搜索磁力引擎", "帮我搜一下磁力引擎", "搜磁力引擎"):
            self.assertEqual(explicit([{"role": "user", "content": prompt}]), ("磁力引擎", True))
        self.assertIsNone(explicit([{"role": "user", "content": "搜索工具怎么用？"}]))

    def test_explicit_search_runs_before_generation_and_errors_skip_model(self):
        scope = self.runtime
        tool_name = scope["PUBLIC_SEARCH"]

        class Service:
            vision = None
            calls = []

            def prepare(self, messages, tools, *args, **kwargs):
                self.calls.append("prepare")
                assert tools is None
                assert messages[-1]["role"] == "tool"
                assert [i for i, m in enumerate(messages) if m["role"] == "system"] == [0]
                assert "Keep existing instructions." in messages[0]["content"]
                return [2], True, 32

            def run(self, *args, **kwargs):
                self.calls.append("run")
                if status == "reasoning_only":
                    yield "event", scope["Event"]("reasoning", "只输出了思考过程。")
                else:
                    yield "event", scope["Event"]("content", "参考搜索结果。")
                yield "done", {"finish": "stop", "completion_tokens": 4}

        for status, ok, expected in (("no_results", True, "未找到可核实"),
                                     ("unavailable", True, "未能获得可用结果"),
                                     ("unavailable", False, "未能获得可用结果"),
                                     ("results", True, "参考搜索结果"),
                                     ("reasoning_only", True, "联网搜索返回的来源")):
            with self.subTest(status=status, ok=ok):
                svc = Service()
                svc.calls = []
                has_results = status in {"results", "reasoning_only"}
                payload = {"status": status, "results": [{"url": "https://example.com"}] if has_results else []}

                class Hub:
                    name = "public_search"
                    settings = {"max_rounds": 2}

                    def routes(self):
                        return {tool_name: (self, "search_web")}

                    def call(self, name, args, cancel):
                        svc.calls.append("search")
                        assert args == {"query": QUERY}
                        return dict(ok=ok, text=json.dumps(payload), chars=64, truncated=False, ms=1)

                messages = [{"role": "system", "content": "Keep existing instructions."},
                            {"role": "user", "content": QUERY}]
                events = list(scope["run_with_mcp"](svc, Hub(), messages,
                              [{"name": tool_name}], {}, [], False, 32, 32, {}, threading.Event(),
                              {tool_name}, explicit=(QUERY, True)))
                self.assertEqual(svc.calls, ["search", "prepare", "run"] if has_results else ["search"])
                self.assertIn(expected, "".join(value.text for kind, value in events if kind == "event"))
                if has_results:
                    self.assertTrue(any(kind == "event" and value.kind == "content" and
                                        "https://example.com" in value.text for kind, value in events))
                self.assertEqual([value["event"] for kind, value in events if kind == "mcp"],
                                 ["start", "call", "result"])

    def test_openai_stream_and_json_use_same_mcp_round_trip(self):
        scope = self.runtime
        event = scope["Event"]
        search_name = scope["PUBLIC_SEARCH"]

        class Service(scope["Service"]):
            keep_awake = None
            engine = vision = None

            def _run(self, ids, *args):
                if ids == [1]:
                    yield "event", event("reasoning", "正在核实。")
                    yield "event", event("content", HYBRID)
                else:
                    yield "event", event("content", "本次搜索未找到可核实的来源。")
                yield "done", {"finish": "stop", "completion_tokens": 3}

            def prepare(self, messages, *args, **kwargs):
                assert messages[-2]["tool_calls"][0]["function"]["arguments"]["query"] == QUERY
                assert messages[-1]["content"] == '{"status":"no_results","results":[]}'
                return [2], True, 500

            def model_for(self, req):
                return "test"

        class Hub:
            name = "public_search"
            settings = {"max_rounds": 2}
            calls = []

            def routes(self):
                return {search_name: (self, "search_web")}

            def call(self, name, args, cancel):
                self.calls.append((name, args))
                return dict(ok=True, text='{"status":"no_results","results":[]}', chars=36,
                            truncated=False, ms=1)

        svc, hub, cancel = Service(), Hub(), threading.Event()
        run = scope["run_with_mcp"](svc, hub, [{"role": "user", "content": QUERY}], [{"name": search_name}],
                                    {}, [1], True, 500, 500, {}, cancel, {search_name})
        chunks = list(scope["openai_chunks"](svc, {}, [1], True, None, 500, cancel, run=run))
        response = scope["openai_collect"](iter(chunks))
        self.assertEqual(hub.calls, [(search_name, {"query": QUERY, "max_results": 8})])
        self.assertEqual([c["strata_mcp"]["event"] for c in chunks if c.get("strata_mcp")],
                         ["start", "call", "result"])
        message = response["choices"][0]["message"]
        self.assertEqual(message["content"], "本次搜索未找到可核实的来源。")
        self.assertEqual(message["reasoning_content"], "正在核实。")
        self.assertNotIn("<tool_call>", json.dumps(chunks))


if __name__ == "__main__":
    unittest.main()
