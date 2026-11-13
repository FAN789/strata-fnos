"""Enable the workstation's public search tool by default for plain chat."""
import ast
from pathlib import Path
import sys


SEARCH_OUTPUT_FILTER = '''def filter_search_markup(chunks):
    """Keep malformed search calls out of streamed Chat Completions text."""
    opening, closing = "<tool_call>", "</tool_call>"
    target = re.compile(r'^(?:\\s*<function\\s*=\\s*(?:web_search|public_search__search_web)\\s*>|\\s*\\{\\s*"name"\\s*:\\s*"(?:web_search|public_search__search_web)")')
    pending = ""
    hidden_call = False
    visible_answer = False
    last_content = None
    for chunk in chunks:
        choices = chunk.get("choices", []) if chunk else []
        choice = choices[0] if choices else {}
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if not content:
            if choice.get("finish_reason") is not None and last_content is not None:
                remainder = pending
                if pending.startswith(opening) and target.match(pending[len(opening):]):
                    hidden_call, remainder = True, ""
                if hidden_call and not visible_answer and not remainder.strip():
                    remainder = "联网搜索未完成。请重新发送问题，或在聊天设置中确认已启用联网搜索。"
                if remainder:
                    yield {**last_content, "choices": [{**last_content["choices"][0], "delta": {"content": remainder}}]}
            yield chunk
            continue
        last_content = chunk
        pending += content
        visible = ""
        while pending:
            index = pending.find(opening)
            if index < 0:
                suffix = next((i for i in range(len(opening) - 1, 0, -1) if pending.endswith(opening[:i])), 0)
                if suffix:
                    visible, pending = visible + pending[:-suffix], pending[-suffix:]
                else:
                    visible, pending = visible + pending, ""
                break
            visible += pending[:index]
            pending = pending[index:]
            end = pending.find(closing, len(opening))
            if end < 0:
                break
            end += len(closing)
            if target.match(pending[len(opening):end]):
                hidden_call = True
            else:
                visible += pending[:end]
            pending = pending[end:]
        if visible:
            visible_answer |= bool(visible.strip())
            yield {**chunk, "choices": [{**choice, "delta": {**delta, "content": visible}}]}


'''


def patch_server(source):
    old = '            use_mcp = req.get("strata_mcp") is True and svc.mcp is not None      # the web app\'s opt-in (serve/mcp.py)'
    new = '''            choice = tool_choice_of(req.get("tool_choice"))[0]
            default_search = (
                "strata_mcp" not in req and validator is None
                and choice == "auto" and not tools
                and not force and not self._foreign_origin()
            )
            use_mcp = svc.mcp is not None and choice != "none" and (
                req.get("strata_mcp") is True or default_search
            )'''
    offer = "                use_mcp = bool(extra)"
    filtered = '''                if default_search:
                    extra = [tool for tool in extra if tool["name"] == "public_search__search_web"]
                if not own and any(tool["name"] == "public_search__search_web" for tool in extra):
                    messages = [{"role": "system", "content": (
                        "For public web searches call the declared public_search__search_web tool with one query string. "
                        "When you have a result, answer in normal text and cite its URLs. "
                        "If you have no results, say so. Never print tool-call markup in the answer."
                    )}, *messages]
                use_mcp = bool(extra)'''
    if source.count(old) != 1 or source.count(offer) != 1:
        raise ValueError("Unexpected Strata chat handler")
    updated = source.replace(old, new, 1).replace(offer, filtered, 1)
    handler = '            chunks = self._capture(chunks, "openai")'
    if updated.count(handler) != 1:
        raise ValueError("Unexpected Strata Chat Completions handler")
    updated = updated.replace('def openai_chunks(', SEARCH_OUTPUT_FILTER + 'def openai_chunks(', 1)
    updated = updated.replace(handler, '''            if validator is None and not top_logprobs(req) and not own:
                chunks = filter_search_markup(chunks)
''' + handler, 1)
    ast.parse(updated)
    return updated


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(patch_server(path.read_text(encoding="utf-8")), encoding="utf-8")
