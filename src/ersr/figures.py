"""Find charts and photos on a page and render each one as an image (M4b).

Photos are embedded images with a position. Charts are not images at all: they
are vector shapes plus small sans-serif labels, so we find their box and render
that part of the page.
"""
from pathlib import Path

import pymupdf

NEAR = 6           # pt: shapes this close to a figure box belong to it
LINE_GAP = 30      # pt: chart text lines closer than this form one figure
MIN_PHOTO = 30     # pt: smaller images are icons/logos
TOP_MARGIN = 40    # pt: the running header zone; no figure reaches into it
DPI = 200


def _ignored_shape(r: pymupdf.Rect, page_rect: pymupdf.Rect) -> bool:
    """Long thin lines (column dividers, rules between articles), full-page panels,
    and invisible clipping shapes that stick out of the page or into the header."""
    thin = min(r.width, r.height) < 2
    return ((thin and max(r.width, r.height) > 250) or (r.width > 400 and r.height > 400)
            or r.y0 < TOP_MARGIN or not page_rect.contains(r))


def visible_shapes(page) -> list[pymupdf.Rect]:
    """Each vector shape's box cut to its clipping region. Maps draw borders and
    coastlines past their frame and rely on clipping to hide the overflow."""
    clips, out = {}, []  # nesting level -> visible area at that level
    for d in page.get_drawings(extended=True):
        level = d.get("level", 0)
        parent = next((clips[l] for l in range(level - 1, -1, -1) if l in clips), page.rect)
        if d["type"] == "clip":
            clips = {l: r for l, r in clips.items() if l < level}
            clips[level] = pymupdf.Rect(d["scissor"]) & parent
        elif d["type"] in ("f", "s", "fs"):
            r = pymupdf.Rect(d["rect"]) & parent
            if not r.is_empty:
                out.append(r)
    return out


def _merge(boxes: list[dict]) -> list[dict]:
    """Merge figure boxes that overlap (photo + its caption, chart + its labels)."""
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i]["rect"], boxes[j]["rect"]
                if pymupdf.Rect(a.x0 - NEAR, a.y0 - NEAR, a.x1 + NEAR, a.y1 + NEAR).intersects(b):
                    boxes[i] = {"rect": a | b, "photo": boxes[i]["photo"] or boxes[j]["photo"],
                                "real": boxes[i]["real"] or boxes[j]["real"],
                                "img": boxes[i]["img"] | boxes[j]["img"]}
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


def find_figures(page, chart_lines: list[pymupdf.Rect], body_lines: list[pymupdf.Rect] = ()) -> list[dict]:
    """Return [{'rect': Rect, 'photo': bool}] in top-to-bottom, left-to-right order.
    chart_lines: boxes of lines already classified as chart/caption text.
    body_lines: boxes of article text; shapes behind text are backgrounds, not figures."""
    # map tiles can be small, so only drop images that are small on both sides
    seeds = [{"rect": pymupdf.Rect(i["bbox"]), "photo": True} for i in page.get_image_info()
             if max(pymupdf.Rect(i["bbox"]).width, pymupdf.Rect(i["bbox"]).height) > MIN_PHOTO]
    for s in seeds:
        s["img"] = pymupdf.Rect(s["rect"])

    # group chart text lines that sit together in one column
    for r in sorted(chart_lines, key=lambda r: (r.x0, r.y0)):
        for s in seeds:
            if not s["photo"] and abs(s["rect"].x0 - r.x0) < 60 and r.y0 - s["rect"].y1 < LINE_GAP and r.y1 > s["rect"].y0 - LINE_GAP:
                s["rect"] |= r
                break
        else:
            seeds.append({"rect": pymupdf.Rect(r), "photo": False, "img": pymupdf.Rect()})

    # grow each box with the vector shapes touching it, until nothing changes
    body = [r + (1, 1, -1, -1) for r in body_lines]
    shapes = [r for r in visible_shapes(page)
              if not _ignored_shape(r, page.rect) and not any(r.intersects(b) for b in body)]
    for s in seeds:
        start = pymupdf.Rect(s["rect"])
        grown = True
        while grown:
            grown = False
            near = pymupdf.Rect(s["rect"].x0 - NEAR, s["rect"].y0 - NEAR, s["rect"].x1 + NEAR, s["rect"].y1 + NEAR)
            for r in shapes:
                if near.intersects(r) and not s["rect"].contains(r):
                    s["rect"] |= r
                    grown = True
        s["real"] = s["photo"] or s["rect"] != start
    # merge first (a title just under a photo joins it), then drop text with no
    # chart shapes or photo: that is not a figure
    figs = [{"rect": f["rect"], "photo": f["photo"], "img": f["img"]} for f in _merge(seeds) if f["real"]]
    return sorted(figs, key=lambda f: (round(f["rect"].x0 / 50), f["rect"].y0))


def render(page, fig: dict, out: Path) -> Path:
    """Save the figure's area of the page; JPEG for photos, PNG for charts."""
    clip = fig["rect"] + (-3, -3, 3, 3)
    pix = page.get_pixmap(clip=clip & page.rect, dpi=DPI)
    path = out.with_suffix(".jpg" if fig["photo"] else ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fig["photo"]:
        pix.save(path, jpg_quality=80)
    else:
        pix.save(path)
    return path
