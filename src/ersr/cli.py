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
    args = parser.parse_args()

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
