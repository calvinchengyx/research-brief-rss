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
    return text if words <= 0 or len(parts) <= words else " ".join(parts[:words]).rstrip(",;:") + " …"


def nice_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%B %Y')}"


def build_context(cfg: Config, selected: list[Article], overflow: list[Article], scholars_quiet: list[str],
                  stats: dict, today: date, test: bool = False, dives: list[Article] | None = None) -> dict:
    """Group articles as the email shows them and give each an ID (A1, A2, B1 ...) in that order."""
    words = int(cfg.settings.get("abstract_words", 0))
    dives = dives or []
    overflow = overflow[:int(cfg.settings.get("overflow_max", 15))] if cfg.settings.get("overflow_footer", True) else []

    priority = [a for a in selected if a.top_priority]
    topic_groups = []
    for t in cfg.topics:
        items = [a for a in selected if a.topic == t["id"] and not a.top_priority and not
                 (a.scholar_hit and not a.journal_hit)]
        if items:
            venues: dict[str, list[Article]] = {}
            for a in items:
                if not a.is_preprint:
                    venues.setdefault(a.venue, []).append(a)
            topic_groups.append((t["name"], venues, [a for a in items if a.is_preprint]))
    watch: dict[str, list[Article]] = {}
    for a in selected:
        if a.scholar_hit and not a.journal_hit:
            watch.setdefault(", ".join(a.scholar_names), []).append(a)

    # IDs follow reading order: one letter per section, numbered within it
    blocks = [dives, priority] + [[a for v in venues.values() for a in v] + pre for _, venues, pre in topic_groups] \
        + [[a for v in watch.values() for a in v], overflow]
    letters = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    for block in blocks:
        if block:
            letter = next(letters)
            for i, a in enumerate(block, 1):
                a.ref = f"{letter}{i}"

    def view(a: Article) -> dict:
        return {
            "ref": a.ref, "title": a.title, "url": a.url, "venue": a.venue or ("Preprint" if a.is_preprint else ""),
            "date": nice_date(a.date),
            "authors": author_line(a), "abstract": short_abstract(a.abstract, words),
            "summary": a.summary, "preprint": a.is_preprint, "pick": a.editors_pick,
            "now_published": a.now_published, "scholars": a.scholar_names,
            "topic": cfg.topic_names.get(a.topic, ""), "dive": a.deep_dive, "requested": a.requested,
        }

    return {
        "date": nice_date(today.isoformat()), "test": test, "stats": stats,
        "dives": [view(a) for a in dives],
        "priority": [view(a) for a in priority],
        "sections": [{"name": name, "venues": [{"venue": v, "articles": [view(a) for a in its]}
                                               for v, its in venues.items()],
                      "preprints": [view(a) for a in pre]} for name, venues, pre in topic_groups],
        "watch": [{"scholar": k, "articles": [view(a) for a in v]} for k, v in watch.items()],
        "quiet": scholars_quiet,
        "picks": [view(a) for a in selected if a.editors_pick],
        "overflow": [view(a) for a in overflow],
    }


def render(context: dict) -> tuple[str, str]:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    return env.get_template("brief.html.j2").render(**context), env.get_template("brief.txt.j2").render(**context)
