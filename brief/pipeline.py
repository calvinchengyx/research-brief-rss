"""One run of the brief: fetch -> dedupe -> filter -> cap -> render -> (send)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import classify as cls
from .config import ARCHIVE_DIR, PREVIEW_DIR, Config, load_config
from .deepdive import (clear_resend, collect_votes, mark_processed, queue_resend, resend_queue, save_issue,
                       top_picks, write_deep_dives)
from .models import Article
from .openalex import OpenAlex, fill_abstracts, to_article
from .recipe import write_recipe
from .render import build_context, nice_date, render, render_dives
from .resolve import resolve_all
from .select import apply_cap, is_watch, mark_editors_picks
from .send import send
from .state import Seen

log = logging.getLogger(__name__)

SKIP_TYPES = {"erratum", "paratext", "retraction", "editorial", "letter", "peer-review", "other", "dataset",
              "supplementary-materials", "software", "grant", "standard"}


@dataclass
class Followed:
    """Lookup tables built from state/resolved.json."""
    sources: dict[str, dict] = field(default_factory=dict)       # source id -> journals.yaml entry
    authors: dict[str, tuple[str, str]] = field(default_factory=dict)  # author id -> (label, topic)
    anchor_ids: set[str] = field(default_factory=set)  # people named in scholars.yaml
    institutions: dict[str, tuple[str, str]] = field(default_factory=dict)  # MIT Media Lab etc.
    anchors: dict[str, set[str]] = field(default_factory=dict)  # scholars.yaml name -> author ids
    preprint_institutions: list[str] = field(default_factory=list)
    preprint_servers: list[str] = field(default_factory=list)
    preprint_fields: list[str] = field(default_factory=list)


def build_followed(cfg: Config, resolved: dict) -> Followed:
    f = Followed()
    for j in cfg.journals:
        for sid in resolved["journals"].get(j["name"], {}).get("ids", []):
            f.sources[sid] = j
    for sc in cfg.scholars:
        r = resolved["scholars"].get(sc["name"], {})
        if not r.get("id"):
            continue
        if r.get("type") == "institution":
            f.institutions[r["id"]] = (sc["name"], sc["topic"])
            continue
        f.authors[r["id"]] = (sc["name"], sc["topic"])
        f.anchor_ids.add(r["id"])
        f.anchors[sc["name"]] = {r["id"]}
        relation = "coauthor of" if r["type"] == "coauthors" else "lab of"
        surname = sc["name"].split()[-1]
        for m in r.get("members", []):
            if m["id"] not in f.authors:
                f.authors[m["id"]] = (f"{m['name']} ({relation} {surname})", sc["topic"])
            f.anchors[sc["name"]].add(m["id"])
    f.preprint_institutions = [r["id"] for r in resolved.get("institutions", {}).values() if r.get("id")]
    f.preprint_servers = sum((r["ids"] for r in resolved.get("servers", {}).values()), [])
    f.preprint_fields = resolved.get("preprint_fields", [])
    return f


def collect(cfg: Config, oa: OpenAlex, f: Followed, since: str, until: str,
            counts: dict | None = None) -> dict[str, Article]:
    """Fetch the window's works. `counts` gets the new works each source added and the skips."""
    raw: dict[str, dict] = {}
    counts = counts if counts is not None else {}

    def add(works: list[dict]):
        for w in works:
            raw.setdefault(w["id"], w)

    add(oa.works_by("primary_location.source.id", list(f.sources), since, until))
    counts["journals"] = len(raw)
    log.info("Journals: %d works", len(raw))
    add(oa.works_by("authorships.author.id", list(f.authors), since, until))
    counts["scholars"] = len(raw) - counts["journals"]
    log.info("+ scholars: %d works", len(raw))
    n = len(raw)
    if f.institutions:
        add(oa.works_by("authorships.institutions.lineage", list(f.institutions), since, until))
        log.info("+ followed institutions: %d works", len(raw))
    counts["institutions"] = len(raw) - n
    n = len(raw)
    pp = cfg.settings.get("preprints") or {}
    if pp.get("enabled", True) and f.preprint_servers and f.preprint_institutions:
        extra = [f"primary_location.source.id:{'|'.join(f.preprint_servers)}"]
        if f.preprint_fields:
            extra.append(f"primary_topic.field.id:{'|'.join(f.preprint_fields)}")
        add(oa.works_by("authorships.institutions.lineage", f.preprint_institutions, since, until,
                        extra=extra, max_results=4000))
        log.info("+ preprints: %d works", len(raw))
    counts["preprints"] = len(raw) - n

    articles: dict[str, Article] = {}
    counts["raw"], counts["skipped_type"], counts["unmatched"] = len(raw), 0, 0
    for w in raw.values():
        if w.get("type") in SKIP_TYPES or not w.get("display_name"):
            counts["skipped_type"] += 1
            continue
        a = to_article(w)
        tag(a, f)
        if a.journal_hit or a.scholar_hit or a.is_preprint or a.topic:
            articles[a.id] = a
        else:
            counts["unmatched"] += 1
    return articles


def tag(a: Article, f: Followed) -> None:
    """Set journal_hit / scholar_hit / topic / needs_filter from the follow lists."""
    names: list[str] = []
    for au in a.authors:
        if au.id in f.authors:
            au.followed = True
            names.append(f.authors[au.id][0])
    # Followed institutions (e.g. MIT Media Lab) count as a source, not as a scholar
    inst_hits = list(dict.fromkeys(f.institutions[i] for au in a.authors
                                   for i in au.institution_ids if i in f.institutions))
    a.scholar_hit = bool(names)
    a.anchor_hit = any(au.id in f.anchor_ids for au in a.authors)
    a.scholar_names = list(dict.fromkeys(names))
    journal = f.sources.get(a.venue_id or "")
    if journal and journal.get("short"):
        a.venue = journal["short"]
    a.journal_hit = journal is not None and not a.is_preprint
    if a.journal_hit:
        a.topic = journal["topic"]
        a.needs_filter = journal.get("filter") == "social-science" and not a.anchor_hit
    elif a.scholar_hit:
        a.topic = f.authors[next(au.id for au in a.authors if au.followed)][1]
        # Coauthors and lab members publish on everything; keep only social-science work
        a.needs_filter = not a.anchor_hit
    else:
        # preprint from a top institution, or work from a followed institution
        a.needs_filter = True
        if inst_hits:
            a.topic = inst_hits[0][1]


def due(today: date | None = None) -> bool:
    """Whether a scheduled send is due: the cron fires weekly, issues go out every send_every_days."""
    today = today or date.today()
    every = int(load_config().settings.get("send_every_days", 7))
    sent = sorted(p.stem for p in ARCHIVE_DIR.glob("*.html")) if ARCHIVE_DIR.exists() else []
    if not sent:
        return True
    days = (today - date.fromisoformat(sent[-1])).days
    if days < every - 1:  # a day of slack for a late cron
        log.info("Last issue went out %d days ago; next one is due after %d days. Skipping.", days, every)
        return False
    return True


def run(mode: str = "preview", since: str | None = None, until: str | None = None,
        oa: OpenAlex | None = None) -> dict:
    cfg = load_config()
    s = cfg.settings
    today = date.today()
    until = until or today.isoformat()
    since = since or (today - timedelta(days=int(s.get("lookback_days", 10)))).isoformat()
    oa = oa or OpenAlex()

    resolved = resolve_all(cfg, oa)
    f = build_followed(cfg, resolved)
    counts: dict = {}
    found = collect(cfg, oa, f, since, until, counts)

    seen = Seen()
    fresh = [a for a in found.values() if seen.is_new(a)]
    passed = cls.prefilter(fresh, s.get("social_keywords") or [])
    passed_ids = {a.id for a in passed}
    screened = [a for a in fresh if a.id not in passed_ids]

    fill_abstracts(passed)
    methods = cls.classify(passed, cfg, use_ai=(s.get("ai") or {}).get("enabled", True))
    kept = [a for a in passed if a.keep]
    screened += [a for a in passed if not a.keep]

    # Papers readers asked for since the last issue go back in at the top
    dives = resend_queue()
    dive_keys = {a.key for a in dives}
    kept_new = [a for a in kept if a.key not in dive_keys]

    selected, overflow = apply_cap(kept_new, s)
    mark_editors_picks(selected, int((s.get("ai") or {}).get("editors_picks", 4)))

    kept_authors = {au.id for a in kept for au in a.authors if au.followed}
    quiet = [name for name, ids in f.anchors.items() if not ids & kept_authors]

    stats = {
        "window": f"{nice_date(since)} to {nice_date(until)}",
        "shown": len(selected), "priority": sum(a.top_priority for a in selected), "cut": len(overflow),
        "found": len(found), "new": len(fresh), "after_prefilter": len(passed), "kept": len(kept),
        "openalex_calls": oa.calls, "requested": len(dives),
    }
    context = build_context(cfg, selected, overflow, quiet, stats, today, test=(mode == "test"), dives=dives)
    html, text = render(context)

    report = run_report(cfg, mode, since, until, stats, counts, methods, fresh, passed, kept, selected, overflow)
    PREVIEW_DIR.mkdir(exist_ok=True)
    (PREVIEW_DIR / "latest.html").write_text(html, encoding="utf-8")
    (PREVIEW_DIR / "latest.txt").write_text(text, encoding="utf-8")
    (PREVIEW_DIR / "run.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    write_recipe(cfg, resolved, report)
    log.info("Stats: %s", stats)

    subject = (s.get("email") or {}).get("subject", "Research Brief: {date}").format(date=nice_date(until))
    if mode == "test":
        # Tests go to test_recipients only, so nothing is recorded as sent
        send(cfg.test_recipients or cfg.recipients, f"[TEST] {subject}", html, text, s)
        save_issue(until, subject, dives + selected + overflow)  # lets a test reply be checked
    elif mode == "send":
        send(cfg.recipients, subject, html, text, s)
        seen.record(selected + overflow, screened)
        seen.save()
        save_issue(until, subject, dives + selected + overflow)
        clear_resend()
        ARCHIVE_DIR.mkdir(exist_ok=True)
        (ARCHIVE_DIR / f"{until}.html").write_text(html, encoding="utf-8")
    return stats


def run_dives(mode: str = "preview") -> dict:
    """The deep-dive email: the top-voted papers from replies since the last one. Skipped without replies."""
    cfg = load_config()
    dd = cfg.settings.get("deep_dive") or {}
    today = date.today()
    requested, reply_files = collect_votes(int(dd.get("max_per_reply", 3)))
    if not requested:
        log.info("No new requests: no deep-dive email")
        return {"requested": 0, "dives": 0}
    picks = top_picks(requested, int(dd.get("max_papers", 5)), seed=today.isoformat())
    write_deep_dives(picks, cfg)
    picks = [a for a in picks if a.deep_dive]
    stats = {"requested": len(requested), "dives": len(picks), "votes": sum(a.requested for a in requested)}
    if not picks:
        log.warning("Deep dives could not be written; the replies stay in inbox/ for the next run")
        return stats
    html, text = render_dives(cfg, picks, stats["votes"], len(requested), today, test=(mode == "test"))
    PREVIEW_DIR.mkdir(exist_ok=True)
    (PREVIEW_DIR / "dives.html").write_text(html, encoding="utf-8")
    (PREVIEW_DIR / "dives.txt").write_text(text, encoding="utf-8")
    subject = (cfg.settings.get("email") or {}).get("dives_subject", "Research Brief deep dives: {date}") \
        .format(date=nice_date(today.isoformat()))
    if mode == "test":
        send(cfg.test_recipients or cfg.recipients, f"[TEST] {subject}", html, text, cfg.settings)
    elif mode == "send":
        send(cfg.recipients, subject, html, text, cfg.settings)
        queue_resend(requested, picks)
        mark_processed(reply_files)
        (ARCHIVE_DIR / "dives").mkdir(parents=True, exist_ok=True)
        (ARCHIVE_DIR / "dives" / f"{today.isoformat()}.html").write_text(html, encoding="utf-8")
    log.info("Deep dives: %s", stats)
    return stats


def section_of(a: Article) -> str:
    if a.top_priority:
        return "Top priority"
    if is_watch(a):
        return "Scholar watch"
    return "Topic"


def reason(a: Article, cfg: Config) -> str:
    """Plain-language reason a paper is in the brief (shown in recipe.html)."""
    who = ", ".join(a.scholar_names)
    topic = cfg.topic_names.get(a.topic, a.topic or "")
    if a.top_priority:
        why = f"Followed scholar ({who}) in a followed venue."
    elif is_watch(a):
        why = f"Work by a followed scholar ({who}) outside the venue list."
    elif a.is_preprint:
        why = f"Preprint from a listed institution, filed under {topic}."
    else:
        why = f"Published in a followed venue, filed under {topic}."
    if a.needs_filter:
        why += " Passed the social-science filter."
    return why


def run_report(cfg, mode, since, until, stats, counts, methods, fresh, passed, kept, selected, overflow) -> dict:
    def tally(items, key):
        out: dict[str, int] = {}
        for a in items:
            out[key(a)] = out.get(key(a), 0) + 1
        return out

    def row(a: Article) -> dict:
        return {"title": a.title, "url": a.url, "venue": a.venue or "Preprint", "date": a.date,
                "topic": cfg.topic_names.get(a.topic, a.topic), "preprint": a.is_preprint,
                "section": section_of(a), "scholars": a.scholar_names, "relevance": a.relevance,
                "pick": a.editors_pick, "summary": a.summary, "reason": reason(a, cfg)}

    topic = lambda a: cfg.topic_names.get(a.topic, a.topic or "None")  # noqa: E731
    return {
        "mode": mode, "since": since, "until": until, "generated": date.today().isoformat(), **stats,
        "sources": counts, "classified_by": methods,
        "needs_filter": sum(a.needs_filter for a in fresh),
        "preprints_found": sum(a.is_preprint for a in fresh),
        "kept_by_topic": tally(kept, topic), "kept_by_section": tally(kept, section_of),
        "shown_by_topic": tally(selected, topic), "shown_by_section": tally(selected, section_of),
        "selected": [row(a) for a in selected],
        "cut_top": [row(a) for a in overflow[:10]],
    }
