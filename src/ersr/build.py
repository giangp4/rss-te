"""Write the site: an RSS 2.0 feed under a secret path, plus files that hide the root."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
import os
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

FEED_TITLE = "The Economist (personal)"
FEED_LINK = "https://www.economist.com/"
ATOM = "http://www.w3.org/2005/Atom"
FEED_DAYS = 30

ROBOTS = "User-agent: *\nDisallow: /\n"
BLANK_PAGE = '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>.</title>\n'


def recent(items: list[dict], days: int = FEED_DAYS) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [it for it in items if parsedate_to_datetime(it["pubdate"]) >= cutoff]


def build_feed(items: list[dict], out: Path, self_url: str | None = None) -> None:
    ET.register_namespace("atom", ATOM)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "description").text = "Personal feed built from the public Economist RSS"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    if self_url:
        ET.SubElement(channel, f"{{{ATOM}}}link", href=self_url, rel="self", type="application/rss+xml")

    for it in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = it["title"]
        ET.SubElement(item, "link").text = it["link"]
        ET.SubElement(item, "guid", isPermaLink=str(it["guid"].startswith("http")).lower()).text = it["guid"]
        ET.SubElement(item, "pubDate").text = it["pubdate"]
        ET.SubElement(item, "description").text = it["description"]
        if it["section"]:
            ET.SubElement(item, "category").text = it["section"]

    out.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(rss)
    ET.ElementTree(rss).write(out, encoding="utf-8", xml_declaration=True)


LOCAL_URL = "http://localhost:8000"
MATCH_ACCEPT = 60  # M7 dry run: every match at or above this was correct; lower ones wait for M8


def assign_paths(items: list[dict], articles: list[dict]) -> dict[str, dict]:
    """Give each article its page path, <edition>/<section>/<print headline>, fixed at
    ingest time and independent of matching (online dates differ from the edition's).
    Returns {RSS guid: article} for the accepted matches."""
    from ersr.match import match_report, section_slug
    merged = {}
    for row in match_report(articles, items):
        a, best = row["article"], row["best"]
        a["path"] = f"{a['edition']}/{section_slug(a['section'])}/{a['slug']}"
        if best and best["score"] >= MATCH_ACCEPT:
            merged[best["item"]["guid"]] = a
    return merged


def merge_matches(items: list[dict], merged: dict[str, dict], base: str) -> list[dict]:
    """Point matched RSS items at our full-text page. The item keeps its guid, so
    readers don't see it as new; its description ends with the original link."""
    from html import escape
    out = []
    for it in items:
        a = merged.get(it["guid"])
        if a:
            link = escape(it["link"])
            text = escape(it["description"].rstrip(". "))
            source = f'Source: <a href="{link}">{link}</a>'
            it = {**it, "link": f"{base}/{a['path']}.html", "description": f"{text}. {source}" if text else source}
        out.append(it)
    return out


def article_items(articles: list[dict], base: str) -> list[dict]:
    """One feed item per full-text article that has no RSS item to attach to."""
    items = []
    for a in articles:
        date = datetime.fromisoformat(a["edition"]).replace(tzinfo=timezone.utc)
        items.append({
            "guid": f"ersr:{a['id']}",
            "title": a["headline"],
            "link": f"{base}/{a['path']}.html",
            "pubdate": format_datetime(date),
            "description": a["standfirst"] or next((b[1][:280] for b in a["blocks"] if b[0] == "p"), ""),
            "section": a["section"],
        })
    return items


def build_articles(articles: list[dict], out_dir: Path, content_dir: Path) -> int:
    """Write <path>.html for each article, and <edition>/figures/ for each edition."""
    from ersr.render import render_article
    for edition in {a["edition"] for a in articles}:
        figs = content_dir / edition / "figures"
        if figs.exists():
            shutil.copytree(figs, out_dir / edition / "figures", dirs_exist_ok=True)
    for a in articles:
        page = out_dir / f"{a['path']}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        figures_url = Path(os.path.relpath(out_dir / a["edition"] / "figures", page.parent)).as_posix()
        page.write_text(render_article(a, figures_url), encoding="utf-8")
    return len(articles)


def build_site(items: list[dict], site_dir: Path, secret: str, base_url: str | None,
               articles: list[dict] = (), content_dir: Path = Path("content")) -> Path:
    """site/robots.txt, site/index.html (blank), and under site/<secret>/: feed.xml and
    <edition>/<section>/<slug>.html per article, with <edition>/figures/. Returns the feed path."""
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "robots.txt").write_text(ROBOTS)
    (site_dir / "index.html").write_text(BLANK_PAGE)
    (site_dir / ".nojekyll").write_text("")
    base = f"{(base_url or LOCAL_URL).rstrip('/')}/{secret}"
    shutil.rmtree(site_dir / secret, ignore_errors=True)
    articles = list(articles)
    merged = assign_paths(items, articles)
    build_articles(articles, site_dir / secret, content_dir)
    items = merge_matches(items, merged, base)
    unmatched = [a for a in articles if a not in merged.values()]
    print(f"full text: {len(merged)} articles merged into their RSS item, {len(unmatched)} kept as separate items")
    all_items = items + article_items(unmatched, base)
    all_items.sort(key=lambda it: parsedate_to_datetime(it["pubdate"]), reverse=True)
    feed = site_dir / secret / "feed.xml"
    build_feed(recent(all_items), feed, f"{base}/feed.xml" if base_url else None)
    return feed
