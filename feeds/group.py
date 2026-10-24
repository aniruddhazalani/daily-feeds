"""Group articles about the same story, even when their headlines differ.

Near-identical headlines are already merged by filter.cluster_items. This step goes
further: it compares what articles are *about* using TF-IDF over headline + snippet,
so "Wiegman signs contract extension" and "Sarina Wiegman signs new England contract
until 2029" become one story with two articles.

How it decides:
- Words are weighted by rarity across today's items (TF-IDF), so names and specific
  terms (Wiegman, Cloudera, H-1B) count far more than common ones (Trump, says, war).
- Two articles must share at least `min_shared` distinctive words and be published
  within `max_hours_apart` of each other.
- Grouping is greedy against each group's centroid (its average vector), not chained
  pair-to-pair, so a story can't snowball into "everything mentioning Ukraine".
- News, analysis and papers are grouped separately: blog analysis keeps its own list.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import timedelta

from .models import Cluster

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9’'\-]*[A-Za-z0-9]|[A-Za-z]")
STOP = set("""
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on
once only or other our out over own same she should so some such than that the their them then there these
they this those through to too under until up very was we were what when where which while who whom why
will with would you your
says said say saying tells told new latest live update updates news report reports reported today week
watch video photos amid after over first last year years day days could may might set sets make makes
one two three back get gets got just still now how why what here's it's says
""".split())
KIND_GROUP = {"paper": "paper", "blog": "blog"}  # everything else groups as "news"


def tokens(text: str) -> list[str]:
    out = []
    for w in WORD_RE.findall(text):
        w = w.lower().replace("’", "'")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # light plural folding: tariffs → tariff
        if len(w) < 2 or w in STOP or w.isdigit():
            continue
        out.append(w)
    return out


def _doc(cl: Cluster) -> Counter:
    tf: Counter = Counter()
    for t in dict.fromkeys(it.title for it in cl.items):
        tf.update(tokens(t) * 2)  # headlines carry the story; count them double
    for s in dict.fromkeys(it.snippet for it in cl.items if it.snippet):
        tf.update(tokens(s[:300]))
    return tf


def _norm(vec: dict[str, float]) -> dict[str, float]:
    n = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / n for k, v in vec.items()}


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def group_stories(clusters: list[Cluster], similarity: float = 0.45, min_shared: int = 2,
                  max_hours_apart: float = 48, max_size: int = 25) -> list[Cluster]:
    groups_out: list[Cluster] = []
    by_kind: dict[str, list[Cluster]] = defaultdict(list)
    for cl in clusters:
        kinds = {KIND_GROUP.get(it.kind, "news") for it in cl.items}
        by_kind[kinds.pop() if len(kinds) == 1 else "news"].append(cl)

    for kind, cls in by_kind.items():
        if kind == "paper":  # papers only merge as exact duplicates (done upstream)
            groups_out.extend(cls)
            continue
        groups_out.extend(_group(cls, similarity, min_shared, max_hours_apart, max_size))
    return groups_out


def _group(cls: list[Cluster], similarity: float, min_shared: int, max_hours: float, max_size: int) -> list[Cluster]:
    n = len(cls)
    if n < 2:
        return cls
    tfs = [_doc(c) for c in cls]
    df: Counter = Counter()
    for tf in tfs:
        df.update(tf.keys())
    idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
    # A word in more than 3% of today's items (Trump, India, AI) can't on its own tie stories together.
    distinctive_df = max(3, int(0.03 * n))
    vecs = [_norm({t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}) for tf in tfs]
    distinct = [{t for t in tf if df[t] <= distinctive_df} for tf in tfs]

    # Seed groups with the most widely covered stories first, so they attract their follow-ups.
    order = sorted(range(n), key=lambda i: (-len(cls[i].outlets), -cls[i].newest.timestamp()))
    postings: dict[str, list[int]] = defaultdict(list)  # distinctive word → group ids
    groups: list[dict] = []  # {"members": [idx], "centroid": {...}, "sum": {...}, "words": set, "lo": dt, "hi": dt}
    span = timedelta(hours=max_hours)

    for i in order:
        cand = Counter(g for t in distinct[i] for g in postings.get(t, ()))
        best, best_sim = None, similarity
        for g_id, shared in cand.items():
            if shared < min_shared:
                continue
            g = groups[g_id]
            if len(g["members"]) >= max_size:
                continue
            if cls[i].newest - g["lo"] > span or g["hi"] - cls[i].newest > span:
                continue
            sim = _dot(vecs[i], g["centroid"])
            if sim >= best_sim:
                best, best_sim = g_id, sim
        if best is None:
            g_id = len(groups)
            groups.append({"members": [i], "sum": dict(vecs[i]), "centroid": vecs[i],
                           "lo": cls[i].newest, "hi": cls[i].newest})
        else:
            g_id = best
            g = groups[g_id]
            g["members"].append(i)
            for t, v in vecs[i].items():
                g["sum"][t] = g["sum"].get(t, 0.0) + v
            g["centroid"] = _norm(g["sum"])
            g["lo"], g["hi"] = min(g["lo"], cls[i].newest), max(g["hi"], cls[i].newest)
        for t in distinct[i]:
            if not postings[t] or postings[t][-1] != g_id:
                postings[t].append(g_id)

    _merge_groups(groups, distinct, similarity, min_shared, span, max_size)
    return [Cluster(items=[it for m in g["members"] for it in cls[m].items]) for g in groups if g["members"]]


def _merge_groups(groups: list[dict], distinct: list[set], similarity: float, min_shared: int,
                  span: timedelta, max_size: int) -> None:
    """Second pass: merge groups that ended up as two halves of one story.

    A single article can miss a group's centroid (its own wording differs), and then
    start a parallel group that collects the rest of its coverage. Comparing whole groups
    catches that. Merges happen most-similar first; emptied groups are left with no members.
    """
    words = [set().union(*(distinct[m] for m in g["members"])) for g in groups]
    postings: dict[str, list[int]] = defaultdict(list)
    for g_id, ws in enumerate(words):
        for t in ws:
            postings[t].append(g_id)
    pairs = []
    for a in range(len(groups)):
        shared = Counter(b for t in words[a] for b in postings[t] if b > a)
        for b, n in shared.items():
            if n < min_shared:
                continue
            ga, gb = groups[a], groups[b]
            if ga["hi"] - gb["lo"] > span or gb["hi"] - ga["lo"] > span:
                continue
            sim = _dot(ga["centroid"], gb["centroid"])
            if sim >= similarity:
                pairs.append((sim, a, b))
    parent = list(range(len(groups)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for sim, a, b in sorted(pairs, reverse=True):
        ra, rb = find(a), find(b)
        if ra == rb or len(groups[ra]["members"]) + len(groups[rb]["members"]) > max_size:
            continue
        # Re-check against the merged-so-far centroids so merges can't chain into a blob.
        if _dot(groups[ra]["centroid"], groups[rb]["centroid"]) < similarity:
            continue
        ga, gb = groups[ra], groups[rb]
        ga["members"] += gb["members"]
        for t, v in gb["sum"].items():
            ga["sum"][t] = ga["sum"].get(t, 0.0) + v
        ga["centroid"] = _norm(ga["sum"])
        ga["lo"], ga["hi"] = min(ga["lo"], gb["lo"]), max(ga["hi"], gb["hi"])
        gb["members"] = []
        parent[rb] = ra
