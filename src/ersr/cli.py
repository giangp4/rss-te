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
    a = sub.add_parser("articles", help="split an edition PDF into articles")
    a.add_argument("pdf", type=Path)
    a.add_argument("--out", type=Path, default=Path("scratch/m5"))
    args = parser.parse_args()

    if args.cmd == "articles":
        import json
        from ersr.articles import parse_contents, split_articles, to_markdown
        from ersr.pdf_text import edition_pages
        pages, contents, _ = edition_pages(args.pdf, args.out / "figures")
        arts = split_articles(pages)
        md_dir = args.out / "articles"
        md_dir.mkdir(parents=True, exist_ok=True)
        for f in md_dir.glob("*.md"):
            f.unlink()
        for n, art in enumerate(arts, 1):
            (md_dir / f"{n:02d}-{art['slug']}.md").write_text(to_markdown(art, "../figures"), encoding="utf-8")
        (args.out / "articles.json").write_text(json.dumps(arts, ensure_ascii=False, indent=1), encoding="utf-8")
        toc = parse_contents(contents)
        starts = {}
        for art in arts:
            starts.setdefault(art["pages"][0], []).append(art)
        lines = [f"{'#':>3} {'pages':7} {'words':>5} {'figs':>4}  {'section':22} {'rubric':24} headline"]
        for n, art in enumerate(arts, 1):
            pg = f"{art['pages'][0]}-{art['pages'][1]}" if art["pages"][0] != art["pages"][1] else str(art["pages"][0])
            lines.append(f"{n:3} {pg:7} {art['words']:5} {len(art['figures']):4}  {art['section'][:22]:22} {art['rubric'][:24]:24} {art['headline'][:50]}")
            lines += [f"{'':12}! {f}" for f in art["flags"]]
        missing = [(pg, t) for pg, t in toc if pg not in starts]
        toc_pages = {pg for pg, _ in toc}
        extra = [art for art in arts if art["pages"][0] not in toc_pages]
        lines += ["", f"Contents check: {len(toc)} entries; {len(toc) - len(missing)} have an article starting on that page."]
        lines += [f"  no article starts on p{pg}: {t}" for pg, t in missing]
        lines += [f"  article not in contents: p{art['pages'][0]} {art['headline'][:60]}" for art in extra]
        report = "\n".join(lines) + "\n"
        (args.out / "report.txt").write_text(report, encoding="utf-8")
        words = sum(art["words"] for art in arts)
        print(f"{len(arts)} articles | {words} words | {sum(len(a['figures']) for a in arts)} figures | "
              f"{sum(1 for a in arts if a['flags'])} flagged | contents: {len(toc) - len(missing)}/{len(toc)} matched")
        print(f"wrote {md_dir}/, {args.out}/articles.json, {args.out}/report.txt")

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
