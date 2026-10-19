"""Turn the edition PDF into reading-order text (M4).

Steps per page: skip ad pages, drop the running header, find the column starts,
sort lines column by column, then rebuild paragraphs and undo hyphenation.
"""
import collections
import re
from pathlib import Path

import pymupdf

from ersr.figures import find_figures, render

BODY_FONT = "EconomistSerif-Light"   # body size varies: 9pt in most sections, 9.5pt in Leaders
HEADER_Y = 40        # running header ("24 · The Economist · October 10th 2026") sits above this
PARA_GAP = 4         # extra vertical space that separates items (The world this week)
INDENT = 8           # a line starting this much right of its column start opens a paragraph
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})
SPACE_GAP = 0.5      # pt between characters that means a word break the PDF left out
SECTION_BOX = "ALSO IN THIS SECTION"
SECTION_BOX_ENTRY = re.compile(r"^(\d{1,3}|—) \S")


def header_section(page) -> str:
    """Section named in the running header ('Briefing', 'United States'), if any."""
    names = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip().translate(LIGATURES)
                if (s["bbox"][1] < HEADER_Y and s["flags"] & 16 and t and t != "The Economist"
                        and not t.isdigit()):
                    names.append(t)
    return " ".join(names)


def is_content_page(page) -> bool:
    """Content pages carry the 'The Economist' running header; ads and the cover don't."""
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["bbox"][1] < HEADER_Y and s["text"].strip() == "The Economist":
                    return True
    return False


def span_text(span) -> str:
    """Rebuild a span's text from its characters, restoring spaces some tightly set
    pages (The world this week, Letters) omit: letters touch, words have a ~1pt gap."""
    out, prev = "", None
    for c in span["chars"]:
        if prev is not None and c["c"] != " " and prev["c"] != " " and c["bbox"][0] - prev["bbox"][2] > SPACE_GAP:
            out += " "
        out += c["c"]
        prev = c
    return out.translate(LIGATURES)


def line_text(line) -> str:
    """Join spans, adding a space where PyMuPDF split words into separate spans."""
    out, prev_x1 = "", None
    for s in line["spans"]:
        t = s["text"]
        if prev_x1 is not None and s["bbox"][0] - prev_x1 > 1 and not out.endswith(" ") and not t.startswith(" "):
            out += " "
        out += t
        prev_x1 = s["bbox"][2]
    return " ".join(out.split())


def body_size(raw_lines) -> float:
    """Most common size of the body font on the page, weighted by characters."""
    sizes = collections.Counter()
    for l in raw_lines:
        for s in l["spans"]:
            if s["font"] == BODY_FONT:
                sizes[round(s["size"], 1)] += len(s["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 9.0


def kind(span, body: float = 9.0) -> str:
    """Rough role of a line from its first span's font, for later splitting."""
    font, size = span["font"], round(span["size"], 1)
    if size >= 17 and "Sans" in font:
        return "section"
    if size >= 17 and "SemiBol" in font:
        return "headline"
    if 14 <= size < 17 and font.startswith("EconomistSerif-SemiBold"):
        return "section"  # page masthead, e.g. Letters
    if 14 <= size < 17 and "LightIt" in font:
        return "topic"    # the masthead's list of topics
    # columns (Bagehot, Schumpeter…), obituary, by invitation: centred, different fonts
    if size >= 17 and font.startswith("EconomistSerifSC-Bold"):
        return "rubric"
    if size >= 17 and (font.startswith("EconomistSerif-LightItal") or font.startswith("EconomistSerifLF")):
        return "headline"  # italic column headlines; SerifLF-Regular in boxed articles
    if 9.9 <= size <= 12 and font.startswith("EconomistSerif") and "LightIt" in font:
        return "subhead"   # italic standfirst under a column headline
    if size >= 2 * body and font == BODY_FONT:
        return "dropcap"
    body_sizes = (9.0, 9.5, body)  # Leaders set body text at 9.5pt, most pages at 9pt
    if font == BODY_FONT and size in body_sizes:
        return "body"
    if font.startswith("EconomistSerif-SemiBold") and size in body_sizes:
        return "subhead"  # standfirst under a headline, or a crosshead inside an article
    if font.startswith("EconomistSerif") and size in body_sizes:
        return "body"  # small caps and italics inside body text
    if font.startswith("EconomistSans-SemiBold") and size in (9.0, body):
        return "rubric"
    if font.startswith("EconomistSans-Medium") and size <= 5.5:
        return "dateline"
    if "Sans" in font and size <= 8:
        return "chart"  # chart labels, captions, sources
    return "other"


def column_starts(lines) -> list[float]:
    """Body-text x0 values used by at least 5 lines, minus paragraph-indent positions."""
    xs = collections.Counter(round(l["bbox"][0]) for l, k in lines if k == "body")
    starts = sorted(x for x, n in xs.items() if n >= 5)
    cols = []
    for x in starts:
        if not cols or x - cols[-1] > 20:
            cols.append(x)
    return cols or [0]


def article_starts(lines, cols) -> list[tuple[float, list[float]]]:
    """(top y, columns covered) for each title block that starts mid-page.
    A title block is a headline plus the rubric, standfirst and dateline lines that
    overlap it horizontally; centred blocks on column pages can span every column."""
    heading = ("rubric", "headline", "subhead", "dateline")
    starts, used = [], set()
    for h, k in sorted(lines, key=lambda lk: lk[0]["bbox"][1]):
        if k != "headline" or id(h) in used:
            continue
        hx0, hy0, hx1 = h["bbox"][0], h["bbox"][1], h["bbox"][2]
        block = [l for l, k2 in lines if k2 in heading and -30 <= l["bbox"][1] - hy0 < 110
                 and l["bbox"][0] < hx1 + 120 and l["bbox"][2] > hx0 - 120]
        used.update(id(l) for l in block)
        x0, x1 = min(l["bbox"][0] for l in block), max(l["bbox"][2] for l in block)
        top = min(l["bbox"][1] for l in block) - 3
        bounds = cols + [10_000]
        covered = [c for c, nc in zip(cols, bounds[1:]) if c < x1 - 5 and nc > x0 + 5]
        body_above = any(k2 == "body" and l["bbox"][1] < top and any(abs(l["bbox"][0] - c) < 20 for c in covered)
                         for l, k2 in lines)
        if body_above:  # a title block at the top of its columns doesn't split anything
            starts.append((top, covered))
    return starts

def is_real_rubric(l, lines) -> bool:
    """A rubric has a headline right below it (left-aligned or centred above it);
    chart titles share its style but don't."""
    x0, y1, x1 = l["bbox"][0], l["bbox"][3], l["bbox"][2]
    return any(k == "headline" and h["bbox"][0] < x1 and h["bbox"][2] > x0 and -2 <= h["bbox"][1] - y1 < 25
               for h, k in lines)


def replace_figures(page, lines, figures_dir):
    """Swap chart/caption lines for one synthetic 'figure' line per figure box."""
    lines = [(l, "chart" if k == "rubric" and not is_real_rubric(l, lines) else k) for l, k in lines]
    is_fig_text = lambda k: k in ("chart", "other")
    # the first page of each section lists its other articles: print navigation, drop it
    if any(SECTION_BOX in line_text(l) for l, k in lines):
        lines = [(l, k) for l, k in lines
                 if not (is_fig_text(k) and (SECTION_BOX in line_text(l) or SECTION_BOX_ENTRY.match(line_text(l))))]
    figs = find_figures(page, [pymupdf.Rect(l["bbox"]) for l, k in lines if is_fig_text(k)],
                        [pymupdf.Rect(l["bbox"]) for l, k in lines if k == "body"])
    kept, inside = [], {n: [] for n in range(len(figs))}
    for l, k in lines:
        r = pymupdf.Rect(l["bbox"])
        hit = next((n for n, f in enumerate(figs) if (f["rect"] + (-2, -2, 2, 2)).contains(r)), None)
        if hit is not None and is_fig_text(k):
            inside[hit].append((r.y0, r.x0, line_text(l)))
        else:
            kept.append((l, k))
    for n, f in enumerate(figs):
        name = f"p{page.number + 1}-{n + 1}"
        if figures_dir:
            name = render(page, f, figures_dir / name).name
        else:
            name += ".jpg" if f["photo"] else ".png"
        texts, seen = [], set()
        for y0, x0, t in sorted(inside[n]):
            if (round(y0), round(x0), t) not in seen:  # map labels are drawn several times (halo + text)
                seen.add((round(y0), round(x0), t))
                if not f["photo"] or y0 >= f["img"].y1 - 2:  # photo/map: only the caption below counts
                    texts.append(t)
        # chart: title is its first line; photo: the caption under it
        texts = [t for t in texts if any(c.isalpha() for c in t)]  # skip chart number boxes ('3')
        label = (" ".join(texts) if f["photo"] else (texts[0] if texts else "")).strip()
        rect = f["rect"]
        kept.append(({"bbox": tuple(rect), "spans": [{"text": f"{name}: {label}" if label else name,
                                                     "bbox": tuple(rect)}]}, "figure"))
    return kept


def panels(page, lines) -> list[pymupdf.Rect]:
    """Shaded boxes that hold article text (boxed articles, columns set in a box)."""
    body = [pymupdf.Rect(l["bbox"]) for l, k in lines if k == "body"]
    found = []
    for d in page.get_drawings():
        r = d["rect"]
        if d.get("fill") and r.width > 150 and r.height > 150 and sum(r.contains(b) for b in body) >= 5:
            if not any(f.contains(r) for f in found):
                found = [f for f in found if not r.contains(f)] + [r]
    return found


def bold_block_starts(lines, cols, col_of) -> list[tuple[float, list[float]]]:
    """A long all-bold block that starts at the same height in neighbouring columns
    (a letter set in bold as a sidebar) cuts those columns like a mid-page headline."""
    runs = []  # (column, top y) of each run of 4+ bold lines
    bold = sorted((l for l, k in lines if k == "subhead"), key=lambda l: (col_of(l), l["bbox"][1]))
    run = []
    for l in bold + [None]:
        if run and (l is None or col_of(l) != col_of(run[-1]) or l["bbox"][1] - run[-1]["bbox"][3] > 4):
            if len(run) >= 4:
                runs.append((col_of(run[0]), run[0]["bbox"][1]))
            run = []
        if l is not None:
            run.append(l)
    starts = []
    for c, y in runs:
        covered = sorted({c2 for c2, y2 in runs if abs(y2 - y) < 3})
        body_above = any(k == "body" and col_of(l) in covered and l["bbox"][1] < y for l, k in lines)
        if len(covered) > 1 and body_above and (y - 3, covered) not in starts:
            starts.append((y - 3, covered))
    return starts


def order_region(lines) -> list[tuple[dict, str, float]]:
    """Sort one region's lines into reading order: band by band (a mid-page title
    block starts a new band in the columns it spans), then column by column.
    Returns (line, kind, column start)."""
    if not lines:
        return []
    cols = column_starts(lines)

    def col_of(l):
        x = l["bbox"][0]
        return max((c for c in cols if c <= x + 3), default=cols[0])

    starts = article_starts(lines, cols) + bold_block_starts(lines, cols, col_of)

    def band_of(l):
        """How many article starts sit above this line in its column. Text below a
        mid-page headline is read after the text above it, so articles don't interleave."""
        return sum(1 for y, covered in starts if col_of(l) in covered and l["bbox"][1] >= y)

    band_body_top = {}  # band -> top of its highest body line
    for l, k in lines:
        if k == "body":
            b = band_of(l)
            band_body_top[b] = min(band_body_top.get(b, 1e9), l["bbox"][1])

    def sort_key(lk):
        l, k = lk
        band = band_of(l)
        offset = abs(l["bbox"][0] - col_of(l)) > 3  # centred or offset, not at a column start
        if k in ("rubric", "headline", "subhead", "dateline") and offset and l["bbox"][3] <= band_body_top.get(band, -1e9) + 2:
            return (band, 0, l["bbox"][1], l["bbox"][0])  # title block above its band's text (often centred)
        return (band, col_of(l), l["bbox"][1] - (3 if k == "dropcap" else 0), l["bbox"][0])

    return [(l, k, col_of(l)) for l, k in sorted(lines, key=sort_key)]


def page_lines(page, figures_dir: Path | None = None) -> list[tuple[str, str, float, float]]:
    """(kind, text, indent, gap above) for each line on the page, in reading order.
    Charts and photos become one ('figure', 'p24-1.png: title') line each; their
    images are written to figures_dir when given."""
    raw = [l for b in page.get_text("rawdict")["blocks"] for l in b.get("lines", [])]
    for l in raw:
        for s in l["spans"]:
            s["text"] = span_text(s)
    body = body_size(raw)
    lines = []
    for l in raw:
        spans = [s for s in l["spans"] if s["text"].strip() and s["size"] > 2]
        if not spans or l["bbox"][1] < HEADER_Y:
            continue
        k = kind(spans[0], body)
        if k == "subhead" and any(kind(sp, body) != "subhead" for sp in spans):
            k = "body"  # bold lead-in words inside a paragraph, not a heading
        if k == "body" and all(("Ital" in sp["font"] or "SC" in sp["font"]) for sp in spans):
            k = "sig"  # a line all in italics/small caps: letter signatures, author bios
        if k == "section":
            # 'Briefing' + 'Turbulent bond markets', 'Letters' + 'whether to have surgery,'
            head = [sp for sp in spans if sp["font"] == spans[0]["font"]]
            rest = " ".join(sp["text"].strip() for sp in spans[len(head):]).strip()
            topic = rest
            text = " ".join(sp["text"].strip() for sp in head) + (f" — {topic}" if topic else "")
            spans = [{**spans[0], "text": text, "chars": []}]
        lines.append(({**l, "spans": spans}, k))
    lines = replace_figures(page, lines, figures_dir)

    # boxed articles sit on a shaded panel with their own columns: read the text
    # outside the panels first (often a continuation from the previous page), then each panel
    boxes = panels(page, lines)
    regions = [[] for _ in range(len(boxes) + 1)]
    for l, k in lines:
        r = pymupdf.Rect(l["bbox"])
        inside = next((n for n, p in enumerate(boxes, 1) if (p + (-2, -2, 2, 2)).contains(r)), 0)
        regions[inside].append((l, k))
    ordered = [(l, k, (n, col)) for n, region in enumerate(regions) for l, k, col in order_region(region)]

    merged = []  # (kind, text, indent, gap above, bottom_y, (region, col))
    for l, k, col in ordered:
        text, (top, bottom) = line_text(l), (l["bbox"][1], l["bbox"][3])
        prev = merged[-1] if merged else None
        if prev and k == prev[0] == "body" and prev[5] == col and abs(prev[4] - bottom) < 2:
            merged[-1] = (prev[0], f"{prev[1]} {text}", prev[2], prev[3], prev[4], col)  # piece of a justified line
        else:
            gap = top - prev[4] if prev and prev[5] == col else None  # None: new column
            merged.append((k, text, l["bbox"][0] - col[1], gap, bottom, col))
    out = [(k, t, i, g) for k, t, i, g, _, _ in merged]
    # four or more bold lines in a row are a bold paragraph (a letter set in bold), not headings
    n = 0
    while n < len(out):
        end = n
        while end < len(out) and out[end][0] == "subhead" and (end == n or (out[end][3] is not None and out[end][3] < PARA_GAP)):
            end += 1
        if end - n >= 4:
            first = out[n][1]
            keep_title = len(first) <= 30 and not first.endswith(("-", ","))  # 'It’s Miller time'
            out[n + keep_title:end] = [("body", t, i, g) for _, t, i, g in out[n + keep_title:end]]
        n = max(end, n + 1)
    for n, (k, t, i, g) in enumerate(out):
        nxt = out[n + 1] if n + 1 < len(out) else None
        # an all-bold line that runs on into lowercase text is part of a sentence
        if k == "subhead" and nxt and nxt[0] == "body" and (t.endswith("-") or nxt[1][:1].islower()):
            out[n] = ("body", t, i, g)
    return out


def _load_words() -> set[str]:
    try:
        return {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8")}
    except OSError:
        return set()


WORDS = _load_words()
SENTENCE_END = (".", "”", "?", "!", "’")
ARROWS = {"▸", "⏩", "◀", "▶"}


def join_dropcap(cap: str, text: str) -> str:
    """'I' + 'T IS A BLEAK' -> 'IT IS…'; 'A' + 'PREACHER KICKED' -> 'A PREACHER…'."""
    first = text.split(" ", 1)[0]
    letters = "".join(c for c in first if c.isalpha()).lower()
    capl = "".join(c for c in cap if c.isalpha()).lower()
    if letters and letters in WORDS and capl + letters not in WORDS:
        return f"{cap} {text}"
    return cap + text


def join_hyphen(para: str, text: str) -> str:
    """'add-' + 'ing' -> 'adding', but 'two-' + 'term' stays 'two-term'."""
    head = para[:-1].rsplit(" ", 1)[-1]
    tail = text.split(" ", 1)[0]
    alpha = lambda w: "".join(c for c in w if c.isalpha()).lower()
    joined, h, t = alpha(head + tail), alpha(head.rsplit("-", 1)[-1]), alpha(tail)
    if head[-2:-1].isdigit() or (joined not in WORDS and h in WORDS and t in WORDS):
        return para + text  # a real hyphen that happened to fall at the line end
    return para[:-1] + text


def join_paragraphs(lines) -> list[str]:
    """Merge consecutive lines into paragraphs; non-body lines stay on their own, tagged.
    Chart labels are collected into one [figure] block at the end of the page."""
    out, para, figure, cap, pending, sub, signature = [], "", [], "", [], "", []
    beside_cap = 0  # lines next to a dropcap are indented to make room for it

    def flush():
        nonlocal para, sub
        if para:
            out.append(para)
        if sub:
            out.append(f"[subhead] {sub}")
        if signature:
            out.append("[signature] " + " / ".join(signature))
            signature.clear()
        para = sub = ""
        out.extend(pending)  # figures go after the paragraph or heading they interrupted
        pending.clear()

    for k, text, indent, gap in lines:
        text = " ".join(w for w in text.split() if w not in ARROWS)
        if not text:
            continue
        if k == "topic":
            if out and out[-1].startswith("[section]"):
                out[-1] += (" " if " — " in out[-1] else " — ") + text
            continue
        # a run of italic/small-caps lines after a finished sentence: a letter's signature
        if k == "sig" and (signature or not para or para.endswith(SENTENCE_END)):
            if not signature:
                flush()
            signature.append(text)
            continue
        if signature and k in ("subhead", "body") and gap is not None and gap < PARA_GAP and indent <= INDENT:
            signature.append(text)  # job title or place under the name (a bold place in a bold letter)
            continue
        if signature:
            flush()
        if k == "sig":
            k = "body"  # italic words that happen to fill a line mid-paragraph
        if k == "dropcap":
            flush()
            cap = text  # joined onto the next body line
        elif k == "body":
            if sub:
                flush()
            if cap:
                para, cap, beside_cap = join_dropcap(cap, text), "", 2
            elif para.endswith("-") and text[:1].islower():
                para = join_hyphen(para, text)  # undo end-of-line hyphenation
            elif beside_cap:
                beside_cap -= 1
                para = f"{para} {text}"
            elif para and (indent > INDENT or ((gap or 0) > PARA_GAP and para.endswith(SENTENCE_END))):
                flush()
                para = text
            else:
                para = f"{para} {text}" if para else text
        elif k == "subhead":
            if sub and gap is not None and gap < PARA_GAP:  # next line of a multi-line standfirst
                sub = join_hyphen(sub, text) if sub.endswith("-") and text[:1].islower() else f"{sub} {text}"
            else:
                flush()
                sub = text
        elif k == "figure":
            if para or sub:
                pending.append(f"[figure] {text}")
            else:
                out.append(f"[figure] {text}")
        elif k in ("chart", "other"):
            figure.append(text)  # stray chart-like text that no figure box took
        else:
            flush()
            out.append(f"[{k}] {text}")
    flush()
    if figure:
        out.append("[unplaced] " + " | ".join(figure))
    return out


def edition_pages(pdf: Path, figures_dir: Path | None = None) -> tuple[list[tuple[int, list[str], str]], list[str], dict]:
    """([(page number, tagged paragraphs, header section)], contents-page paragraphs, stats)."""
    doc = pymupdf.open(pdf)
    pages, contents, stats = [], [], {"pages": doc.page_count, "ads": [], "content": 0}
    for i, page in enumerate(doc, start=1):
        if not is_content_page(page):
            stats["ads"].append(i)
            continue
        first = join_paragraphs(page_lines(page))  # first pass writes no images
        if "[section] Contents" in first:
            stats.setdefault("contents", []).append(i)
            contents.extend(first)
            continue
        stats["content"] += 1
        pages.append((i, join_paragraphs(page_lines(page, figures_dir)), header_section(page)))
    return pages, contents, stats


def edition_text(pdf: Path, figures_dir: Path | None = None) -> tuple[str, dict]:
    pages, _, stats = edition_pages(pdf, figures_dir)
    parts = []
    for i, paras, _ in pages:
        parts.append(f"===== page {i} =====")
        parts.extend(paras)
    return "\n\n".join(parts) + "\n", stats
