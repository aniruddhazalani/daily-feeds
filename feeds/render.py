"""Render day snapshots to a static site: index.html (latest) + archive/YYYY-MM-DD.html."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT

TEMPLATES = ROOT / "templates"
BADGES = {"official": "Official", "blog": "Analysis", "paper": "Paper", "new": "New source", "search": "", "news": ""}


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["badge"] = lambda kind: BADGES.get(kind, "")
    return env


def _fmt_local(iso: str, tz: str, fmt: str) -> str:
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz)).strftime(fmt)


def render_site(out: Path, days: list[dict], show_first: int = 5) -> None:
    days = sorted(days, key=lambda d: d["date"])
    if not days:
        return
    env = _env()
    env.filters["local"] = lambda iso, fmt="%d %b, %H:%M": _fmt_local(iso, days[-1].get("timezone", "UTC"), fmt)
    tpl = env.get_template("page.html.j2")
    dates = [d["date"] for d in reversed(days)]

    if out.exists():
        shutil.rmtree(out)
    (out / "archive").mkdir(parents=True)
    shutil.copy(TEMPLATES / "style.css", out / "style.css")
    shutil.copy(TEMPLATES / "app.js", out / "app.js")

    for i, day in enumerate(days):
        latest = i == len(days) - 1
        html = tpl.render(day=day, dates=dates, latest=latest, show_first=show_first, base="../",
                          pretty_date=datetime.fromisoformat(day["date"]).strftime("%A, %d %B %Y"))
        (out / "archive" / f"{day['date']}.html").write_text(html)
        if latest:
            (out / "index.html").write_text(
                tpl.render(day=day, dates=dates, latest=True, show_first=show_first, base="",
                           pretty_date=datetime.fromisoformat(day["date"]).strftime("%A, %d %B %Y")))
    (out / ".nojekyll").write_text("")
