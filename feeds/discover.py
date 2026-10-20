"""Source discovery: find new sources from search results and from links in trusted blogs.

Discovered sources live in data/discovered_sources.yaml at low weight with a NEW SOURCE
badge. Promote one by copying it into feeds.yaml; mute it via ignore_sources.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import yaml

from . import feedfind
from .config import DATA_DIR, DISCOVERED_PATH, Config, Source, load_discovered, norm_domain
from .fetch import FetchResult, parse_feed
from .models import Cluster, Item
from .rank import score

log = logging.getLogger(__name__)
STATE_PATH = DATA_DIR / "discovery.json"
REJECT_DAYS = 30

# Hosting platforms, aggregators, social sites and reference sites: linked constantly,
# never a "source" in their own right.
PLATFORM_DOMAINS = {
    "news.google.com", "google.com", "youtube.com", "youtu.be", "x.com", "twitter.com", "t.co", "facebook.com",
    "instagram.com", "linkedin.com", "reddit.com", "github.com", "gist.github.com", "arxiv.org", "doi.org",
    "wikipedia.org", "en.wikipedia.org", "medium.com", "substack.com", "open.substack.com", "bit.ly", "amzn.to",
    "amazon.com", "apple.com", "apps.apple.com", "podcasts.apple.com", "play.google.com", "docs.google.com",
    "drive.google.com", "huggingface.co", "openreview.net", "archive.org", "web.archive.org", "threads.net",
    "bsky.app", "tiktok.com", "spotify.com", "open.spotify.com", "eepurl.com", "mailchimp.com", "wordpress.com",
    "feedburner.com", "feeds.feedburner.com", "creativecommons.org", "paypal.com", "patreon.com", "discord.gg",
    "discord.com", "t.me", "whatsapp.com", "wa.me", "msn.com", "yahoo.com", "finance.yahoo.com", "flipboard.com",
    "ground.news", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "ssrn.com", "papers.ssrn.com", "scholar.google.com",
    "semanticscholar.org", "zoom.us", "eventbrite.com", "lu.ma", "calendly.com", "typeform.com", "forms.gle",
}


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"hits": {}, "citations": {}, "rejected": {}}


def _days_ago(today: str, n: int) -> str:
    return (date.fromisoformat(today) - timedelta(days=n)).isoformat()


def _slug(domain: str) -> str:
    return "disc_" + re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")


GENERIC_TITLES = {"rss", "feed", "news", "home", "opinion", "blog", "latest", "articles", "metapagetitle", "untitled"}


def _is_platform(domain: str) -> bool:
    return domain in PLATFORM_DOMAINS or "cdn" in domain.split(".")[0] or any(domain.endswith("." + p) for p in ("google.com", "gstatic.com",
                                                                               "googleusercontent.com", "cloudfront.net",
                                                                               "amazonaws.com", "wp.com"))


def _qualifying_sections(cfg: Config, cl: Cluster, now: datetime) -> list[str]:
    out = []
    for sec in cfg.sections():
        s, _ = score(cfg, sec, cl, now)
        if s:
            out.append(sec.key)
    return out


def _check_candidate(cfg: Config, domain: str, sections_hint: list[str], outlet: str) -> Optional[tuple[dict, list[str]]]:
    """Find the domain's feed and confirm its recent posts fit some section. → (source dict, samples)

    A feed qualifies for a section when at least 2 of its recent posts, and at least 15% of
    them, score above that section's bar — so a firehose with one lucky match doesn't get in.
    """
    with feedfind.client() as c:
        found = feedfind.find_feed(c, domain)
    if not found or not feedfind.p_is_fresh(found, 60) or found.entries < 3:
        return None
    if norm_domain(urlparse(found.url).hostname or "") in cfg.known_domains():
        return None  # an alias of a source we already have (bbc.com → feeds.bbci.co.uk)
    tmp = Source(id="__candidate__", type="rss", kind="discovered", weight=1.0, name=found.title or domain, url=found.url)
    with feedfind.client() as c:
        r = c.get(found.url)
    parsed = parse_feed(tmp, r.content, datetime.now().astimezone())
    cfg.sources[tmp.id] = tmp
    try:
        votes: Counter = Counter()
        samples: list[str] = []
        recent = [it for it in parsed.items if (datetime.now(it.published.tzinfo) - it.published).days <= 60]
        for it in recent[:25]:
            for sec in cfg.sections():
                if sections_hint and sec.key not in sections_hint:
                    continue
                probe = replace(sec, source_ids=sec.source_ids + [tmp.id])
                s, _ = score(cfg, probe, Cluster([it]), it.published)  # judge topic, not age
                if s:
                    votes[sec.key] += 1
                    if len(samples) < 3 and it.title not in samples:
                        samples.append(it.title)
    finally:
        del cfg.sources[tmp.id]
    need = max(2, math.ceil(0.15 * min(len(recent), 25)))
    secs = [k for k, n in votes.most_common(2) if n >= need]
    if not secs:
        return None
    title = found.title.strip()
    name = outlet or (title if len(title) >= 4 and title.lower() not in GENERIC_TITLES else domain)
    return {"type": "rss", "url": found.url, "name": name, "sections": secs}, samples


def update(cfg: Config, results: dict[str, FetchResult], kept: list[Item], clusters: list[Cluster],
           shown_source_ids: set[str], today: str, now: datetime, save: bool = True) -> list[dict]:
    dcfg = cfg.settings.get("discovery", {}) or {}
    window = int(dcfg.get("window_days", 14))
    state = _load_state()
    discovered = load_discovered()
    known = cfg.known_domains() | cfg.ignore_sources

    # 1. Search hits: unknown outlets whose items qualify for a section.
    for cl in clusters:
        for it in cl.items:
            if not it.via_search or not it.domain or it.domain in known or _is_platform(it.domain):
                continue
            secs = _qualifying_sections(cfg, Cluster([it]), now)
            if not secs:
                continue
            rows = state["hits"].setdefault(it.domain, [])
            if all(h["url"] != it.url for h in rows):
                rows.append({"date": today, "sections": secs, "title": it.title, "outlet": it.outlet, "url": it.url})

    # 2. Citations: unknown domains linked from trusted blog posts.
    for it in kept:
        src = cfg.sources.get(it.source_id)
        if not src or src.discovered or it.kind != "blog":
            continue
        for d in it.links:
            if d in known or _is_platform(d):
                continue
            rows = state["citations"].setdefault(d, [])
            if all(r["post"] != it.url for r in rows):
                rows.append({"date": today, "source_id": it.source_id, "post": it.url})

    cutoff = _days_ago(today, window)
    for key in ("hits", "citations"):
        state[key] = {d: [r for r in rows if r["date"] >= cutoff] for d, rows in state[key].items()}
        state[key] = {d: rows for d, rows in state[key].items() if rows}
    state["rejected"] = {d: t for d, t in state["rejected"].items() if t >= _days_ago(today, REJECT_DAYS)}

    # 3. Retire discovered sources that went quiet, were promoted, or were muted.
    retire_cutoff = _days_ago(today, int(dcfg.get("retire_days", 30)))
    trusted_domains = set().union(*(s.domains for s in cfg.sources.values() if not s.discovered)) if cfg.sources else set()
    active = []
    for d in discovered:
        if d["id"] in shown_source_ids:
            d["last_qualified"] = today
        dom = d.get("domain", "")
        if dom in cfg.ignore_sources or dom in trusted_domains:
            log.info("discovery: dropping %s (muted or promoted)", dom)
            continue
        if d.get("last_qualified", d.get("added", today)) < retire_cutoff:
            log.info("discovery: retiring %s (no qualifying items for %s days)", dom, dcfg.get("retire_days", 30))
            continue
        active.append(d)
    discovered = active

    # 4. Promote strong candidates.
    have = {d.get("domain") for d in discovered}
    need_hits, need_days = int(dcfg.get("search_hits", 6)), int(dcfg.get("search_days", 3))
    need_cites = int(dcfg.get("citations", 2))

    def search_strong(d: str, factor: int = 1) -> bool:
        # Repeated, specialised appearances: on several different days, mostly in one
        # section. General aggregators spread across every section and are skipped.
        rows = state["hits"].get(d, [])
        days = {h["date"] for h in rows}
        top = Counter(s for h in rows for s in h["sections"]).most_common(1)
        focused = bool(top) and top[0][1] >= 0.6 * len(rows)
        return len(rows) >= need_hits * factor and len(days) >= need_days * factor and focused

    cands = []
    for d in set(state["hits"]) | set(state["citations"]):
        if d in have or d in known or d in state["rejected"] or _is_platform(d):
            continue
        n_hits = len(state["hits"].get(d, []))
        n_cites = len({r["source_id"] for r in state["citations"].get(d, [])})
        if search_strong(d) or n_cites >= need_cites:
            cands.append((n_hits + 3 * n_cites, d, n_hits, n_cites))
    cands.sort(reverse=True)
    room = max(0, int(dcfg.get("max_active", 40)) - len(discovered))
    budget = min(int(dcfg.get("max_new_per_day", 5)), room)
    for _, d, n_hits, n_cites in cands:
        if budget <= 0:
            break
        hit_secs = Counter(s for h in state["hits"].get(d, []) for s in h["sections"])
        if n_cites >= need_cites:
            citers = {r["source_id"] for r in state["citations"][d]}
            hint = [sec.key for sec in cfg.sections() if citers & set(sec.source_ids)]
            names = sorted({cfg.sources[c].name or c for c in citers if c in cfg.sources})
            reason = "cited by " + ", ".join(names[:3])
        else:
            hint = [k for k, _ in hit_secs.most_common(2)]
            reason = f"{n_hits} matching items via search"
        try:
            outlet = state["hits"][d][-1]["outlet"] if n_hits else ""
            checked = _check_candidate(cfg, d, hint, outlet)
        except Exception as e:  # network trouble on one candidate must not break the run
            log.warning("discovery: checking %s failed: %s", d, e)
            checked = None
        if checked:
            spec, samples = checked
        elif search_strong(d, factor=2):
            # No usable feed, but search keeps surfacing it: follow it via a site: query.
            outlet = state["hits"][d][-1]["outlet"]
            spec = {"type": "gnews", "query": f"site:{d}", "name": outlet,
                    "sections": [k for k, _ in hit_secs.most_common(2)]}
            samples = [h["title"] for h in state["hits"][d][-3:]]
        else:
            state["rejected"][d] = today
            log.info("discovery: rejected %s", d)
            continue
        entry = {"id": _slug(d), **spec, "kind": "discovered", "domain": d, "reason": reason,
                 "added": today, "last_qualified": today, "samples": samples}
        discovered.append(entry)
        budget -= 1
        log.info("discovery: added %s → %s (%s)", d, entry["sections"], reason)

    if save:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True))
        DISCOVERED_PATH.write_text(
            "# Written by the app. Promote a source by copying it into feeds.yaml; mute it via ignore_sources.\n"
            + yaml.safe_dump({"sources": discovered}, sort_keys=False, allow_unicode=True, width=120))

    return report(cfg, discovered, today)


def report(cfg: Config, discovered: list[dict], today: str) -> list[dict]:
    """Discovered sources added in the last `new_badge_days`, for the page panel."""
    days = int((cfg.settings.get("discovery") or {}).get("new_badge_days", 7))
    cutoff = _days_ago(today, days)
    titles = {s.key: f"{next(f.title for f in cfg.feeds if f.id == s.feed_id)} › {s.title}" for s in cfg.sections()}
    out = []
    for d in discovered:
        if d.get("added", "") < cutoff:
            continue
        loc = f'url: "{d["url"]}"' if d.get("url") else f'query: "{d["query"]}"'
        out.append({
            "name": d.get("name") or d.get("domain"),
            "domain": d.get("domain"),
            "sections": [titles.get(k, k) for k in d.get("sections", [])],
            "reason": d.get("reason", ""),
            "added": d.get("added"),
            "samples": d.get("samples", []),
            "yaml": (f'  {d["id"][5:]}: {{ type: {d["type"]}, kind: blog, name: "{d.get("name", "")}", {loc} }}\n'
                     f'  # then add {d["id"][5:]} to: {", ".join(d.get("sections", []))}'),
        })
    return out
