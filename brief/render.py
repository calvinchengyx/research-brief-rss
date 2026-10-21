"""Render the newsletter (HTML + plain text) in the Nature e-alert layout."""

from __future__ import annotations

from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import TEMPLATE_DIR, Config
from .models import Article


def author_line(a: Article) -> list[dict]:
    """Nature style: first two, [...], last. Followed scholars are always shown (in bold)."""
    authors = a.authors
    if len(authors) <= 4:
        shown = authors
    else:
        keep = {0, 1, len(authors) - 1} | {i for i, x in enumerate(authors) if x.followed}
        shown, prev = [], -1
        for i in sorted(keep):
            if i != prev + 1:
                shown.append(None)  # gap marker
            shown.append(authors[i])
            prev = i
    return [{"gap": True} if x is None else {"name": x.name, "bold": x.followed} for x in shown]


def short_abstract(text: str, words: int) -> str:
    parts = text.split()
    return text if len(parts) <= words else " ".join(parts[:words]).rstrip(",;:") + " …"


def nice_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%B %Y')}"


def build_context(cfg: Config, selected: list[Article], overflow: list[Article], scholars_quiet: list[str],
                  stats: dict, today: date, test: bool = False) -> dict:
    words = int(cfg.settings.get("abstract_words", 80))

    def view(a: Article) -> dict:
        return {
            "title": a.title, "url": a.url, "venue": a.venue, "date": nice_date(a.date),
            "authors": author_line(a), "abstract": short_abstract(a.abstract, words),
            "summary": a.summary, "preprint": a.is_preprint, "pick": a.editors_pick,
            "now_published": a.now_published, "scholars": a.scholar_names,
            "topic": cfg.topic_names.get(a.topic, ""),
        }

    priority = [view(a) for a in selected if a.top_priority]
    sections = []
    for t in cfg.topics:
        items = [a for a in selected if a.topic == t["id"] and not a.top_priority and not
                 (a.scholar_hit and not a.journal_hit)]
        if items:
            sections.append({
                "name": t["name"],
                "venues": _group_by_venue([view(a) for a in items if not a.is_preprint]),
                "preprints": [view(a) for a in items if a.is_preprint],
            })
    watch: dict[str, list[dict]] = {}
    for a in selected:
        if a.scholar_hit and not a.journal_hit:
            watch.setdefault(", ".join(a.scholar_names), []).append(view(a))
    return {
        "date": nice_date(today.isoformat()), "test": test, "stats": stats,
        "priority": priority, "sections": sections,
        "watch": [{"scholar": k, "articles": v} for k, v in watch.items()],
        "quiet": scholars_quiet,
        "picks": [view(a) for a in selected if a.editors_pick],
        "overflow": [view(a) for a in overflow] if cfg.settings.get("overflow_footer", True) else [],
    }


def _group_by_venue(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["venue"], []).append(it)
    return [{"venue": v, "articles": its} for v, its in groups.items()]


def render(context: dict) -> tuple[str, str]:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    return env.get_template("brief.html.j2").render(**context), env.get_template("brief.txt.j2").render(**context)
