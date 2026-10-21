"""The 20-article cap (README section 6) and Editor's picks."""

from __future__ import annotations

from .models import Article


def rank_key(a: Article):
    # Followed scholars first (journal articles before their preprints), then
    # journal/conference papers, then other preprints; relevance breaks ties.
    if a.scholar_hit:
        tier = 0 if not a.is_preprint else 1
    else:
        tier = 2 if not a.is_preprint else 3
    return (tier, -a.relevance, a.date)


def apply_cap(articles: list[Article], settings: dict) -> tuple[list[Article], list[Article]]:
    """Returns (selected, overflow)."""
    max_n = int(settings.get("max_articles", 20))
    ordered = sorted(articles, key=rank_key)
    if len(ordered) <= max_n:
        return ordered, []

    priority = [a for a in ordered if a.top_priority][:max_n]
    rest = [a for a in ordered if not a.top_priority]
    topic_order = settings.get("topic_priority") or []
    quota = settings.get("topic_quota") or {}
    groups = {t: [a for a in rest if a.topic == t] for t in topic_order}
    groups.setdefault("_other", [a for a in rest if a.topic not in topic_order])

    taken: dict[str, int] = {t: 0 for t in groups}
    slots = max_n - len(priority)

    def reserved_after(i: int) -> int:
        # Minimums still owed to quota topics later in the priority order
        return sum(min(quota[t].get("min", 0), len(groups[t])) for t in topic_order[i + 1:] if t in quota)

    for i, t in enumerate(topic_order):
        cap = quota[t].get("max", len(groups[t])) if t in quota else len(groups[t])
        n = max(0, min(cap, len(groups[t]), slots - reserved_after(i)))
        taken[t] = n
        slots -= n

    # Leftover slots: quota topics beyond their max, in priority order
    for t in [t for t in topic_order if t in quota] + ["_other"]:
        extra = min(slots, len(groups[t]) - taken[t])
        taken[t] += extra
        slots -= extra

    selected = list(priority)
    overflow = [a for a in ordered if a.top_priority][max_n:]
    for t, items in groups.items():
        selected += items[:taken[t]]
        overflow += items[taken[t]:]
    return sorted(selected, key=rank_key), sorted(overflow, key=rank_key)


def mark_editors_picks(selected: list[Article], n: int) -> None:
    candidates = sorted((a for a in selected if a.relevance >= 6), key=lambda a: -a.relevance)
    for a in candidates[:n]:
        a.editors_pick = True
