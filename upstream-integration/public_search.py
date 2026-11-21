"""A single stdio MCP tool that searches public indexes."""
from base64 import b64encode
import json
from datetime import datetime, timezone
import os
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from mcp.server import MCPServer


BLENDER_MIRRORS = {"mirrors.aliyun.com", "mirror.nju.edu.cn"}
HOSTS = {"www.bing.com", "cn.bing.com", "html.duckduckgo.com", "api.github.com", "commons.wikimedia.org", *BLENDER_MIRRORS}
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
    user_agent = "Strata-fnOS/1.0 (public media search)" if urlsplit(endpoint).hostname == "commons.wikimedia.org" else "Mozilla/5.0"
    request = Request(url, headers={"User-Agent": user_agent, "Accept": accept})
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


def relevant(query, text):
    query = re.sub(r"\bsite:\S+", "", query.lower())
    words = re.findall(r"[a-z0-9]{3,}", query)
    cjk = re.findall(r"[\u3400-\u9fff]+", query)
    pairs = {word[i:i + 2] for word in cjk for i in range(len(word) - 1)}
    text = text.lower()
    if not words and not pairs:
        return True
    return (any(word in text for word in words) or
            bool(pairs and sum(pair in text for pair in pairs) >= min(2, len(pairs))))


def media_title(query):
    quoted = re.search(r'["“《]([^"”》]{2,100})["”》]', query)
    if quoted:
        return quoted[1].strip()
    return re.split(r"\s+(?=(?:19\d\d|20\d\d|1080p|720p|4k|download|short film|full movie|official)\b)"
                    r"|(?:电影|短片|高清|下载|官方)", query, maxsplit=1, flags=re.I)[0].strip()


def commons_videos(opener, query):
    title = media_title(query)
    if not 2 <= len(title) <= 100:
        return []
    raw = fetch(opener, "https://commons.wikimedia.org/w/api.php", {
        "action": "query", "generator": "search", "gsrsearch": title + " filetype:video", "gsrnamespace": 6,
        "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiextmetadatafilter": "LicenseShortName|Credit|ImageDescription", "format": "json", "formatversion": 2,
    }, accept="application/json")
    results = []
    normalized = " ".join(re.findall(r"\w+", title.casefold())).replace("_", " ")
    requested_quality = re.search(r"\b(?:4k|2160p|1080p|720p|480p)\b", query, re.I)
    for row in sorted(json.loads(raw).get("query", {}).get("pages", []), key=lambda row: row.get("index", 99)):
        name = row.get("title", "").removeprefix("File:")
        if not normalized or normalized not in " ".join(re.findall(r"\w+", name.casefold())).replace("_", " "):
            continue
        if re.search(r"\b(?:clip|trailer|test|comparison|preview|excerpt)\b|预告|片段", name, re.I):
            continue
        if requested_quality and requested_quality[0].lower() not in name.lower():
            continue
        info = next(iter(row.get("imageinfo", [])), {})
        if not info.get("mime", "").startswith("video/"):
            continue
        def metadata(key):
            return info.get("extmetadata", {}).get(key, {}).get("value", "")
        license_name = metadata("LicenseShortName")
        if not re.match(r"^(?:CC BY(?:-SA)?(?:\s|$)|CC0\b|Public domain\b)", license_name, re.I):
            continue
        credit = BeautifulSoup(metadata("Credit"), "html.parser")
        original = next((link["href"] for link in credit.select("a[href]")
                         if re.match(r"^https://[^/]+/", link["href"]) and
                         re.search(r"\.(?:webm|mp4|mkv|mov|m4v)$", urlsplit(link["href"]).path, re.I)), "")
        media = urlsplit(original or info.get("url", ""))
        if media.scheme != "https" or not media.hostname:
            continue
        uri = urlunsplit(media._replace(query="", fragment=""))
        description = BeautifulSoup(metadata("ImageDescription"), "html.parser").get_text(" ", strip=True)
        snippet = f"{description[:150]} · {license_name} · {info.get('duration', 0):.0f}s"
        results.append({"title": name[:160], "url": uri, "snippet": snippet, "source": info.get("descriptionurl", "")})
    return results


def blender_mirror_videos(opener, query, site):
    target = urlsplit("https://" + site)
    if target.netloc not in BLENDER_MIRRORS:
        return []
    title = media_title(re.sub(r"\bsite:\S+", "", query).strip())
    words = re.findall(r"[a-z0-9]+", title, re.I)
    if not words:
        return []
    base = "/blender/demo/movies/"
    directory = target.path.rstrip("/") + "/" if target.path else base + "".join(word[0] for word in words) + "/"
    if not re.fullmatch(r"/blender/demo/movies/[A-Za-z0-9_-]{1,48}/", directory):
        return []
    root = f"https://{target.hostname}{directory}"
    license_text = fetch(opener, root + "copyright.txt", {}).decode("utf-8", errors="replace")
    if not re.search(r"creative commons|creativecommons\.org/licenses/", license_text, re.I):
        return []
    requested = re.search(r"\b(?:4k|2160p|1080p|720p|480p)\b", query, re.I)
    pattern = r"[\W_]+".join(re.escape(word) for word in words)
    result = []
    for tag in BeautifulSoup(fetch(opener, root, {}), "html.parser").select("a[href]"):
        uri = urljoin(root, tag["href"])
        parts = urlsplit(uri)
        if parts.netloc != target.netloc or not parts.path.startswith(directory) or parts.query or parts.fragment:
            continue
        name = unquote(parts.path.rsplit("/", 1)[-1])
        if not re.fullmatch(pattern + r"[\W_]+(?:[0-9]{3,4}p|4k)\.(?:mov|mkv|webm|mp4)", name, re.I):
            continue
        if requested and requested[0].lower() not in name.lower():
            continue
        result.append({"title": name, "url": uri, "snippet": "Creative Commons · Blender project mirror", "source": root})
    return result


@server.tool()
def search_web(query: str, max_results: int = 5, media: bool = False) -> dict:
    """Search public web indexes and GitHub repositories. Cite returned URLs. If status is unavailable or no_results, say the search returned no verified sources and do not invent links or retry the same query."""
    query = query.strip()
    if not 1 <= len(query) <= 400:
        raise ValueError("Query must be 1–400 characters")
    max_results = max(1, min(max_results, 8))
    opener = search_opener()
    if media:
        try:
            site = re.search(r"\bsite:([^\s]+)", query)
            blender = site and urlsplit("https://" + site[1]).netloc in BLENDER_MIRRORS
            videos = blender_mirror_videos(opener, query, site[1]) if blender else commons_videos(opener, query)
            if videos:
                return {"provider": "blender_mirror" if blender else "wikimedia_commons",
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "results": videos[:max_results]}
        except (OSError, ValueError):
            pass
    project_query = re.search(r"\b(?:github|projects?|repos(?:itory|itories)?)\b|项目|仓库", query, re.I)
    providers = (github, bing, duckduckgo) if project_query else (bing, duckduckgo)
    attempts = [(provider, query) for provider in providers]
    magnet_query = len(query) <= 40 and re.search(r"磁力(?:搜索)?引擎|磁力(?:链接)?搜索工具", query)
    if magnet_query:
        attempts.append((github, "torrent search engine"))
    failed = []
    for provider, terms in attempts:
        try:
            results = []
            for title, url, snippet in provider(opener, terms):
                if not title or not url or urlsplit(url).scheme not in ("http", "https"):
                    continue
                summary = BeautifulSoup(snippet or "", "html.parser").get_text(" ", strip=True)
                description = f"{title} {url} {summary}"
                if provider is not github and not relevant(media_title(terms) if media else terms, description):
                    continue
                if (magnet_query and provider is github and terms != query
                        and not re.search(r"\b(?:search|index(?:er|ing)?)\b", f"{title} {summary}", re.I)):
                    continue
                results.append({"title": title[:200], "url": url, "snippet": summary[:420]})
            if results:
                return {"provider": provider.__name__, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "results": results[:max_results]}
        except (OSError, ValueError, ElementTree.ParseError):
            if provider.__name__ not in failed:
                failed.append(provider.__name__)
    return {"status": "unavailable" if failed else "no_results", "results": [],
            "unavailable_providers": failed,
            "message": "本次搜索未取得可核实的结果。请如实告知用户，避免重复同一查询或编造链接。"}


if __name__ == "__main__":
    server.run(transport="stdio")
