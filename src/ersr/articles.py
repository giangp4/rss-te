"""Split the edition's tagged paragraphs into articles (M5).

Input is pdf_text.edition_pages(): per page, paragraphs tagged [section],
[rubric], [headline], [subhead], [dateline], [figure], or plain body text.
"""
import re
import unicodedata

from ersr.pdf_text import SENTENCE_END, join_hyphen

TAG = re.compile(r"^\[(\w+)\] (.*)$", re.S)
TOC_ENTRY = re.compile(r"(?<!\S)(\d{1,2}) (.+?)(?= \d{1,2} (?=[A-Z“‘\"])|$)")
WORLD_THIS_WEEK = "The world this week"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def parse(para: str) -> tuple[str, str]:
    m = TAG.match(para)
    return (m.group(1), m.group(2)) if m else ("body", para)


def new_article(section: str, page: int, headline: str = "", rubric: str = "") -> dict:
    return {"section": section, "rubric": rubric, "headline": headline, "standfirst": "",
            "dateline": "", "pages": [page, page], "blocks": [], "flags": []}


def page_section(paras: list[str], header: str) -> str:
    """The page's section: its running header, else a section title printed on it."""
    if header:
        return header
    for para in paras:
        kind, text = parse(para)
        if kind == "section":
            return text.split(" — ")[0]
    return ""


def split_articles(pages: list[tuple[int, list[str], str]]) -> list[dict]:
    """Walk the paragraphs in reading order and group them into articles."""
    articles, cur, section, section_topic = [], None, "", ""
    rubric, pending_figs, prev_kind = "", [], ""

    def auto_article(page):
        """An article for a page without headlines (Letters), named after its section."""
        nonlocal section_topic
        a = new_article(section, page, headline=section)
        a["auto"], a["standfirst"], section_topic = True, section_topic, ""
        articles.append(a)
        return a

    def body_started(a):
        return any(b[0] == "p" for b in a["blocks"])

    for page, paras, header in pages:
        first_on_page = first_text = True
        here = page_section(paras, header)
        if here:
            section = here
            if cur and cur["section"] != here:
                cur = None  # articles never run on into another section
        for para in paras:
            kind, text = parse(para)
            if kind == "unplaced":
                continue
            if kind == "section":
                name, _, topic = text.partition(" — ")
                # The world this week pages have no headlines: the topic names the article
                if name == WORLD_THIS_WEEK:
                    cur = new_article(WORLD_THIS_WEEK, page, headline=topic)
                    articles.append(cur)
                else:
                    section_topic = topic  # e.g. the Letters masthead's list of topics
            elif kind == "rubric":
                rubric = text
            elif kind == "headline":
                if prev_kind == "headline" and cur:
                    cur["headline"] += " " + text  # second line of a two-line headline
                else:
                    # pages without a section name: an all-caps column rubric is one (OBITUARY)
                    sec = section if here else (rubric.capitalize() if rubric.isupper() else section)
                    cur = new_article(sec, page, headline=text, rubric=rubric)
                    cur["blocks"].extend(pending_figs)  # figure right before a title belongs to it
                    pending_figs, rubric = [], ""
                    articles.append(cur)
            elif kind in ("subhead", "dateline"):
                if cur is None:
                    cur = auto_article(page)
                if pending_figs and body_started(cur):
                    cur["blocks"].extend(pending_figs)  # a figure above a sub-heading stays above it
                    pending_figs = []
                if cur.get("auto"):
                    cur["blocks"].append(("h", text))  # no standfirst without a headline
                elif cur and not body_started(cur) and not cur["standfirst"] and kind == "subhead":
                    cur["standfirst"] = text
                elif cur and not body_started(cur) and kind == "dateline":
                    cur["dateline"] = text
                elif cur:
                    cur["blocks"].append(("h", text))
            elif kind == "signature":
                if cur:
                    cur["blocks"].append(("sig", text))
            elif kind == "figure":
                name, _, label = text.partition(": ")
                pending_figs.append(("fig", name, label))
            else:  # body text
                if cur is None:
                    cur = auto_article(page)
                if pending_figs:
                    cur["blocks"].extend(pending_figs)
                    pending_figs = []
                last = cur["blocks"][-1] if cur["blocks"] else None
                if first_text and last and last[0] == "p" and not last[1].endswith(SENTENCE_END):
                    # a sentence cut by the page break: carry on the same paragraph
                    joined = join_hyphen(last[1], text) if last[1].endswith("-") else f"{last[1]} {text}"
                    cur["blocks"][-1] = ("p", joined)
                    cur["pages"][1] = page
                    first_text = False
                    continue
                first_text = False
                if text[:1].islower() and not first_on_page and body_started(cur) \
                        and cur["blocks"][-1][0] == "p" and cur["blocks"][-1][1].endswith((".", "”", "?", "!")):
                    cur["flags"].append(f"p{page}: text starts mid-sentence after a finished one: {text[:40]!r}")
                cur["blocks"].append(("p", text))
                cur["pages"][1] = page
            if kind != "figure":
                prev_kind = kind
            first_on_page = False
        # a page of figures only (the indicators) becomes its own article
        if pending_figs and cur is None:
            cur = new_article(section, page, headline=section)
            articles.append(cur)
        # figures still pending at the end of a page stay with the open article
        if cur and pending_figs:
            cur["blocks"].extend(pending_figs)
            pending_figs = []

    for a in articles:
        b = a["blocks"]
        for n in range(len(b) - 1):
            if b[n][0] == "sig" and b[n + 1][0] == "fig":
                b[n], b[n + 1] = b[n + 1], b[n]  # a picture under a signature illustrates that letter
        move_footer(a)
        a["words"] = sum(len(b[1].split()) for b in a["blocks"] if b[0] == "p")
        a["figures"] = [b[1] for b in a["blocks"] if b[0] == "fig"]
        a["slug"] = slugify(a["headline"] or a["section"])
        if a["words"] < 80 and not (a["figures"] and a["headline"] == a["section"]):
            a["flags"].append(f"only {a['words']} words")
        if not a["rubric"] and a["section"] != WORLD_THIS_WEEK and a["headline"] != a["section"]:
            a["flags"].append("no rubric")
    return articles


def move_footer(a: dict) -> None:
    """Footnotes like '→ Letters should be addressed…' go to the end of the article,
    together with a web address printed in bold right after them."""
    blocks, footer, n = a["blocks"], [], 0
    while n < len(blocks):
        b = blocks[n]
        if b[0] == "p" and b[1].startswith("→"):
            text = b[1]
            # its last lines ('More letters available at:' / 'economist.com/letters') are styled differently
            while n + 1 < len(blocks) and (blocks[n + 1][0] == "sig" or
                                           (blocks[n + 1][0] == "h" and re.search(r"\w\.\w{2,}/", blocks[n + 1][1]))):
                text += " " + blocks.pop(n + 1)[1].replace(" / ", " ")
            footer.append(("p", text))
            blocks.pop(n)
        else:
            n += 1
    blocks.extend(footer)


def parse_contents(paras: list[str]) -> list[tuple[int, str]]:
    """'33 Oil woes 34 Grumbling about leave' -> [(33, 'Oil woes'), (34, 'Grumbling about leave')]."""
    text = " ".join(parse(p)[1] for p in paras if parse(p)[0] in ("body", "subhead"))
    return [(int(n), t.strip()) for n, t in TOC_ENTRY.findall(text) if 1 <= int(n) <= 99]


def to_markdown(a: dict, figures_url: str = "figures") -> str:
    out = [f"# {a['headline']}", ""]
    first, last = a["pages"]
    where = f"page {first}" if first == last else f"pages {first}–{last}"
    meta = " · ".join(x for x in (a["section"], a["rubric"], where) if x)
    out += [f"*{meta}*", ""]
    if a["standfirst"]:
        out += [f"**{a['standfirst']}**", ""]
    if a["dateline"]:
        out += [a["dateline"], ""]
    for b in a["blocks"]:
        if b[0] == "p":
            out += [b[1], ""]
        elif b[0] == "h":
            out += [f"## {b[1]}", ""]
        elif b[0] == "sig":
            out += ["  \n".join(f"*{line}*" for line in b[1].split(" / ")), ""]
        else:
            out += [f"![{b[2]}]({figures_url}/{b[1]})", ""]
    return "\n".join(out)
