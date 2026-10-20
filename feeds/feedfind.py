"""Find a site's RSS/Atom feed (used by check-sources and discovery)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from .fetch import HEADERS, _dt

COMMON_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/blog/feed", "/blog/rss.xml", "/news/rss.xml"]
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/xml", "text/xml")


@dataclass
class FoundFeed:
    url: str
    title: str
    entries: int
    newest: Optional[datetime]
    recent_titles: list[str]


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        if "alternate" in (a.get("rel") or "").lower() and (a.get("type") or "").lower() in FEED_TYPES and a.get("href"):
            self.feeds.append(a["href"])


def probe_feed(client: httpx.Client, url: str) -> Optional[FoundFeed]:
    try:
        r = client.get(url)
        if r.status_code != 200:
            return None
    except httpx.HTTPError:
        return None
    parsed = feedparser.parse(r.content)
    if not parsed.entries:
        return None
    dates = [d for d in (_dt(e.get("published_parsed")) or _dt(e.get("updated_parsed")) for e in parsed.entries) if d]
    return FoundFeed(
        url=str(r.url),
        title=(parsed.feed.get("title") or "").strip(),
        entries=len(parsed.entries),
        newest=max(dates) if dates else None,
        recent_titles=[(e.get("title") or "").strip() for e in parsed.entries[:5]],
    )


def find_feed(client: httpx.Client, site: str) -> Optional[FoundFeed]:
    """Return the best working feed for a site (homepage URL or bare domain)."""
    if not site.startswith("http"):
        site = "https://" + site
    candidates: list[str] = []
    try:
        r = client.get(site)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            p = _LinkParser()
            p.feed(r.text[:400_000])
            candidates += [urljoin(str(r.url), h) for h in p.feeds]
            site = str(r.url)
    except httpx.HTTPError:
        pass
    root = f"{urlparse(site).scheme}://{urlparse(site).netloc}"
    candidates += [root + p for p in COMMON_PATHS]
    if urlparse(site).path not in ("", "/"):
        candidates += [site.rstrip("/") + p for p in ("/feed", "/rss", "/rss.xml", "/index.xml")]
    best: Optional[FoundFeed] = None
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        found = probe_feed(client, url)
        if found and (best is None or (found.newest or datetime.min.replace(tzinfo=timezone.utc))
                      > (best.newest or datetime.min.replace(tzinfo=timezone.utc))):
            best = found
            if p_is_fresh(found):
                break
    return best


def p_is_fresh(f: FoundFeed, days: int = 30) -> bool:
    return bool(f.newest and (datetime.now(timezone.utc) - f.newest).days <= days)


def client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=httpx.Timeout(12.0, connect=8.0), follow_redirects=True)
