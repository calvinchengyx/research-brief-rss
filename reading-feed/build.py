"""Build the reading-feed page (index.html) and OPML file from sources.yaml."""

from datetime import date
from html import escape
from pathlib import Path
from xml.sax.saxutils import quoteattr

import yaml

HERE = Path(__file__).parent
TAGS = {
    "F": "Feminism & Chinese platforms",
    "L": "Corpus & LLM coding",
    "D": "Disinformation & Telegram",
}
CHECKS = {
    "ok": ("Fetched", "Feed fetched and parsed on the build date."),
    "page": ("From publisher page", "URL copied from the publisher's page for this venue."),
    "pattern": ("Test once", "Publisher's standard feed address; the publisher blocks automated checks."),
}


def load():
    sections = yaml.safe_load((HERE / "sources.yaml").read_text())["sections"]
    for s in sections:
        s["sources"].sort(key=lambda x: (-(x["quality"] + x["fit"]), -x["quality"]))
    return sections


def dots(n):
    return "●" * n + "○" * (5 - n)


def build_opml(sections, today):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "  <head>",
        "    <title>Calvin reading feed</title>",
        f"    <dateCreated>{today.isoformat()}</dateCreated>",
        "  </head>",
        "  <body>",
    ]
    for s in sections:
        lines.append(f"    <outline text={quoteattr(s['name'])} title={quoteattr(s['name'])}>")
        for x in s["sources"]:
            site = f" htmlUrl={quoteattr(x['site'])}" if x.get("site") else ""
            lines.append(
                f"      <outline type=\"rss\" text={quoteattr(x['name'])} title={quoteattr(x['name'])}"
                f" xmlUrl={quoteattr(x['url'])}{site}/>"
            )
        lines.append("    </outline>")
    lines += ["  </body>", "</opml>", ""]
    return "\n".join(lines)


def build_html(sections, today):
    total = sum(len(s["sources"]) for s in sections)
    toc = "".join(
        f'<a href="#{s["id"]}">{escape(s["name"])} <span>{len(s["sources"])}</span></a>' for s in sections
    )
    chips = "".join(
        f'<button class="chip" data-tag="{k}" aria-pressed="false"><b>{k}</b> {escape(v)}</button>'
        for k, v in TAGS.items()
    )
    body = []
    for s in sections:
        rows = []
        for i, x in enumerate(s["sources"], 1):
            label, why = CHECKS[x["check"]]
            tags = "".join(f'<span class="tag t{t}" title="{escape(TAGS[t])}">{t}</span>' for t in x["tags"])
            name = escape(x["name"])
            if x.get("site"):
                name = f'<a href="{escape(x["site"])}">{name}</a>'
            note = f'<p class="note">{escape(x["note"])}</p>' if x.get("note") else ""
            rows.append(
                f'<li class="src" data-tags="{" ".join(x["tags"])}">'
                f'<span class="rank">{i}</span>'
                f'<div class="main"><div class="name">{name}</div>{note}'
                f'<div class="feed"><code>{escape(x["url"])}</code>'
                f'<button class="copy" data-url="{escape(x["url"])}">Copy</button></div></div>'
                f'<div class="meta">'
                f'<div><span class="k">Quality</span><span class="d" aria-label="{x["quality"]} of 5">{dots(x["quality"])}</span></div>'
                f'<div><span class="k">Fit</span><span class="d" aria-label="{x["fit"]} of 5">{dots(x["fit"])}</span></div>'
                f'<div class="tags">{tags}</div>'
                f'<div class="chk c{x["check"]}" title="{escape(why)}">{label}</div>'
                f"</div></li>"
            )
        intro = f'<p class="intro">{escape(s["intro"])}</p>' if s.get("intro") else ""
        body.append(
            f'<section id="{s["id"]}"><h2>{escape(s["name"])}</h2>{intro}<ol>{"".join(rows)}</ol></section>'
        )
    return TEMPLATE.format(
        today=today.strftime("%-d %B %Y"), total=total, toc=toc, chips=chips, body="".join(body)
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Curated Reading Feed</title>
<style>
:root {{
  --bg: #faf9f6; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #e4e2dc;
  --accent: #8a3b12; --F: #a3326b; --L: #2f6690; --D: #8a6100;
  --ok: #2e7d32; --page: #2f6690; --pattern: #8a6100; --code: #f2f0ea;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #161614; --panel: #1f1f1c; --ink: #ecebe6; --muted: #a09e97; --line: #34332f;
    --accent: #e39463; --F: #e283b2; --L: #7fb3db; --D: #d8b04a;
    --ok: #7bc47f; --page: #7fb3db; --pattern: #d8b04a; --code: #2a2a26;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #161614; --panel: #1f1f1c; --ink: #ecebe6; --muted: #a09e97; --line: #34332f;
  --accent: #e39463; --F: #e283b2; --L: #7fb3db; --D: #d8b04a;
  --ok: #7bc47f; --page: #7fb3db; --pattern: #d8b04a; --code: #2a2a26;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }}
header h1 {{ font: 600 30px/1.2 Georgia, "Times New Roman", serif; margin: 0 0 8px; }}
header p {{ color: var(--muted); margin: 0 0 6px; max-width: 70ch; }}
a {{ color: var(--accent); }}
.toc {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0 12px; }}
.toc a {{ text-decoration: none; border: 1px solid var(--line); background: var(--panel);
  padding: 4px 10px; border-radius: 999px; font-size: 13px; color: var(--ink); }}
.toc a span {{ color: var(--muted); }}
.filters {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; font-size: 13px; color: var(--muted); }}
.chip {{ font: inherit; font-size: 13px; cursor: pointer; border: 1px solid var(--line); background: var(--panel);
  color: var(--ink); padding: 4px 10px; border-radius: 999px; }}
.chip[aria-pressed="true"] {{ border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }}
.legend {{ font-size: 13px; color: var(--muted); margin: 4px 0 0; }}
section {{ margin-top: 36px; }}
h2 {{ font: 600 20px/1.3 Georgia, serif; border-bottom: 1px solid var(--line); padding-bottom: 6px; margin: 0 0 4px; }}
.intro {{ color: var(--muted); font-size: 14px; max-width: 75ch; }}
ol {{ list-style: none; padding: 0; margin: 0; }}
.src {{ display: grid; grid-template-columns: 28px minmax(0, 1fr) 190px; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--line); }}
.src.hidden {{ display: none; }}
.main {{ min-width: 0; }}
.rank {{ color: var(--muted); font-variant-numeric: tabular-nums; padding-top: 1px; }}
.name {{ font-weight: 600; }}
.name a {{ color: var(--ink); text-decoration-color: var(--line); }}
.note {{ margin: 2px 0 0; color: var(--muted); font-size: 14px; }}
.feed {{ display: flex; gap: 8px; align-items: center; margin-top: 6px; min-width: 0; }}
.feed code {{ font-size: 12px; background: var(--code); padding: 2px 6px; border-radius: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }}
.copy {{ font: inherit; font-size: 12px; cursor: pointer; border: 1px solid var(--line); background: var(--panel);
  color: var(--ink); border-radius: 4px; padding: 2px 8px; flex: none; }}
.meta {{ font-size: 13px; display: grid; gap: 3px; }}
.meta .k {{ display: inline-block; width: 52px; color: var(--muted); }}
.meta .d {{ letter-spacing: 1px; color: var(--accent); }}
.tag {{ display: inline-block; font-size: 11px; font-weight: 700; border-radius: 3px; padding: 0 5px; margin-right: 4px; color: var(--panel); }}
.tF {{ background: var(--F); }} .tL {{ background: var(--L); }} .tD {{ background: var(--D); }}
.chk {{ font-size: 12px; }}
.cok {{ color: var(--ok); }} .cpage {{ color: var(--page); }} .cpattern {{ color: var(--pattern); }}
footer {{ margin-top: 40px; color: var(--muted); font-size: 13px; }}
@media (max-width: 640px) {{
  .src {{ grid-template-columns: 24px minmax(0, 1fr); }}
  .meta {{ grid-column: 2; grid-template-columns: 1fr 1fr; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Curated reading feed</h1>
  <p>{total} journals, conference proceedings, preprint categories and scholars for computational social science on
  online feminism in China, LLM-based content coding, and gendered disinformation on Telegram. Each section is ranked by
  quality plus fit to that work. Import <code>calvin-reading-feed.opml</code> into any RSS reader to subscribe to all of them.</p>
  <p>Built {today}.</p>
</header>
<nav class="toc">{toc}</nav>
<div class="filters">Show only: {chips}</div>
<p class="legend">Feed check: <span class="cok">Fetched</span> = fetched and parsed on the build date ·
<span class="cpage">From publisher page</span> = URL taken from the journal's own page ·
<span class="cpattern">Test once</span> = publisher's standard address, but the publisher blocks automated checks.</p>
{body}
<footer>Source list: <code>reading-feed/sources.yaml</code>. Edit it and run <code>python reading-feed/build.py</code> to rebuild this page and the OPML file.</footer>
</div>
<script>
const active = new Set();
document.querySelectorAll('.chip').forEach(b => b.addEventListener('click', () => {{
  const t = b.dataset.tag;
  active.has(t) ? active.delete(t) : active.add(t);
  b.setAttribute('aria-pressed', active.has(t));
  document.querySelectorAll('.src').forEach(li => {{
    const tags = li.dataset.tags.split(' ');
    li.classList.toggle('hidden', active.size > 0 && ![...active].some(x => tags.includes(x)));
  }});
}}));
document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', async () => {{
  try {{ await navigator.clipboard.writeText(b.dataset.url); b.textContent = 'Copied'; }}
  catch (e) {{ b.textContent = 'Select the URL'; }}
  setTimeout(() => b.textContent = 'Copy', 1500);
}}));
</script>
</body>
</html>
"""


def main():
    sections = load()
    today = date.today()
    (HERE / "index.html").write_text(build_html(sections, today))
    (HERE / "calvin-reading-feed.opml").write_text(build_opml(sections, today))
    print(f"Wrote {sum(len(s['sources']) for s in sections)} sources")


if __name__ == "__main__":
    main()
