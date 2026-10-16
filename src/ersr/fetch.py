"""Read the Economist's public RSS into plain item dicts."""
from email.utils import format_datetime
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser

LATEST_URL = "https://www.economist.com/latest/rss.xml"


def section_from_link(link: str) -> str:
    """'https://www.economist.com/business/2026/10/15/slug' -> 'business'."""
    parts = urlparse(link).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else ""


def fetch_items(source: str = LATEST_URL) -> list[dict]:
    """Parse a feed URL or local file and return one dict per entry."""
    feed = feedparser.parse(source)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"could not parse feed {source}: {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        items.append({
            "guid": e.get("id") or e.link,
            "title": e.title,
            "link": e.link,
            "pubdate": format_datetime(published),
            "description": e.get("summary", ""),
            "section": section_from_link(e.link),
        })
    return items
