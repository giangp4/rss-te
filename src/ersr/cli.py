"""Command line: `ersr build [--source URL_OR_FILE] [--site DIR] [--store PATH]`.

FEED_SECRET (the secret path segment) and SITE_URL (e.g. https://user.github.io/repo)
are read from the environment so they never need to be written into the repo.
"""
import argparse
import os
from pathlib import Path

from ersr import store
from ersr.build import FEED_DAYS, build_site
from ersr.fetch import LATEST_URL, fetch_items


def main() -> None:
    parser = argparse.ArgumentParser(prog="ersr")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="merge the public RSS into the store and write the site")
    b.add_argument("--source", default=LATEST_URL, help="feed URL or local XML file")
    b.add_argument("--site", type=Path, default=Path("site"))
    b.add_argument("--store", type=Path, default=store.STORE_PATH)
    t = sub.add_parser("pdf-text", help="extract reading-order text from an edition PDF")
    t.add_argument("pdf", type=Path)
    t.add_argument("--out", type=Path, default=Path("scratch/m4/edition.txt"))
    t.add_argument("--figures", type=Path, default=Path("scratch/m4/figures"), help="where chart/photo images go")
    args = parser.parse_args()

    if args.cmd == "pdf-text":
        from ersr.pdf_text import edition_text
        text, stats = edition_text(args.pdf, args.figures)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"{stats['pages']} pages | {len(stats['ads'])} skipped as ads/cover: {stats['ads']}")
        print(f"{stats['content']} content pages (contents pages {stats.get('contents')} skipped) | {len(text.split())} words -> {args.out}")
        n_fig = len(list(args.figures.glob("*")))
        print(f"{n_fig} figures -> {args.figures}/ | {text.count('[unplaced]')} pages with unplaced chart text")

    if args.cmd == "build":
        secret = os.environ.get("FEED_SECRET", "local")
        fetched = fetch_items(args.source)
        items = store.load(args.store)
        before = len(items)
        added, updated = store.merge(items, fetched)
        store.save(items, args.store)
        feed = build_site(list(store.load(args.store).values()), args.site, secret, os.environ.get("SITE_URL"))
        n_feed = open(feed, encoding="utf-8").read().count("<item>")
        print(f"fetched {len(fetched)} | store {before} -> {len(items)} "
              f"(+{added} new, {updated} updated) | feed {n_feed} items (last {FEED_DAYS} days)")
        print(f"wrote {args.site}/{'<secret>' if secret != 'local' else 'local'}/feed.xml")
