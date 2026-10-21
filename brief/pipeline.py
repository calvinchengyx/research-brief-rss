"""One run of the brief: fetch -> dedupe -> filter -> cap -> render -> (send)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import classify as cls
from .config import ARCHIVE_DIR, PREVIEW_DIR, Config, load_config
from .models import Article
from .openalex import OpenAlex, fill_abstracts, to_article
from .render import build_context, nice_date, render
from .resolve import resolve_all
from .select import apply_cap, mark_editors_picks
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


def collect(cfg: Config, oa: OpenAlex, f: Followed, since: str, until: str) -> dict[str, Article]:
    raw: dict[str, dict] = {}

    def add(works: list[dict]):
        for w in works:
            raw.setdefault(w["id"], w)

    add(oa.works_by("primary_location.source.id", list(f.sources), since, until))
    log.info("Journals: %d works", len(raw))
    add(oa.works_by("authorships.author.id", list(f.authors), since, until))
    log.info("+ scholars: %d works", len(raw))
    if f.institutions:
        add(oa.works_by("authorships.institutions.lineage", list(f.institutions), since, until))
        log.info("+ followed institutions: %d works", len(raw))
    pp = cfg.settings.get("preprints") or {}
    if pp.get("enabled", True) and f.preprint_servers and f.preprint_institutions:
        extra = [f"primary_location.source.id:{'|'.join(f.preprint_servers)}"]
        if f.preprint_fields:
            extra.append(f"primary_topic.field.id:{'|'.join(f.preprint_fields)}")
        add(oa.works_by("authorships.institutions.lineage", f.preprint_institutions, since, until,
                        extra=extra, max_results=4000))
        log.info("+ preprints: %d works", len(raw))

    articles: dict[str, Article] = {}
    for w in raw.values():
        if w.get("type") in SKIP_TYPES or not w.get("display_name"):
            continue
        a = to_article(w)
        tag(a, f)
        if a.journal_hit or a.scholar_hit or a.is_preprint or a.topic:
            articles[a.id] = a
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
    found = collect(cfg, oa, f, since, until)

    seen = Seen()
    fresh = [a for a in found.values() if seen.is_new(a)]
    passed = cls.prefilter(fresh, s.get("social_keywords") or [])
    passed_ids = {a.id for a in passed}
    screened = [a for a in fresh if a.id not in passed_ids]

    fill_abstracts(passed)
    cls.classify(passed, cfg, use_ai=(s.get("ai") or {}).get("enabled", True))
    kept = [a for a in passed if a.keep]
    screened += [a for a in passed if not a.keep]

    selected, overflow = apply_cap(kept, s)
    mark_editors_picks(selected, int((s.get("ai") or {}).get("editors_picks", 4)))

    kept_authors = {au.id for a in kept for au in a.authors if au.followed}
    quiet = [name for name, ids in f.anchors.items() if not ids & kept_authors]

    stats = {
        "window": f"{nice_date(since)} to {nice_date(until)}",
        "shown": len(selected), "priority": sum(a.top_priority for a in selected), "cut": len(overflow),
        "found": len(found), "new": len(fresh), "after_prefilter": len(passed), "kept": len(kept),
        "openalex_calls": oa.calls,
    }
    context = build_context(cfg, selected, overflow, quiet, stats, today, test=(mode == "test"))
    html, text = render(context)

    PREVIEW_DIR.mkdir(exist_ok=True)
    (PREVIEW_DIR / "latest.html").write_text(html, encoding="utf-8")
    (PREVIEW_DIR / "latest.txt").write_text(text, encoding="utf-8")
    (PREVIEW_DIR / "run.json").write_text(json.dumps({"mode": mode, "since": since, "until": until, **stats},
                                                     indent=1), encoding="utf-8")
    log.info("Stats: %s", stats)

    subject = (s.get("email") or {}).get("subject", "Research Brief: {date}").format(date=nice_date(until))
    if mode == "test":
        send(cfg.recipients[:1], f"[TEST] {subject}", html, text, s)
    elif mode == "send":
        send(cfg.recipients, subject, html, text, s)
        seen.record(selected + overflow, screened)
        seen.save()
        ARCHIVE_DIR.mkdir(exist_ok=True)
        (ARCHIVE_DIR / f"{until}.html").write_text(html, encoding="utf-8")
    return stats
