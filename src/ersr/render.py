"""Render one article as a standalone HTML page (M6)."""
from html import escape

STYLE = """
:root { --bg: #fdfcf9; --fg: #1d1d1b; --muted: #6b6b66; --accent: #e3120b; --rule: #e2e0da; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --accent: #ff5a4f; --rule: #33322f; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 18px/1.6 Georgia, "Times New Roman", serif; }
main { max-width: 42rem; margin: 0 auto; padding: 2rem 16px 4rem; }
.meta { font: 600 0.8rem/1.4 system-ui, sans-serif; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.rubric { color: var(--accent); }
h1 { font-size: 2rem; line-height: 1.2; margin: .4rem 0 .6rem; }
.standfirst { font-size: 1.15rem; color: var(--muted); margin: 0 0 1.2rem; }
.dateline { font: 600 .75rem system-ui, sans-serif; letter-spacing: .06em; color: var(--muted); }
h2 { font-size: 1.15rem; margin: 2rem 0 .4rem; }
figure { margin: 1.6rem 0; }
figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; background: #fff; }
figcaption { font: .8rem system-ui, sans-serif; color: var(--muted); margin-top: .3rem; }
.signature { font-style: italic; color: var(--muted); margin: -.4rem 0 1.4rem; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rule); font: .8rem system-ui, sans-serif; color: var(--muted); }
"""


def render_article(a: dict, figures_url: str = "figures") -> str:
    parts = []
    meta = " · ".join(escape(x) for x in (a["section"],) if x)
    rubric = f' · <span class="rubric">{escape(a["rubric"])}</span>' if a["rubric"] and a["rubric"] != a["headline"] else ""
    parts.append(f'<p class="meta">{meta}{rubric}</p>')
    parts.append(f"<h1>{escape(a['headline'])}</h1>")
    if a["standfirst"]:
        parts.append(f'<p class="standfirst">{escape(a["standfirst"])}</p>')
    if a["dateline"]:
        parts.append(f'<p class="dateline">{escape(a["dateline"])}</p>')
    for b in a["blocks"]:
        if b[0] == "p":
            parts.append(f"<p>{escape(b[1])}</p>")
        elif b[0] == "h":
            parts.append(f"<h2>{escape(b[1])}</h2>")
        elif b[0] == "sig":
            parts.append('<p class="signature">' + "<br>".join(escape(x) for x in b[1].split(" / ")) + "</p>")
        elif b[0] == "fig":
            cap = f"<figcaption>{escape(b[2])}</figcaption>" if b[2] else ""
            parts.append(f'<figure><img src="{escape(figures_url)}/{escape(b[1])}" alt="{escape(b[2])}" loading="lazy">{cap}</figure>')
    first, last = a["pages"]
    where = f"page {first}" if first == last else f"pages {first}–{last}"
    parts.append(f"<footer>The Economist, edition of {escape(a['edition'])}, {where}. Personal copy.</footer>")
    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(a['headline'])}</title>
<style>{STYLE}</style>
</head>
<body><main>
{body}
</main></body>
</html>
"""
