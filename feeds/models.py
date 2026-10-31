from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Item:
    title: str
    url: str
    outlet: str
    domain: str
    source_id: str
    kind: str
    published: datetime  # timezone-aware UTC
    snippet: str = ""
    paywall: bool = False
    discovered: bool = False
    via_search: bool = False          # came from a Google News query (outlet != source)
    links: list[str] = field(default_factory=list)  # outbound domains (for discovery)
    upvotes: int = 0                   # HF daily papers


@dataclass
class Cluster:
    items: list[Item]

    @property
    def outlets(self) -> list[str]:
        seen, out = set(), []
        for it in self.items:
            if it.outlet and it.outlet.lower() not in seen:
                seen.add(it.outlet.lower())
                out.append(it.outlet)
        return out

    @property
    def newest(self) -> datetime:
        return max(it.published for it in self.items)

    @property
    def source_ids(self) -> set[str]:
        return {it.source_id for it in self.items}

    def text(self) -> tuple[str, str]:
        titles = " \n ".join(dict.fromkeys(it.title for it in self.items))
        snippets = " \n ".join(dict.fromkeys(it.snippet for it in self.items if it.snippet))
        return titles, snippets


@dataclass
class Scored:
    cluster: Cluster
    section_key: str
    score: float
    primary: Item
    parts: dict = field(default_factory=dict)
    tag: Optional[str] = None
    rating: Optional[dict] = None       # impact rating from Claude, when available
    continuing: Optional[dict] = None   # earlier coverage of the same storyline, when found
