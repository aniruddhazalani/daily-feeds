"""CLI: python -m feeds build | check-sources"""
from __future__ import annotations

import argparse
import logging
import sys

from . import config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="feeds")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="fetch, rank and render the daily page")
    b.add_argument("--explain", metavar="FEED.SECTION", help="print every candidate's score breakdown for a section")
    b.add_argument("--no-discover", action="store_true", help="skip source discovery")
    b.add_argument("--no-save", action="store_true", help="don't write data/ (dry run); still renders site/")
    b.add_argument("--out", default="site", help="output directory for the static site")

    c = sub.add_parser("check-sources", help="verify every source and suggest fixes")
    c.add_argument("--only", help="comma-separated source ids")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load()

    if args.cmd == "check-sources":
        from . import check
        only = set(args.only.split(",")) if args.only else None
        return check.run(cfg, only)

    from . import build
    return build.run(cfg, explain=args.explain, discover_sources=not args.no_discover, save=not args.no_save, out=args.out)


if __name__ == "__main__":
    sys.exit(main())
