"""A single stdio MCP tool that searches public indexes."""
from base64 import b64encode
import json
from datetime import datetime, timezone
import os
import re
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from mcp.server import MCPServer


HOSTS = {"www.bing.com", "cn.bing.com", "html.duckduckgo.com", "api.github.com"}
LIMIT = 512 * 1024
server = MCPServer("strata-public-search")


class SearchRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password or parts.port:
            raise ValueError("Search provider redirected outside the public indexes")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SearchProxy(ProxyHandler):
    def proxy_open(self, req, proxy, _scheme):
        # A configured proxy must not silently fall back to direct requests
        # when the host's inherited NO_PROXY matches a search provider.
        parts = urlsplit(proxy)
        if parts.username is not None and parts.password is not None:
            basic = b64encode(f"{unquote(parts.username)}:{unquote(parts.password)}".encode()).decode("ascii")
            req.add_header("Proxy-authorization", "Basic " + basic)
        req.set_proxy(parts.netloc.rsplit("@", 1)[-1], parts.scheme)
        return None


def search_opener():
    configured = os.environ.get("STRATA_SEARCH_PROXY")
    if configured is None:
        proxy = ProxyHandler()
    elif configured:
        proxy = SearchProxy({"https": configured})
    else:
        proxy = ProxyHandler({})
    return build_opener(proxy, SearchRedirect())


def fetch(opener, endpoint, params, accept="text/html, application/rss+xml"):
    url = endpoint + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": accept})
    with opener.open(request, timeout=8) as response:
        body = response.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError("Search response is too large")
    return body


def bing(opener, query):
    data = fetch(opener, "https://www.bing.com/search", {"q": query, "format": "rss"})
    return [(item.findtext("title"), item.findtext("link"), item.findtext("description"))
            for item in ElementTree.fromstring(data).findall("./channel/item")]


def duckduckgo(opener, query):
    data = fetch(opener, "https://html.duckduckgo.com/html/", {"q": query})
    rows = []
    for item in BeautifulSoup(data, "html.parser").select(".result"):
        link = item.select_one(".result__a")
        snippet = item.select_one(".result__snippet")
        if link:
            url = link.get("href", "")
            url = parse_qs(urlsplit(url).query).get("uddg", [url])[0]
            rows.append((link.get_text(" ", strip=True), url, snippet.get_text(" ", strip=True) if snippet else ""))
    return rows


def github(opener, query):
    terms = re.sub(r"\bsite:(?:www\.)?github\.com\b|\b(?:github|projects?|repos(?:itory|itories)?|open[- ]source)\b|相关的?项目|开源项目|项目|仓库", " ", query, flags=re.I)
    words = re.findall(r"[\w.-]+", terms)
    if not words:
        return []
    data = fetch(opener, "https://api.github.com/search/repositories", {
        "q": " ".join(words) + " in:name,description,readme is:public", "per_page": 8},
        accept="application/vnd.github+json")
    items = json.loads(data).get("items", [])
    return [(item.get("full_name"), item.get("html_url"), item.get("description")) for item in items]


@server.tool()
def search_web(query: str, max_results: int = 5) -> dict:
    """Search public web indexes and GitHub repositories. Cite returned URLs. If status is unavailable or no_results, say the search returned no verified sources and do not invent links or retry the same query."""
    query = query.strip()
    if not 1 <= len(query) <= 400:
        raise ValueError("Query must be 1–400 characters")
    max_results = max(1, min(max_results, 8))
    opener = search_opener()
    terms = re.findall(r"[a-z0-9]{3,}", re.sub(r"\bsite:\S+", "", query.lower()))
    project_query = re.search(r"\b(?:github|projects?|repos(?:itory|itories)?)\b|项目|仓库", query, re.I)
    providers = (github, bing, duckduckgo) if project_query else (bing, duckduckgo)
    failed = []
    for provider in providers:
        try:
            results = []
            for title, url, snippet in provider(opener, query):
                if not title or not url or urlsplit(url).scheme not in ("http", "https"):
                    continue
                summary = BeautifulSoup(snippet or "", "html.parser").get_text(" ", strip=True)
                if provider is not github and terms and not any(term in f"{title} {url} {summary}".lower() for term in terms):
                    continue
                results.append({"title": title[:200], "url": url, "snippet": summary[:420]})
            if results:
                return {"provider": provider.__name__, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "results": results[:max_results]}
        except (OSError, ValueError, ElementTree.ParseError):
            failed.append(provider.__name__)
    return {"status": "unavailable" if failed else "no_results", "results": [],
            "unavailable_providers": failed,
            "message": "本次搜索未取得可核实的结果。请如实告知用户，避免重复同一查询或编造链接。"}


if __name__ == "__main__":
    server.run(transport="stdio")
