"""Web research: search, fetch, extract, synthesise, cite."""
from __future__ import annotations

import asyncio
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import settings
from .llm import llm, offline_summarise

log = logging.getLogger("omnicraft.research")

USER_AGENT = "OmnicraftResearch/1.0 (+https://omnicraft.app/bot)"
_robots_cache: dict[str, RobotFileParser] = {}


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        elif not self._skip_depth:
            self.chunks.append(text)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.chunks)).strip()


async def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    parser = _robots_cache.get(root)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(f"{root}/robots.txt")
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except httpx.HTTPError:
            parser.parse([])
        _robots_cache[root] = parser
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return True


async def search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Serper.dev when configured, DuckDuckGo HTML otherwise."""
    if settings.SERPER_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": query, "num": min(limit, 20)},
                )
                resp.raise_for_status()
                data = resp.json()
            return [
                {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                for r in data.get("organic", [])[:limit]
            ]
        except httpx.HTTPError as exc:
            log.warning("Serper search failed, falling back: %s", exc)

    return await _duckduckgo(query, limit)


async def _duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    from urllib.parse import parse_qs, unquote
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        log.warning("Fallback search failed: %s", exc)
        return []

    results: list[dict[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', html, re.S
    ):
        href = match.group("href")
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        title = re.sub(r"<[^>]+>", "", match.group("title")).strip()
        if href.startswith("http"):
            results.append({"title": title, "url": href, "snippet": ""})
        if len(results) >= limit:
            break
    return results


async def fetch_page(url: str) -> dict[str, Any]:
    if not await _robots_allows(url):
        return {"url": url, "ok": False, "reason": "Excluded by the site's robots.txt", "text": ""}
    try:
        async with httpx.AsyncClient(
            timeout=25, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("content-type", ""):
                return {"url": url, "ok": False, "reason": "Not an HTML page", "text": ""}
            parser = _TextExtractor()
            parser.feed(resp.text)
            return {"url": url, "ok": True, "title": parser.title, "text": parser.text[:20000]}
    except httpx.HTTPError as exc:
        return {"url": url, "ok": False, "reason": str(exc)[:200], "text": ""}


async def run_research(query: str, depth: str = "basic", max_sources: int = 8) -> dict[str, Any]:
    queries = [query]
    if depth == "deep" and llm.available:
        plan = await llm.json_complete(
            f"Break this research question into 4 focused web search queries: {query}",
            system="You plan research. Return {\"queries\": [string, ...]}.",
            fallback={"queries": [query]},
        )
        queries = ([query] + [q for q in plan.get("queries", []) if isinstance(q, str)])[:5]

    seen: set[str] = set()
    hits: list[dict[str, str]] = []
    for q in queries:
        for hit in await search(q, limit=max_sources):
            if hit["url"] not in seen:
                seen.add(hit["url"])
                hits.append(hit)
    hits = hits[: max_sources if depth == "basic" else max_sources * 2]

    pages = await asyncio.gather(*(fetch_page(h["url"]) for h in hits), return_exceptions=True)
    sources = []
    for hit, page in zip(hits, pages):
        if isinstance(page, Exception) or not page.get("ok"):
            continue
        sources.append({
            "title": page.get("title") or hit["title"],
            "url": hit["url"],
            "excerpt": page["text"][:1500],
            "words": len(page["text"].split()),
        })

    if not sources:
        return {
            "query": query, "depth": depth, "sources": [],
            "report": "No readable sources came back for that query. Try narrower wording or a different angle.",
        }

    corpus = "\n\n".join(f"[{i+1}] {s['title']} ({s['url']})\n{s['excerpt']}" for i, s in enumerate(sources))

    if llm.available:
        style = (
            "Write a thorough briefing with a short summary, the key findings, disagreements between "
            "sources, and open questions."
            if depth == "deep" else
            "Write a tight briefing: three-sentence summary, then the key points."
        )
        report = await llm.complete(
            f"Research question: {query}\n\nSources:\n{corpus}\n\n{style} "
            f"Cite sources inline using their bracket numbers. Say plainly when the sources don't answer something.",
            system="You are a research analyst. Ground every claim in the supplied sources.",
            max_tokens=2400 if depth == "deep" else 1000,
        )
    else:
        report = offline_summarise(" ".join(s["excerpt"] for s in sources), sentences=12)
        report = (
            "Assembled without a language model, so this is an extract of the source text rather "
            "than a written analysis. Add OPENAI_API_KEY for a synthesised briefing.\n\n" + report
        )

    return {"query": query, "depth": depth, "sources": sources, "report": report,
            "engine": "serper" if settings.SERPER_API_KEY else "duckduckgo"}
