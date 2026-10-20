"""Time windows, already-shown filter, ignore list, and duplicate clustering."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from rapidfuzz import fuzz, process

from .config import DATA_DIR, Config, norm_domain
from .models import Cluster, Item

SEEN_PATH = DATA_DIR / "seen.json"
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|cmpid|ito|ocid|smid|taid|src$|at_)", re.I)
TITLE_NORM = re.compile(r"[^a-z0-9 ]+")


def canonical_url(url: str) -> str:
    u = urlparse(url.strip())
    host = norm_domain(u.hostname or "")
    path = re.sub(r"/(amp|amp\.html)/?$", "/", u.path).rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(u.query) if not TRACKING_PARAMS.match(k)])
    return urlunparse(("https", host, path, "", query, ""))


def norm_title(title: str) -> str:
    return TITLE_NORM.sub(" ", title.lower()).strip()


def title_key(title: str) -> str:
    return " ".join(norm_title(title).split())[:120]


# ---------------------------------------------------------------- seen store
def load_seen(path: Path = SEEN_PATH) -> dict[str, str]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_seen(seen: dict[str, str], today: str, keep_days: int, path: Path = SEEN_PATH) -> None:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=keep_days)).date().isoformat()
    kept = {k: v for k, v in seen.items() if v >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, sort_keys=True, indent=0))


def seen_keys(item: Item) -> list[str]:
    return ["u:" + canonical_url(item.url), "t:" + title_key(item.title)]


# ---------------------------------------------------------------- filtering
def filter_items(cfg: Config, items: list[Item], seen: dict[str, str], today: str, now: datetime) -> tuple[list[Item], dict]:
    windows = cfg.settings.get("windows_hours", {})
    junk = [re.compile(p) for p in cfg.settings.get("junk_titles", [])]
    stats = {"window": 0, "seen": 0, "ignored": 0, "junk": 0, "kept": 0}
    out = []
    for it in items:
        if len(it.title.split()) < 3 or any(p.search(it.title) for p in junk):
            stats["junk"] += 1
            continue
        hours = windows.get(it.kind, 36)
        if now - it.published > timedelta(hours=hours):
            stats["window"] += 1
            continue
        if it.domain in cfg.ignore_sources:
            stats["ignored"] += 1
            continue
        # Shown on an earlier day → skip. Shown earlier *today* (a re-run) → keep.
        if any(seen.get(k, today) < today for k in seen_keys(it)):
            stats["seen"] += 1
            continue
        out.append(it)
    stats["kept"] = len(out)
    return out, stats


# ---------------------------------------------------------------- clustering
def cluster_items(items: list[Item], threshold: float = 88) -> list[Cluster]:
    """Group items that are the same story: identical canonical URL or near-identical title."""
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_url: dict[str, int] = {}
    for i, it in enumerate(items):
        key = canonical_url(it.url)
        if key in by_url:
            union(by_url[key], i)
        else:
            by_url[key] = i

    titles = [norm_title(it.title) for it in items]
    eligible = [i for i, t in enumerate(titles) if len(t.split()) >= 5]
    if len(eligible) > 1:
        texts = [titles[i] for i in eligible]
        # token_sort_ratio, not token_set_ratio: set-ratio scores a short title that is a
        # subset of a longer one as 100, which merges unrelated "X wins" / "X wins final" stories.
        matrix = process.cdist(texts, texts, scorer=fuzz.token_sort_ratio, score_cutoff=threshold, workers=-1)
        for a in range(len(eligible)):
            row = matrix[a]
            for b in range(a + 1, len(eligible)):
                if row[b]:
                    union(eligible[a], eligible[b])

    groups: dict[int, list[Item]] = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    return [Cluster(items=g) for g in groups.values()]
