"""Fetch every source and normalize entries into Items."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import feedparser
import httpx

from .config import Config, Source, norm_domain
from .models import Item

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 DailyFeeds/1.0"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json, */*"}
ALT_HEADERS = {"User-Agent": "feedparser/6.0.11 +https://github.com/kurtmckee/feedparser", "Accept": "*/*"}
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_ENTRIES = 100

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
HREF_RE = re.compile(r"""href=["'](https?://[^"'#\s]+)""", re.I)
BOILERPLATE = [
    re.compile(r"The post .{0,200}? appeared first on .{0,100}?\.?$", re.I),
    re.compile(r"(Continue reading|Read more|Read the full story)\W*$", re.I),
]


@dataclass
class FetchResult:
    source_id: str
    items: list[Item] = field(default_factory=list)
    error: Optional[str] = None
    raw_count: int = 0
    feed_title: str = ""
    fallback: Optional[str] = None  # why the feed failed, when items came from the search fallback


def clean_text(raw: str, limit: int = 250) -> str:
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    text = WS_RE.sub(" ", text).strip()
    for pat in BOILERPLATE:
        text = pat.sub("", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-") + "…"
    return text


def _dt(struct) -> Optional[datetime]:
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def outbound_domains(html_text: str, own: str) -> list[str]:
    out = []
    for url in HREF_RE.findall(html_text or ""):
        d = norm_domain(urlparse(url).hostname or "")
        if d and d != own and not d.endswith("." + own) and d not in out:
            out.append(d)
    return out


def gnews_url(query: str, kind: str, settings: dict) -> str:
    days = 7 if kind in ("blog", "official") else 2
    region = settings.get("gnews_region", {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    q = quote(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl={region['hl']}&gl={region['gl']}&ceid={region['ceid']}"


def arxiv_url(src: Source) -> str:
    q = quote(src.query or "", safe=":()\"")
    return (f"https://export.arxiv.org/api/query?search_query={q}"
            f"&sortBy=submittedDate&sortOrder=descending&max_results={src.max_results}")


def parse_feed(src: Source, body: bytes, now: datetime) -> FetchResult:
    parsed = feedparser.parse(body)
    res = FetchResult(src.id, feed_title=clean_text(parsed.feed.get("title", ""), 120))
    entries = parsed.entries[:MAX_ENTRIES]
    res.raw_count = len(entries)
    if not entries and parsed.bozo:
        res.error = f"unparseable feed ({type(parsed.bozo_exception).__name__})"
        return res
    for e in entries:
        title = clean_text(e.get("title", ""), 300)
        link = e.get("link", "")
        if not title or not link:
            continue
        published = min(_dt(e.get("published_parsed")) or _dt(e.get("updated_parsed")) or now, now)
        outlet = src.name or res.feed_title
        domain = norm_domain(urlparse(link).hostname or "")
        snippet_html = e.get("summary", "")
        content_html = ""
        if e.get("content"):
            content_html = e["content"][0].get("value", "")
        via_search = False
        if src.type == "gnews":
            via_search = True
            s = e.get("source") or {}
            outlet = s.get("title") or outlet
            domain = norm_domain(urlparse(s.get("href", "")).hostname or "") or domain
            if outlet and title.endswith(" - " + outlet):
                title = title[: -len(outlet) - 3].strip()
            snippet_html = ""  # Google News descriptions are just link lists
            if src.kind != "search" and src.name:
                outlet = src.name
        if src.type == "arxiv":
            outlet = "arXiv"
            title = WS_RE.sub(" ", title)
        res.items.append(Item(
            title=title,
            url=link,
            outlet=outlet or domain,
            domain=domain,
            source_id=src.id,
            kind=src.kind,
            published=published,
            snippet=clean_text(snippet_html or content_html),
            paywall=src.paywall,
            discovered=src.discovered,
            via_search=via_search,
            links=outbound_domains(content_html or snippet_html, domain) if src.kind == "blog" else [],
        ))
    return res


def parse_hf_papers(src: Source, data, now: datetime) -> FetchResult:
    # publishedAt is the arXiv date (often days earlier); what matters is the day it was
    # featured, which is the date we asked for, so stamp items as featured ~12h ago.
    featured = now - timedelta(hours=12)
    res = FetchResult(src.id, feed_title="Hugging Face Daily Papers")
    rows = data if isinstance(data, list) else []
    res.raw_count = len(rows)
    for row in rows[:MAX_ENTRIES]:
        paper = row.get("paper") or {}
        pid = paper.get("id")
        title = WS_RE.sub(" ", row.get("title") or paper.get("title") or "").strip()
        if not pid or not title:
            continue
        res.items.append(Item(
            title=title,
            url=f"https://huggingface.co/papers/{pid}",
            outlet="HF Daily Papers",
            domain="huggingface.co",
            source_id=src.id,
            kind=src.kind,
            published=featured,
            snippet=clean_text(paper.get("summary", "")),
            upvotes=int(paper.get("upvotes") or 0),
        ))
    return res


async def _get(client: httpx.AsyncClient, url: str, headers: Optional[dict] = None) -> httpx.Response:
    last: Exception = RuntimeError("no attempt")
    for attempt in range(2):
        try:
            r = await client.get(url, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(2)
                continue
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500 and e.response.status_code != 429:
                break
            await asyncio.sleep(1.5)
    raise last


def source_url(src: Source, settings: dict) -> str:
    if src.type == "gnews":
        return gnews_url(src.query or "", src.kind, settings)
    if src.type == "arxiv":
        return arxiv_url(src)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    return (src.url or "").replace("{yesterday}", yesterday)


def fallback_query(src: Source) -> Optional[str]:
    """Google News query to use when a source's feed is blocked or empty.

    Some publishers (Substack, Indian Express, ESPN) refuse or return empty feeds to
    datacenter IPs such as GitHub Actions; their posts are still indexed by Google News.
    """
    if src.fallback:
        return src.fallback
    host = norm_domain(urlparse(src.url or "").hostname or "")
    if src.type == "rss" and host.endswith(".substack.com"):
        return f"site:{host}"
    return None


async def fetch_one(client, src: Source, settings: dict, now: datetime, sems: dict) -> FetchResult:
    res = await _fetch_direct(client, src, settings, now, sems[src.type])
    query = fallback_query(src) if (res.error or not res.items) else None
    if not query:
        return res
    fb = await _fetch_direct(client, replace(src, type="gnews", query=query), settings, now, sems["gnews"])
    if not fb.items:
        return res
    log.info("%s: feed failed (%s), used search fallback", src.id, res.error or "no items")
    fb.fallback = res.error or "no items"
    return fb


async def _fetch_direct(client, src: Source, settings: dict, now: datetime, sem: asyncio.Semaphore) -> FetchResult:
    async with sem:
        url = source_url(src, settings)
        try:
            try:
                r = await _get(client, url)
            except httpx.HTTPStatusError:
                if src.type != "rss":
                    raise
                r = None
            if src.type == "hf_papers":
                return parse_hf_papers(src, r.json(), now)
            res = parse_feed(src, r.content, now) if r is not None else None
            if src.type == "rss" and (res is None or not res.items):
                # Some sites only serve feeds to feed-reader user agents (and vice versa).
                r2 = await _get(client, url, headers=ALT_HEADERS)
                res = parse_feed(src, r2.content, now)
            if src.type == "gnews":
                await asyncio.sleep(0.4)
            elif src.type == "arxiv":
                await asyncio.sleep(3.1)  # arXiv API etiquette
            return res
        except Exception as e:  # one bad source must never break the run
            msg = f"{type(e).__name__}: {e}"
            if isinstance(e, httpx.HTTPStatusError):
                msg = f"HTTP {e.response.status_code}"
            return FetchResult(src.id, error=msg[:200])


async def fetch_sources(sources: list[Source], settings: dict) -> dict[str, FetchResult]:
    now = datetime.now(timezone.utc)
    sems = {"rss": asyncio.Semaphore(12), "hf_papers": asyncio.Semaphore(2),
            "gnews": asyncio.Semaphore(3), "arxiv": asyncio.Semaphore(1)}
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, limits=limits) as client:
        tasks = [fetch_one(client, s, settings, now, sems) for s in sources]
        results = await asyncio.gather(*tasks)
    return {r.source_id: r for r in results}


def fetch_all(cfg: Config, only: Optional[set[str]] = None) -> dict[str, FetchResult]:
    used = {sid for sec in cfg.sections() for sid in sec.source_ids}
    if only:
        used &= only
    sources = [cfg.sources[s] for s in sorted(used)]
    t0 = time.time()
    results = asyncio.run(fetch_sources(sources, cfg.settings))
    ok = sum(1 for r in results.values() if not r.error)
    log.info("fetched %d/%d sources in %.1fs", ok, len(results), time.time() - t0)
    return results
