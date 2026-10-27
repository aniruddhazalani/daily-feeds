"""`python -m feeds build`: the daily pipeline."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import discover, rank, render
from .config import DATA_DIR, Config, load_discovered
from .fetch import fetch_all
from .filter import cluster_items, filter_items, load_seen, save_seen, seen_keys
from .group import group_stories
from .models import Scored

log = logging.getLogger(__name__)
SNAPSHOT_DIR = DATA_DIR / "days"


MAX_RELATED = 10


def related_json(cfg: Config, s: Scored) -> list[dict]:
    """Other articles on the same story: one row per distinct outlet + headline, best sources first."""
    p = s.primary
    seen = {p.url, (p.outlet.lower(), p.title.lower())}
    rows = []
    for it in sorted(s.cluster.items, key=lambda it: (-cfg.sources[it.source_id].weight if it.source_id in cfg.sources else 0,
                                                       -it.published.timestamp())):
        key = (it.outlet.lower(), it.title.lower())
        if it.url in seen or key in seen:
            continue
        seen |= {it.url, key}
        rows.append({"title": it.title, "url": it.url, "outlet": it.outlet, "lean": cfg.lean(it.domain),
                     "published": it.published.isoformat(), "paywall": it.paywall})
    return rows


def item_json(cfg: Config, s: Scored) -> dict:
    p = s.primary
    related = related_json(cfg, s)
    # Google News items have no snippet; borrow one from another article on the same story.
    snippet = p.snippet or next((it.snippet for it in s.cluster.items if it.snippet), "")
    return {
        "title": p.title,
        "url": p.url,
        "outlet": p.outlet,
        "kind": "new" if p.discovered else p.kind,
        "published": p.published.isoformat(),
        "snippet": snippet,
        "related": related[:MAX_RELATED],
        "related_more": max(0, len(related) - MAX_RELATED),
        "outlets": len(s.cluster.outlets),
        "paywall": p.paywall,
        "lean": cfg.lean(p.domain),
        "score": s.score,
        "tag": s.tag,
        "upvotes": max(it.upvotes for it in s.cluster.items),
    }


def top_stories(cfg: Config, candidates: list[tuple[Scored, str, str]]) -> list[dict]:
    """The day's most widely covered stories across every feed (headlines only, no repeats)."""
    tcfg = cfg.settings.get("top_stories") or {}
    count, min_outlets = int(tcfg.get("count", 15)), int(tcfg.get("min_outlets", 3))
    best: dict[int, tuple[Scored, str, str]] = {}
    for s, where, anchor in candidates:  # a story can be shown in two feeds; keep its best placement
        if id(s.cluster) not in best or s.score > best[id(s.cluster)][0].score:
            best[id(s.cluster)] = (s, where, anchor)
    ranked = sorted(best.values(), key=lambda t: (len(t[0].cluster.outlets), t[0].score), reverse=True)
    picked = [t for t in ranked if len(t[0].cluster.outlets) >= min_outlets][:count]
    return [{**item_json(cfg, s), "where": where, "anchor": anchor} for s, where, anchor in picked]


def run(cfg: Config, explain: Optional[str] = None, discover_sources: bool = True, save: bool = True, out: str = "site") -> int:
    tz = ZoneInfo(cfg.settings.get("timezone", "UTC"))
    now = datetime.now(timezone.utc)
    today = now.astimezone(tz).date().isoformat()

    results = fetch_all(cfg)
    items = [it for r in results.values() for it in r.items]
    seen = load_seen()
    kept, fstats = filter_items(cfg, items, seen, today, now)
    clusters = cluster_items(kept, float(cfg.settings.get("dedupe_threshold", 88)))
    grouping = cfg.settings.get("story_grouping") or {}
    if grouping.get("enabled", True):
        clusters = group_stories(clusters, similarity=float(grouping.get("similarity", 0.4)),
                                 min_shared=int(grouping.get("min_shared", 2)),
                                 max_hours_apart=float(grouping.get("max_hours_apart", 48)))
    log.info("items: %d fetched → %d kept (%s) → %d stories", len(items), len(kept), fstats, len(clusters))

    if explain:
        rank.explain(cfg, explain, clusters, now)
        return 0

    feeds_out = []
    shown_sources: set[str] = set()
    top_candidates: list[tuple[Scored, str, str]] = []  # (story, "Feed › Section", anchor)
    for feed in cfg.feeds:
        ranked = rank.rank_feed(cfg, feed, clusters, now)
        sections = []
        for sec in feed.sections:
            buckets = ranked[sec.id]
            top_candidates += [(s, f"{feed.title} › {sec.title}", f"{feed.id}-{sec.id}") for s in buckets["news"]]
            for lst in buckets.values():
                for s in lst:
                    shown_sources |= s.cluster.source_ids
                    for it in s.cluster.items:
                        for k in seen_keys(it):
                            seen.setdefault(k, today)
            sec_out = {"id": sec.id, "title": sec.title,
                       **{b: [item_json(cfg, s) for s in lst] for b, lst in buckets.items()}}
            if feed.balance:
                shown = sec_out["news"] + sec_out["analysis"]
                sec_out["leans"] = {l: sum(1 for i in shown if i["lean"] == l) for l in ("left", "center", "right")}
            sections.append(sec_out)
        tags = sorted({i["tag"] for sec in sections for b in ("news", "analysis", "papers") for i in sec[b] if i["tag"]})
        feeds_out.append({"id": feed.id, "title": feed.title, "tags": tags, "sections": sections})

    top = top_stories(cfg, top_candidates)

    if discover_sources and (cfg.settings.get("discovery") or {}).get("enabled", True):
        new_sources = discover.update(cfg, results, kept, clusters, shown_sources, today, now, save=save)
    else:
        new_sources = discover.report(cfg, load_discovered(), today)

    problems, fallbacks = [], []
    for sid, r in sorted(results.items()):
        src = cfg.sources[sid]
        if r.error or not r.items:
            problems.append({"id": sid, "name": src.name or sid, "error": r.error or "no items"})
        elif r.fallback:
            fallbacks.append({"id": sid, "name": src.name or sid, "error": r.fallback})

    snapshot = {
        "date": today,
        "generated_at": now.isoformat(),
        "timezone": str(tz),
        "site_title": cfg.settings.get("site_title", "Daily Feeds"),
        "top": top,
        "feeds": feeds_out,
        "new_sources": new_sources,
        "problems": problems,
        "fallbacks": fallbacks,
        "stats": {"sources": len(results), "sources_ok": len(results) - len(problems), "items": len(items),
                  "kept": len(kept), "stories": len(clusters),
                  "shown": sum(len(sec[b]) for f in feeds_out for sec in f["sections"] for b in ("news", "analysis", "papers"))},
    }

    if save:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{today}.json").write_text(json.dumps(snapshot, indent=1, ensure_ascii=False))
        save_seen(seen, today, int(cfg.settings.get("seen_days", 14)))
        keep_from = (date.fromisoformat(today) - timedelta(days=int(cfg.settings.get("archive_days", 60)))).isoformat()
        for f in SNAPSHOT_DIR.glob("*.json"):
            if f.stem < keep_from:
                f.unlink()

    snapshots = sorted(SNAPSHOT_DIR.glob("*.json")) if SNAPSHOT_DIR.exists() else []
    days = [json.loads(f.read_text()) for f in snapshots]
    if not save or not any(d["date"] == today for d in days):
        days = [d for d in days if d["date"] != today] + [snapshot]
    render.render_site(Path(out), days, int(cfg.settings.get("show_first", 5)), cfg.settings.get("refresh"))
    log.info("rendered %d stories across %d feeds → %s/index.html", snapshot["stats"]["shown"], len(feeds_out), out)
    return 0
