"""The 20-article cap (README section 6) and Editor's picks."""

from __future__ import annotations

from .models import Article


def rank_key(a: Article):
    # Journal/conference papers, then followed scholars' work elsewhere (their
    # preprints before other preprints); relevance breaks ties.
    if a.journal_hit:
        tier = 0
    elif a.scholar_hit:
        tier = 1 if not a.is_preprint else 2
    else:
        tier = 3
    return (tier, -a.relevance, a.date)


def is_watch(a: Article) -> bool:
    """Shown under Scholar watch: a followed scholar's work outside the listed journals."""
    return a.scholar_hit and not a.journal_hit


def apply_cap(articles: list[Article], settings: dict) -> tuple[list[Article], list[Article]]:
    """Returns (selected, overflow).

    Order of filling: top priority, Scholar watch (up to its max), then topics in
    `topic_priority`, keeping each quota topic's minimum free until it is filled.
    """
    max_n = int(settings.get("max_articles", 20))
    ordered = sorted(articles, key=rank_key)
    if len(ordered) <= max_n:
        return ordered, []

    topic_order = list(settings.get("topic_priority") or [])
    quota = dict(settings.get("topic_quota") or {})
    watch_max = int((settings.get("scholar_watch") or {}).get("max", 5))

    priority = [a for a in ordered if a.top_priority]
    rest = [a for a in ordered if not a.top_priority]
    groups = {"_watch": [a for a in rest if is_watch(a)]}
    for t in topic_order:
        groups[t] = [a for a in rest if not is_watch(a) and a.topic == t]
    groups["_other"] = [a for a in rest if not is_watch(a) and a.topic not in topic_order]

    order = ["_watch"] + topic_order
    quota["_watch"] = {"min": 0, "max": watch_max}
    taken = {g: 0 for g in groups}
    slots = max_n - min(len(priority), max_n)

    def reserved_after(i: int) -> int:
        return sum(min(quota[g].get("min", 0), len(groups[g])) for g in order[i + 1:] if g in quota)

    for i, g in enumerate(order):
        cap = quota[g].get("max", len(groups[g])) if g in quota else len(groups[g])
        n = max(0, min(cap, len(groups[g]), slots - reserved_after(i)))
        taken[g] = n
        slots -= n

    # Leftover slots: quota topics beyond their max, in priority order
    for g in [t for t in topic_order if t in quota] + ["_other"]:
        extra = min(slots, len(groups[g]) - taken[g])
        taken[g] += extra
        slots -= extra

    selected = priority[:max_n]
    overflow = priority[max_n:]
    for g, items in groups.items():
        selected += items[:taken[g]]
        overflow += items[taken[g]:]
    return sorted(selected, key=rank_key), sorted(overflow, key=rank_key)


def mark_editors_picks(selected: list[Article], n: int) -> None:
    candidates = sorted((a for a in selected if a.relevance >= 6), key=lambda a: -a.relevance)
    for a in candidates[:n]:
        a.editors_pick = True
