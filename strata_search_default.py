"""Enable the workstation's public search tool by default for plain chat."""
import ast
from pathlib import Path
import sys


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
                use_mcp = bool(extra)'''
    if source.count(old) != 1 or source.count(offer) != 1:
        raise ValueError("Unexpected Strata chat handler")
    updated = source.replace(old, new, 1).replace(offer, filtered, 1)
    start = updated.index('    finalizing = False\n', updated.index('    max_rounds = int(hub.settings["max_rounds"])'))
    end = updated.index('    yield "done", {**done, "completion_tokens": total', start)
    loop = updated[start:end]
    before = '''                elif ev.kind == "content":
                    text.append(ev.text)
'''
    after = before + '''                    if finalizing and "public_search__search_web" in mcp_names:
                        continue
'''
    flush = '''        if finalizing and "public_search__search_web" in mcp_names:
            answer = re.sub(r"<tool_call>(?:(?!</?tool_call>).)*public_search__search_web.*?(?:</tool_call>|$)",
                            "", "".join(text), flags=re.S).strip()
            if not answer and not cancel.is_set():
                answer = "联网搜索未能生成最终答复。请查看已返回的搜索结果，或换一个更具体的查询。"
            if answer:
                yield "event", Event("content", answer)
'''
    if loop.count(before) != 1 or loop.count('        total += done["completion_tokens"]\n') != 1:
        raise ValueError("Unexpected Strata MCP loop")
    loop = loop.replace(before, after).replace('        total += done["completion_tokens"]\n', flush + '        total += done["completion_tokens"]\n')
    updated = updated[:start] + loop + updated[end:]
    ast.parse(updated)
    return updated


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(patch_server(path.read_text(encoding="utf-8")), encoding="utf-8")
