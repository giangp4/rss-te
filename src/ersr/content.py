"""Store extracted editions under content/<date>/ (later its own private git repo)."""
import json
import shutil
from pathlib import Path

from ersr.articles import parse_contents, split_articles
from ersr.pdf_text import edition_pages

CONTENT_DIR = Path("content")


def ingest(pdf: Path, content_dir: Path = CONTENT_DIR) -> tuple[str, list[dict]]:
    """Extract one edition PDF into content/<date>/articles.json + figures/. Re-running replaces it."""
    tmp = content_dir / ".ingest"
    shutil.rmtree(tmp, ignore_errors=True)
    pages, contents, stats = edition_pages(pdf, tmp / "figures")
    date = stats["date"]
    articles, seen = split_articles(pages), set()
    for a in articles:
        slug, n = a["slug"], 2
        while slug in seen:  # two articles with the same headline (e.g. 'Politics')
            slug, n = f"{a['slug']}-{n}", n + 1
        seen.add(slug)
        a["slug"], a["edition"], a["id"] = slug, date, f"{date}/{slug}"
    # the contents page's short title for each article ('Trump’s AI dilemma'), matched by start page
    by_page = {}
    for pg, title in parse_contents(contents):
        by_page.setdefault(pg, []).append(title)
    for a in articles:
        titles = by_page.get(a["pages"][0], [])
        a["toc_title"] = titles.pop(0) if titles else ""
    out = content_dir / date
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out) if (tmp / "figures").exists() else out.mkdir(parents=True)
    (out / "articles.json").write_text(json.dumps(articles, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return date, articles


def load_editions(content_dir: Path = CONTENT_DIR) -> list[dict]:
    """All stored articles, newest edition first."""
    articles = []
    for f in sorted(content_dir.glob("*/articles.json"), reverse=True):
        articles += json.loads(f.read_text(encoding="utf-8"))
    return articles
