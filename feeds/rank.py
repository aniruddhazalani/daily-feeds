"""Score clusters against sections, assign each to one section per feed, cut to size."""
from __future__ import annotations

import math
import re
from datetime import datetime
from functools import lru_cache
from typing import Optional

from .config import Config, Feed, Section
from .models import Cluster, Item, Scored

KEYWORD_CAP = 10
TOPICAL_BONUS = 3
RECENCY_DIVISOR = {"news": 12, "search": 12, "discovered": 12, "paper": 24, "blog": 48, "official": 48}


@lru_cache(maxsize=None)
def term_re(term: str) -> re.Pattern:
    # Short acronyms with capitals (ICE, OPT, Fed, Meta, CM) match case-sensitively so
    # they don't hit ordinary words ("ice", "opt", "fed"). Longer terms ignore case.
    flags = 0 if (len(term) <= 5 and any(c.isupper() for c in term)) else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


def matches(term: str, text: str) -> bool:
    return bool(term_re(term).search(text))


def pick_primary(items: list[Item], weights: dict[str, float]) -> Item:
    return max(items, key=lambda it: (weights.get(it.source_id, 0), it.upvotes, not it.via_search, it.published))


def score(cfg: Config, sec: Section, cl: Cluster, now: datetime) -> tuple[Optional[Scored], str]:
    """Return (Scored, "") or (None, reason it was dropped)."""
    in_sec = [it for it in cl.items if it.source_id in sec.source_ids]
    if not in_sec:
        return None, "not from this section's sources"
    titles, snippets = cl.text()
    full = titles + "\n" + snippets
    for t in sec.exclude:
        if matches(t, full):
            return None, f"excluded by '{t}'"
    if sec.require_any and not any(matches(t, full) for t in sec.require_any):
        return None, "no required term"

    kw = 0.0
    hit_terms = []
    for term, w in sec.include.items():
        if matches(term, titles):
            kw += 2 * w
            hit_terms.append(term)
        elif snippets and matches(term, snippets):
            kw += w
            hit_terms.append(term)
    kw = min(kw, KEYWORD_CAP)

    weights = {it.source_id: cfg.sources[it.source_id].weight for it in in_sec}
    primary = pick_primary(in_sec, weights)
    topical = TOPICAL_BONUS if any(cfg.sources[it.source_id].topical for it in in_sec) else 0
    source = max(weights.values())
    coverage = 1.5 * math.log(max(len(cl.outlets), 1))
    age_h = max((now - cl.newest).total_seconds() / 3600, 0)
    recency = -age_h / RECENCY_DIVISOR.get(primary.kind, 12)
    upvotes = math.log1p(max(it.upvotes for it in cl.items)) if primary.kind == "paper" else 0.0
    total = kw + topical + source + coverage + recency + upvotes
    parts = {"keyword": round(kw, 2), "topical": topical, "source": source, "coverage": round(coverage, 2),
             "recency": round(recency, 2), "upvotes": round(upvotes, 2), "terms": hit_terms}
    s = Scored(cluster=cl, section_key=sec.key, score=round(total, 2), primary=primary, parts=parts)
    if total < sec.min_score:
        return None, f"score {total:.1f} < min {sec.min_score:g}"
    return s, ""


def bucket(kind: str) -> str:
    return {"paper": "papers", "blog": "analysis"}.get(kind, "news")


def tag_for(feed: Feed, cl: Cluster) -> Optional[str]:
    if not feed.tags:
        return None
    titles, snippets = cl.text()
    text = titles + "\n" + snippets + "\n" + " ".join(cl.outlets)  # outlet names identify single-sport sites
    best, best_n = None, 0
    for tag, terms in feed.tags.items():
        n = sum(2 if matches(t, titles) else 1 for t in terms if matches(t, text))
        if n > best_n:
            best, best_n = tag, n
    return best or "other"


def rank_feed(cfg: Config, feed: Feed, clusters: list[Cluster], now: datetime) -> dict[str, dict[str, list[Scored]]]:
    """→ {section_id: {"news": [...], "analysis": [...], "papers": [...]}}"""
    best: dict[int, Scored] = {}
    for idx, cl in enumerate(clusters):
        for sec in feed.sections:
            s, _ = score(cfg, sec, cl, now)
            if s and (idx not in best or s.score > best[idx].score):
                best[idx] = s
    out: dict[str, dict[str, list[Scored]]] = {sec.id: {"news": [], "analysis": [], "papers": []} for sec in feed.sections}
    for s in best.values():
        s.tag = tag_for(feed, s.cluster)
        out[s.section_key.split(".", 1)[1]][bucket(s.primary.kind)].append(s)
    for sec in feed.sections:
        limits = {"news": sec.max_items, "analysis": sec.max_analysis, "papers": sec.max_papers}
        for b, lst in out[sec.id].items():
            lst.sort(key=lambda s: s.score, reverse=True)
            if feed.balance and b != "papers":
                lst[:] = balance(cfg, lst, limits[b])
            del lst[limits[b]:]
    return out


OPPOSITE = {"left": "right", "right": "left"}


def balance(cfg: Config, ranked: list[Scored], limit: int) -> list[Scored]:
    """Pick up to `limit` items, best first, without letting left or right pull ahead.

    When the next-best item would put its side two ahead of the other, we first look for
    the same story from an outlet on the other side (and show that outlet instead), then
    for the best other qualifying story from the other side. If neither exists, the item
    is taken anyway: balance never drops news, it only reorders and swaps outlets.
    Center and unrated outlets don't count either way.
    """
    pool = list(ranked)
    picked: list[Scored] = []
    count = {"left": 0, "right": 0}
    while pool and len(picked) < limit:
        cand = pool[0]
        lean = cfg.lean(cand.primary.domain)
        if lean in OPPOSITE and count[lean] - count[OPPOSITE[lean]] >= 1:
            want = OPPOSITE[lean]
            same_story = [it for it in cand.cluster.items if cfg.lean(it.domain) == want]
            if same_story:
                cand.primary = max(same_story, key=lambda it: (cfg.sources[it.source_id].weight, it.published))
                lean = want
            else:
                other = next((s for s in pool if cfg.lean(s.primary.domain) == want), None)
                if other:
                    cand, lean = other, want
        pool.remove(cand)
        picked.append(cand)
        if lean in count:
            count[lean] += 1
    return picked


def explain(cfg: Config, key: str, clusters: list[Cluster], now: datetime) -> None:
    sec = cfg.section(key)
    feed = next(f for f in cfg.feeds if f.id == sec.feed_id)
    ranked = rank_feed(cfg, feed, clusters, now)[sec.id]
    shown = {id(s.cluster) for b in ranked.values() for s in b}
    rows = []
    for cl in clusters:
        if not any(it.source_id in sec.source_ids for it in cl.items):
            continue
        s, reason = score(cfg, sec, cl, now)
        title = cl.items[0].title[:90]
        if s:
            status = "SHOWN" if id(cl) in shown else "cut/other section"
            rows.append((s.score, f"{s.score:6.1f}  {status:17}  {title}\n        {s.parts}  [{s.primary.outlet}]"))
        else:
            rows.append((-99, f"{'-':>6}  {reason:17}  {title}"))
    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"\n== {key}: {len(rows)} candidates ==")
    for _, line in rows:
        print(line)
