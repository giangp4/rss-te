"""Item history kept in one JSON file, keyed by guid."""
import json
from email.utils import parsedate_to_datetime
from pathlib import Path

STORE_PATH = Path("data/items.json")


def load(path: Path = STORE_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {it["guid"]: it for it in json.loads(path.read_text(encoding="utf-8"))}


def merge(store: dict[str, dict], items: list[dict]) -> tuple[int, int]:
    """Add new items and refresh existing ones. Returns (added, updated)."""
    added = updated = 0
    for it in items:
        old = store.get(it["guid"])
        if old is None:
            added += 1
        elif any(old.get(k) != v for k, v in it.items()):
            updated += 1
        # keep fields later milestones add (full text, abstracts) while refreshing RSS ones
        store[it["guid"]] = {**(old or {}), **it}
    return added, updated


def save(store: dict[str, dict], path: Path = STORE_PATH) -> None:
    """Newest first, so the file and its git diffs read top-down."""
    items = sorted(store.values(), key=lambda it: parsedate_to_datetime(it["pubdate"]), reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
