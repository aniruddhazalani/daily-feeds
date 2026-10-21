"""Load and validate feeds.yaml (+ data/discovered_sources.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "feeds.yaml"
DATA_DIR = ROOT / "data"
DISCOVERED_PATH = DATA_DIR / "discovered_sources.yaml"

SOURCE_TYPES = {"rss", "gnews", "arxiv", "hf_papers"}
KINDS = {"official", "news", "blog", "paper", "search", "discovered"}
LEANS = ("left", "center", "right")
DEFAULT_WEIGHTS = {"official": 3, "news": 2, "blog": 2, "paper": 2, "search": 1, "discovered": 1}


class ConfigError(ValueError):
    pass


@dataclass
class Source:
    id: str
    type: str
    kind: str
    weight: float
    name: str = ""
    url: Optional[str] = None
    query: Optional[str] = None
    topical: bool = False
    paywall: bool = False
    max_results: int = 100
    fallback: Optional[str] = None  # Google News query used if the feed is blocked
    discovered: bool = False
    meta: dict = field(default_factory=dict)  # discovery bookkeeping

    @property
    def domains(self) -> set[str]:
        """Domains this source publishes from (used to tell known from unknown domains)."""
        out = set()
        if self.url:
            out.add(norm_domain(urlparse(self.url).hostname or ""))
        if self.query:
            for m in re.finditer(r"site:([^\s/)]+)", self.query):
                out.add(norm_domain(m.group(1)))
        if self.meta.get("domain"):
            out.add(self.meta["domain"])
        out.discard("")
        return out


@dataclass
class Section:
    id: str
    feed_id: str
    title: str
    source_ids: list[str]
    include: dict[str, float]
    exclude: list[str]
    require_any: list[str]
    min_score: float
    max_items: int
    max_analysis: int
    max_papers: int

    @property
    def key(self) -> str:
        return f"{self.feed_id}.{self.id}"


@dataclass
class Feed:
    id: str
    title: str
    sections: list[Section]
    tags: dict[str, list[str]] = field(default_factory=dict)
    balance: bool = False  # keep left- and right-leaning outlets even in this feed's sections


@dataclass
class Config:
    settings: dict
    sources: dict[str, Source]
    feeds: list[Feed]
    ignore_sources: set[str]
    leans: dict[str, str] = field(default_factory=dict)  # domain → left | center | right

    def lean(self, domain: str) -> Optional[str]:
        """Political lean of an outlet domain (subdomains inherit), or None if unrated."""
        d = norm_domain(domain)
        while d:
            if d in self.leans:
                return self.leans[d]
            d = d.partition(".")[2] if d.count(".") > 1 else ""
        return None

    def sections(self) -> list[Section]:
        return [s for f in self.feeds for s in f.sections]

    def section(self, key: str) -> Section:
        for s in self.sections():
            if s.key == key:
                return s
        raise KeyError(key)

    def known_domains(self) -> set[str]:
        out: set[str] = set()
        for s in self.sources.values():
            out |= s.domains
        return out


def norm_domain(host: str) -> str:
    host = (host or "").lower().strip().rstrip(".")
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def _source(sid: str, raw: dict, discovered: bool = False) -> Source:
    if not isinstance(raw, dict):
        raise ConfigError(f"source {sid}: must be a mapping")
    stype = raw.get("type")
    if stype not in SOURCE_TYPES:
        raise ConfigError(f"source {sid}: type must be one of {sorted(SOURCE_TYPES)}")
    kind = raw.get("kind", "discovered" if discovered else "news")
    if kind not in KINDS:
        raise ConfigError(f"source {sid}: kind must be one of {sorted(KINDS)}")
    if stype in ("rss", "hf_papers") and not raw.get("url"):
        raise ConfigError(f"source {sid}: {stype} needs url")
    if stype in ("gnews", "arxiv") and not raw.get("query"):
        raise ConfigError(f"source {sid}: {stype} needs query")
    known = {"type", "kind", "weight", "name", "url", "query", "topical", "paywall", "max_results", "fallback"}
    meta = {k: v for k, v in raw.items() if k not in known}
    return Source(
        id=sid,
        type=stype,
        kind=kind,
        weight=float(raw.get("weight", DEFAULT_WEIGHTS[kind])),
        name=raw.get("name", ""),
        url=raw.get("url"),
        query=raw.get("query"),
        topical=bool(raw.get("topical", False)),
        paywall=bool(raw.get("paywall", False)),
        max_results=int(raw.get("max_results", 100)),
        fallback=raw.get("fallback"),
        discovered=discovered,
        meta=meta,
    )


def load_discovered(path: Path = DISCOVERED_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("sources", []) or []


def load(path: Path = CONFIG_PATH, with_discovered: bool = True) -> Config:
    raw = yaml.safe_load(path.read_text())
    settings = raw.get("settings", {}) or {}
    ignore = {norm_domain(d) for d in (raw.get("ignore_sources") or [])}

    sources: dict[str, Source] = {}
    for sid, sraw in (raw.get("sources") or {}).items():
        sources[sid] = _source(sid, sraw)

    feeds: list[Feed] = []
    for fid, fraw in (raw.get("feeds") or {}).items():
        sections = []
        for sec_id, sraw in (fraw.get("sections") or {}).items():
            src_ids = sraw.get("sources") or []
            for s in src_ids:
                if s not in sources:
                    raise ConfigError(f"section {fid}.{sec_id}: unknown source '{s}'")
            sections.append(Section(
                id=sec_id,
                feed_id=fid,
                title=sraw.get("title", sec_id),
                source_ids=list(src_ids),
                include={str(k): float(v) for k, v in (sraw.get("include") or {}).items()},
                exclude=[str(x) for x in (sraw.get("exclude") or [])],
                require_any=[str(x) for x in (sraw.get("require_any") or [])],
                min_score=float(sraw.get("min_score", settings.get("default_min_score", 3))),
                max_items=int(sraw.get("max_items", settings.get("default_max_items", 12))),
                max_analysis=int(sraw.get("max_analysis", settings.get("default_max_analysis", 6))),
                max_papers=int(sraw.get("max_papers", settings.get("default_max_papers", 8))),
            ))
        if not sections:
            raise ConfigError(f"feed {fid}: needs at least one section")
        feeds.append(Feed(id=fid, title=fraw.get("title", fid), sections=sections,
                          tags={k: [str(t) for t in v] for k, v in (fraw.get("tags") or {}).items()},
                          balance=bool(fraw.get("balance", False))))

    leans: dict[str, str] = {}
    for lean, domains in (raw.get("leans") or {}).items():
        if lean not in LEANS:
            raise ConfigError(f"leans: '{lean}' must be one of {LEANS}")
        for d in domains or []:
            if norm_domain(d) in leans:
                raise ConfigError(f"leans: {d} is listed twice")
            leans[norm_domain(d)] = lean

    cfg = Config(settings=settings, sources=sources, feeds=feeds, ignore_sources=ignore, leans=leans)

    if with_discovered:
        keys = {s.key for s in cfg.sections()}
        for d in load_discovered():
            sid = d.get("id")
            if not sid or sid in sources:
                continue
            src = _source(sid, {k: v for k, v in d.items() if k != "id"}, discovered=True)
            if src.domains & ignore:
                continue
            sources[sid] = src
            for key in d.get("sections", []):
                if key in keys:
                    cfg.section(key).source_ids.append(sid)
    return cfg
