"""Match full-text articles from the PDF to items in the public RSS (M7)."""
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from rapidfuzz import fuzz

from ersr.articles import slugify

# Online, an edition dated Saturday comes out on Thursday (2 days before); some
# articles appear earlier in the week, none after the cover date
WINDOW_BEFORE, WINDOW_AFTER = 10, -1
RELEASE_OFFSET = -2


def rss_section(link: str) -> str:
    return urlparse(link).path.strip("/").split("/")[0]


def section_slug(section: str) -> str:
    return slugify(section.replace("&", "and"))


def url_words(link: str) -> str:
    return urlparse(link).path.rstrip("/").split("/")[-1].replace("-", " ")


def days_from_release(article: dict, item: dict) -> int:
    """How far the item's date is from the edition's online release day."""
    ed = date.fromisoformat(article["edition"])
    return abs((parsedate_to_datetime(item["pubdate"]).date() - ed).days - RELEASE_OFFSET)


def score(article: dict, item: dict) -> tuple[float, str]:
    """Best similarity between the article and the RSS item, and which fields gave it."""
    head, stand, toc = article["headline"], article["standfirst"], article.get("toc_title", "")
    pairs = {
        "title~contents": (item["title"], toc),
        "url~contents": (url_words(item["link"]), toc),
        "title~headline": (item["title"], head),
        "title~standfirst": (item["title"], stand),
        "description~standfirst": (item["description"], stand),
        "description~headline": (item["description"], head),
        "url~headline": (url_words(item["link"]), head),
        "url~standfirst": (url_words(item["link"]), stand),
    }
    best = max(((fuzz.token_sort_ratio(a.lower(), b.lower()) if a and b else 0, name)
                for name, (a, b) in pairs.items()), key=lambda x: x[0])
    return best


def candidates(article: dict, items: list[dict]) -> list[dict]:
    ed = date.fromisoformat(article["edition"])
    lo, hi = ed - timedelta(days=WINDOW_BEFORE), ed + timedelta(days=WINDOW_AFTER)
    return [it for it in items if lo <= parsedate_to_datetime(it["pubdate"]).date() <= hi]


def rank(article: dict, items: list[dict]) -> list[dict]:
    """Candidate RSS items for one article, best first. Only items from the article's
    section compete, when there are any (sections are reliable on both sides)."""
    out, cands = [], candidates(article, items)
    same = [it for it in cands if rss_section(it["link"]) == section_slug(article["section"])]
    for it in same or cands:
        s, why = score(article, it)
        same = rss_section(it["link"]) == section_slug(article["section"])
        out.append({"item": it, "score": s, "why": why, "same_section": same,
                    "days_off": days_from_release(article, it)})
    # equal scores (weekly columns with the same title): the item nearest the release day wins
    return sorted(out, key=lambda r: (-r["score"], r["days_off"]))


def match_report(articles: list[dict], items: list[dict]) -> list[dict]:
    """Best RSS item per article, one article per item: the highest-scoring pairs are
    assigned first, and an article whose favourite is taken falls back to its next choice."""
    ranked = {a["id"]: rank(a, items) for a in articles}
    pairs = sorted(((-r["score"], r["days_off"], a["id"], n) for a in articles for n, r in enumerate(ranked[a["id"]])))
    chosen, taken = {}, set()
    for _, _, aid, n in pairs:
        r = ranked[aid][n]
        if aid not in chosen and r["item"]["guid"] not in taken:
            chosen[aid], _ = r, taken.add(r["item"]["guid"])
    rows = []
    for a in articles:
        best = chosen.get(a["id"])
        others = [r for r in ranked[a["id"]] if r is not best]
        rows.append({"article": a, "best": best, "second": others[0] if others else None,
                     "n_candidates": len(ranked[a["id"]])})
    return rows
