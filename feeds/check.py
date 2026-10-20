"""`python -m feeds check-sources`: verify every source works and suggest fixes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from . import feedfind
from .config import Config
from .fetch import fetch_all


def run(cfg: Config, only: Optional[set[str]] = None, suggest: bool = True) -> int:
    results = fetch_all(cfg, only)
    now = datetime.now(timezone.utc)
    bad = []
    print(f"{'source':28} {'type':9} {'items':>5}  {'newest':>8}  status")
    for sid in sorted(results):
        r = results[sid]
        src = cfg.sources[sid]
        newest = max((i.published for i in r.items), default=None)
        age = f"{(now - newest).days}d" if newest else "-"
        status = "ok"
        if r.error:
            status = f"ERROR {r.error}"
        elif not r.items:
            status = "EMPTY"
        elif newest and (now - newest).days > 60:
            status = "STALE"
        print(f"{sid:28} {src.type:9} {len(r.items):>5}  {age:>8}  {status}")
        if status != "ok":
            bad.append(sid)

    if suggest and bad:
        print("\nLooking for working feeds for failing rss sources…")
        with feedfind.client() as c:
            for sid in bad:
                src = cfg.sources[sid]
                if src.type != "rss" or not src.url:
                    continue
                u = urlparse(src.url)
                found = feedfind.find_feed(c, f"{u.scheme}://{u.netloc}")
                if found:
                    newest = found.newest.date().isoformat() if found.newest else "?"
                    print(f"  {sid}: try {found.url}  ({found.entries} entries, newest {newest})")
                else:
                    print(f"  {sid}: no feed found; consider a gnews 'site:{u.netloc}' query")
    print(f"\n{len(results) - len(bad)}/{len(results)} sources ok")
    return 1 if bad else 0
