"""Enable the workstation's public search tool by default for plain chat."""
import ast
from pathlib import Path
import sys


SEARCH_OUTPUT_FILTER = r'''from html import unescape as unescape_tool_markup
from serve.frontend import ToolCall


PUBLIC_SEARCH = "public_search__search_web"
SEARCH_NAMES = {PUBLIC_SEARCH, "web_search"}

SEARCH_REQUEST = re.compile(
    r"^\s*(?:"
    r"(?:请|麻烦|帮我|给我|能否|可以)?\s*(?:帮我\s*)?(?:先\s*)?(?:用|去|实际)?\s*"
    r"(?:联网\s*(?:搜索|搜一下|搜|查证|查一下|查询|查|核实)|"
    r"(?:在线|网上|上网)\s*(?:搜索|搜一下|搜|查证|查一下|查询|查|核实))"
    r"\s*(?:(?:一下|下)\s*)?(?:(?:核实|查证|验证)\s*)?(?:(?:这条|以下|下面的)\s*(?:查询|问题|信息|说法)\s*)?"
    r"|(?:(?:please|can you|could you)\s+)*(?:use\s+(?:web search|the internet)\s+to\s+(?:verify|check|find)"
    r"|search\s+(?:the\s+web|(?:the\s+)?internet|online)|(?:look\s+up|find|verify|check)\s+online)"
    r"(?:\s+(?:for|whether))?\b)\s*[:：,，]?\s*",
    re.I,
)
SEARCH_NOTICES = {
    "disabled": ("本轮未执行联网搜索，因此无法核实。当前请求关闭了搜索工具。",
                 "Web search was disabled for this request. I could not verify this online."),
    "invalid_query": ("本轮未执行联网搜索。请提供 1–400 字的搜索内容。",
                      "Web search was not run. Provide a search query of 1–400 characters."),
    "unavailable": ("本轮联网搜索未能获得可用结果，无法核实。", "Web search is unavailable. I could not verify this online."),
    "no_results": ("本次联网搜索未找到可核实的来源。", "The web search returned no verifiable sources."),
}


def explicit_search(messages):
    """Recognize search commands in the current user turn, never in quoted history."""
    last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    text = last.get("content") or ""
    if isinstance(text, list):
        text = " ".join(p["text"] for p in text if isinstance(p, dict) and isinstance(p.get("text"), str))
    match = SEARCH_REQUEST.match(text)
    if not match:
        return None
    query = re.split(r"[。！？\n]|[.!?]\s", text[match.end():], maxsplit=1)[0].strip()
    return query, bool(re.search(r"[\u3400-\u9fff]", match.group()))


def search_outcome(result):
    if result.get("ok"):
        try:
            payload = json.loads(result["text"])
            if isinstance(payload, dict):
                if payload.get("results"):
                    return "results"
                if payload.get("status") == "no_results":
                    return "no_results"
        except (KeyError, TypeError, ValueError):
            pass
    return "unavailable"


def search_notice(status, chinese):
    yield "event", Event("content", SEARCH_NOTICES[status][0 if chinese else 1])
    yield "done", {"finish": "stop", "completion_tokens": 0}


def search_arguments(body):
    """Read a complete fallback call, accepting only the bundled search schema."""
    body = body.strip()
    try:
        call = json.loads(body)
    except ValueError:
        # Qwen can start writing JSON and switch to XML after the function name.
        match = re.fullmatch(
            r'(?:<function\s*=\s*|\{\s*")([\w]+)\s*>(.*?)</function>\s*\}?',
            body, re.I | re.S,
        )
        if not match:
            return None
        name, payload = match.groups()
        args = {}
        parameter = re.compile(r'<parameter\s*=\s*(query|max_results)\s*>(.*?)</parameter>', re.I | re.S)
        pos = 0
        for item in parameter.finditer(payload):
            key, value = item.groups()
            key = key.lower()
            if payload[pos:item.start()].strip() or key in args:
                return None
            args[key] = value.strip()
            pos = item.end()
        if payload[pos:].strip():
            return None
        if "max_results" in args:
            if not re.fullmatch(r"[0-9]{1,3}", args["max_results"]):
                return None
            args["max_results"] = int(args["max_results"])
    else:
        if not isinstance(call, dict):
            return None
        name, args = call.get("name"), call.get("arguments")
    if not isinstance(name, str) or name.lower() not in SEARCH_NAMES or not isinstance(args, dict):
        return None
    query = args.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 400:
        return None
    if args.keys() - {"query", "max_results"}:
        return None
    result = {"query": query.strip()}
    if "max_results" in args:
        count = args["max_results"]
        if type(count) is not int:
            return None
        result["max_results"] = min(8, max(1, count))
    return result


class SearchMarkupFilter:
    """Keep generated tool envelopes out of both text channels across stream chunks."""

    opening = re.compile(r'\\?(?:<tool_call>|&lt;tool_call&gt;)', re.I)
    closing = re.compile(r'\\?(?:</tool_call>|&lt;/tool_call&gt;)', re.I)
    markers = ("<tool_call>", "&lt;tool_call&gt;", "\\<tool_call>", "\\&lt;tool_call&gt;")
    closing_markers = tuple(marker.replace("tool_call", "/tool_call") for marker in markers)
    max_body = 8192

    def __init__(self):
        self.pending = ""
        self.in_call = False
        self.discard_body = False
        self.removed = False
        self.arguments = None

    @staticmethod
    def hold_length(text, markers):
        return max((length for marker in markers for length in range(1, len(marker))
                    if text.endswith(marker[:length])), default=0)

    def feed(self, text, final=False):
        self.pending += text
        visible = []
        while self.pending:
            if not self.in_call:
                start = self.opening.search(self.pending)
                if not start:
                    hold = self.hold_length(self.pending.lower(), self.markers)
                    end = len(self.pending) - hold
                    # A bare backslash or angle bracket can be ordinary answer text.
                    if final and hold and self.pending[end:].lstrip("\\").lower() in ("", "<", "&"):
                        end = len(self.pending)
                    visible.append(self.pending[:end])
                    self.removed |= final and end < len(self.pending)
                    self.pending = "" if final else self.pending[end:]
                    break
                visible.append(self.pending[:start.start()])
                self.pending = self.pending[start.end():]
                self.in_call = True
                self.removed = True
                self.discard_body = False
            end = self.closing.search(self.pending)
            if end:
                if not self.discard_body and end.start() <= self.max_body and self.arguments is None:
                    body = unescape_tool_markup(self.pending[:end.start()])
                    body = re.sub(r'\\(?=</?(?:function|parameter)\b)', '', body, flags=re.I)
                    self.arguments = search_arguments(body)
                self.pending = self.pending[end.end():]
                self.in_call = False
                continue
            if final:
                self.pending = ""
            elif self.discard_body or len(self.pending) > self.max_body:
                self.discard_body = True
                hold = self.hold_length(self.pending.lower(), self.closing_markers)
                self.pending = self.pending[len(self.pending) - hold:]
            break
        return "".join(visible)


def filter_search_events(events, recover_search):
    """Recover only a search offered by the server, leaving native calls intact."""
    filters = {kind: SearchMarkupFilter() for kind in ("reasoning", "content")}
    visible_text = {kind: False for kind in filters}
    called_tool = False
    for kind, value in events:
        if kind == "event" and value.kind in filters:
            text = filters[value.kind].feed(value.text or "")
            visible_text[value.kind] |= bool(text.strip())
            if text:
                yield "event", value if text == value.text else Event(value.kind, text)
            continue
        if kind == "event" and value.kind in {"tool_start", "tool_call"}:
            called_tool = True
        if kind == "done":
            for channel, cleaner in filters.items():
                tail = cleaner.feed("", final=True)
                visible_text[channel] |= bool(tail.strip())
                if tail:
                    yield "event", Event(channel, tail)
            content, reasoning = filters["content"], filters["reasoning"]
            # Calls quoted in an explanation or code sample must not be executed.
            args = content.arguments or (None if visible_text["reasoning"] else reasoning.arguments)
            finish = value.get("finish")
            if recover_search and args and not visible_text["content"] and not called_tool and finish == "stop":
                call = ToolCall(PUBLIC_SEARCH, args)
                yield "event", Event("tool_start", call=call)
                yield "event", Event("tool_call", call=call)
            elif not visible_text["content"] and not called_tool and finish not in {"cancel", "disconnect"}:
                if content.removed or reasoning.removed:
                    yield "event", Event("content", "本轮没有生成可用的回复。若需要联网搜索，请检查搜索设置后重试。")
        yield kind, value


'''


def patch_server(source):
    old = '            use_mcp = req.get("strata_mcp") is True and svc.mcp is not None      # the web app\'s opt-in (serve/mcp.py)'
    new = '''            choice = tool_choice_of(req.get("tool_choice"))[0]
            explicit = explicit_search(messages) if validator is None else None
            default_search = (
                "strata_mcp" not in req and validator is None
                and choice == "auto" and not tools
                and not force and not self._foreign_origin()
            )
            use_mcp = svc.mcp is not None and choice != "none" and not (explicit and force) and (
                req.get("strata_mcp") is True or default_search
            )'''
    offer = "                use_mcp = bool(extra)"
    filtered = '''                if default_search:
                    extra = [tool for tool in extra if tool["name"] == "public_search__search_web"]
                if explicit is None and not own and any(tool["name"] == "public_search__search_web" for tool in extra):
                    messages = [{"role": "system", "content": (
                        "For public web searches call the declared public_search__search_web tool with one query string. "
                        "When you have a result, answer in normal text and cite its URLs. "
                        "If you have no results, say so. Never print tool-call markup in the answer."
                    )}, *messages]
                use_mcp = bool(extra)'''
    if source.count(old) != 1 or source.count(offer) != 1:
        raise ValueError("Unexpected Strata chat handler")
    updated = source.replace(old, new, 1).replace(offer, filtered, 1)
    run = "            yield from self._run(ids, thinking, tools, max_new, sampling, cancel, force, declared_only, deferred)"
    if updated.count(run) != 1 or updated.count("def openai_chunks(") != 1:
        raise ValueError("Unexpected Strata generation path")
    updated = updated.replace("def openai_chunks(", SEARCH_OUTPUT_FILTER + "def openai_chunks(", 1)
    signature = """    def run(self, ids, thinking, tools, max_new, sampling, cancel, force=None,
            declared_only=False, deferred=False) -> Iterator[tuple[str, object]]:"""
    loop = "        for kind, x in svc.run(ids, thinking, tools, max_new, sampling, cancel, declared_only=True):"
    if updated.count(signature) != 1 or updated.count(loop) != 1:
        raise ValueError("Unexpected Strata MCP loop")
    updated = updated.replace(signature, signature.replace("deferred=False", "deferred=False, recover_search=False"), 1)
    updated = updated.replace(run, """            events = self._run(ids, thinking, tools, max_new, sampling, cancel, force, declared_only, deferred)
            yield from filter_search_events(events, recover_search)""", 1)
    updated = updated.replace(loop, """        for kind, x in svc.run(ids, thinking, tools, max_new, sampling, cancel, declared_only=True,
                               recover_search=not finalizing and PUBLIC_SEARCH in mcp_names):""", 1)
    mcp_signature = "                 mcp_names):"
    generation = """        for kind, x in svc.run(ids, thinking, tools, max_new, sampling, cancel, declared_only=True,
                               recover_search=not finalizing and PUBLIC_SEARCH in mcp_names):"""
    mcp_result = '            results.append(r.get("model_content", r["text"]) if svc.vision is not None else r["text"])'
    final = "        if rounds >= max_rounds:"
    handler = '''            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, force=force, req=req, cancel=cancel)
            _debug_req("openai", req, messages, tools, max_new, thinking, len(ids))
            run = run_with_mcp(svc, svc.mcp, messages, tools, kw, ids, thinking, max_new, max_req, req, cancel,
                               {t["name"] for t in extra}) if use_mcp else None'''
    if any(updated.count(anchor) != 1 for anchor in (mcp_signature, generation, mcp_result, final, handler)):
        raise ValueError("Unexpected Strata explicit search path")
    updated = updated.replace(mcp_signature, "                 mcp_names, explicit=None):", 1)
    updated = updated.replace(generation, """        if explicit is not None and rounds == 0:
            query, chinese = explicit
            call = ToolCall(PUBLIC_SEARCH, {"query": query})
            events = iter((("event", Event("tool_start", call=call)),
                           ("event", Event("tool_call", call=call)),
                           ("done", {"finish": "stop", "completion_tokens": 0})))
        else:
            events = svc.run(ids, thinking, tools, max_new, sampling, cancel, declared_only=True,
                             recover_search=not finalizing and PUBLIC_SEARCH in mcp_names)
        for kind, x in events:""", 1)
    boundary = '        if cancel.is_set() or len(results) < len(calls):'
    if updated.count(boundary) != 1:
        raise ValueError("Unexpected Strata MCP result boundary")
    updated = updated.replace(boundary, '''            if explicit is not None:
                status = search_outcome(r)
                if status != "results" and not cancel.is_set():
                    yield from search_notice(status, chinese)
                    return
''' + boundary, 1)
    updated = updated.replace(final, """        if explicit is not None or rounds >= max_rounds:""", 1)
    system = '''            messages.insert(system_end, {"role": "system", "content":
                f"The tool-use limit of {max_rounds} rounds has been reached. No tools are available for this final "
                "reply. Answer the user's original request in their language using the results already obtained. "
                "Explain any gaps in the available evidence. Do not request or emit further tool calls."})'''
    if updated.count(system) != 1:
        raise ValueError("Unexpected Strata MCP final prompt")
    updated = updated.replace(system, '''            if explicit is not None:
                instruction = (
                    "The requested web search has already run. Answer in the user's language using the tool results. "
                    "Cite only URLs from those results and explain gaps in the evidence. No further tools are available."
                )
                # Qwen accepts a single leading system message.
                prior = "\\n\\n".join(m["content"] for m in messages[:system_end]
                                    if isinstance(m.get("content"), str))
                messages[:system_end] = [{"role": "system", "content":
                                          "\\n\\n".join(filter(None, (prior, instruction)))}]
            else:
''' + "\n".join("    " + line for line in system.splitlines()), 1)
    updated = updated.replace('            yield "mcp", {"event": "limit", "max_rounds": max_rounds}',
                              '''            if explicit is None:
                yield "mcp", {"event": "limit", "max_rounds": max_rounds}''', 1)
    updated = updated.replace(handler, '''            names = {t["name"] for t in extra} if use_mcp else set()
            if explicit is not None:
                query, chinese = explicit
                ids, thinking = [], False
                if choice == "none" or req.get("strata_mcp") is False:
                    run = search_notice("disabled", chinese)
                elif not 1 <= len(query) <= 400:
                    run = search_notice("invalid_query", chinese)
                elif PUBLIC_SEARCH not in names or force or self._foreign_origin():
                    run = search_notice("unavailable", chinese)
                else:
                    run = run_with_mcp(svc, svc.mcp, messages, tools, kw, ids, thinking,
                                       max_new, max_req, req, cancel, names, explicit=explicit)
            else:
                ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, force=force, req=req, cancel=cancel)
                _debug_req("openai", req, messages, tools, max_new, thinking, len(ids))
                run = run_with_mcp(svc, svc.mcp, messages, tools, kw, ids, thinking, max_new, max_req, req, cancel,
                                   names) if use_mcp else None''', 1)
    ast.parse(updated)
    return updated


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(patch_server(path.read_text(encoding="utf-8")), encoding="utf-8")
