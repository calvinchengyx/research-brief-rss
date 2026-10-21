"""Turn names in config/ into OpenAlex IDs, cached in state/resolved.json.

The cache refreshes when the relevant config file changes, and scholar groups
(coauthors / lab members) are recomputed every `expand_every_days`.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .config import STATE_DIR, Config
from .openalex import OpenAlex

log = logging.getLogger(__name__)

CACHE = STATE_DIR / "resolved.json"
PREPRINT_FIELDS = ["Social Sciences", "Psychology", "Computer Science", "Economics, Econometrics and Finance",
                   "Arts and Humanities", "Decision Sciences"]


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def resolve_all(cfg: Config, oa: OpenAlex) -> dict:
    cache = load_cache()
    s = cfg.settings

    fp = cfg.fingerprint("journals")
    if cache.get("journals_fp") != fp:
        log.info("Resolving %d journals", len(cfg.journals))
        cache["journals"] = {j["name"]: oa.resolve_source(j) for j in cfg.journals}
        cache["journals_fp"] = fp

    fp = cfg.fingerprint("institutions") + str(s.get("preprints"))
    if cache.get("institutions_fp") != fp:
        names = sum((cfg.institutions.get(k) or [] for k in ("universities", "institutes", "companies")), [])
        log.info("Resolving %d institutions", len(names))
        cache["institutions"] = {n: oa.resolve_institution(n) for n in names}
        servers = (s.get("preprints") or {}).get("servers") or []
        cache["servers"] = {n: oa.resolve_repository(n) for n in servers}
        cache["preprint_fields"] = oa.field_ids(PREPRINT_FIELDS)
        cache["institutions_fp"] = fp

    fp = cfg.fingerprint("scholars")
    expired = cache.get("expanded_on", "") < (date.today() - timedelta(days=s.get("expand_every_days", 30))).isoformat()
    if cache.get("scholars_fp") != fp or expired:
        log.info("Resolving %d scholars", len(cfg.scholars))
        scholars = {}
        for sc in cfg.scholars:
            if sc.get("type") == "institution":
                scholars[sc["name"]] = {**oa.resolve_institution(sc["name"]), "type": "institution"}
                continue
            info = oa.resolve_author(sc)
            info["type"] = sc.get("type", "person")
            info["members"] = []
            if info["id"] and info["type"] in ("coauthors", "group"):
                info["members"] = oa.expand(info["id"], info["type"],
                                            min_joint=sc.get("min_joint_papers", 2),
                                            years=s.get("coauthor_years", 5),
                                            cap=sc.get("max_members", 100 if sc.get("min_joint_papers") == 1 else 60))
            scholars[sc["name"]] = info
        cache["scholars"] = scholars
        cache["scholars_fp"] = fp
        cache["expanded_on"] = date.today().isoformat()

    STATE_DIR.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    (STATE_DIR / "following.md").write_text(following_report(cfg, cache), encoding="utf-8")
    return cache


def following_report(cfg: Config, cache: dict) -> str:
    """Human-readable list of what every config entry matched, for review."""
    lines = ["# What the brief is following", "",
             f"Generated {date.today().isoformat()} from config/. Fix a wrong match by adding `issn:` "
             "(journals) or `openalex:` (scholars) to the entry.", "", "## Journals and conferences", ""]
    for j in cfg.journals:
        r = cache.get("journals", {}).get(j["name"], {})
        if not r.get("ids"):
            lines.append(f"- **{j['name']}**: NOT FOUND")
        else:
            flag = "" if r.get("exact") else " (closest match, please check)"
            lines.append(f"- **{j['name']}** → {'; '.join(r['matched'][:6])}"
                         f"{' …' if len(r['matched']) > 6 else ''}{flag}")
    lines += ["", "## Scholars", ""]
    for sc in cfg.scholars:
        r = cache.get("scholars", {}).get(sc["name"], {})
        if not r.get("id"):
            lines.append(f"- **{sc['name']}**: NOT FOUND")
            continue
        if r.get("type") == "institution":
            lines.append(f"- **{sc['name']}** (institution) → {r['matched']} ({r['id']})")
            continue
        lines.append(f"- **{sc['name']}** → {r['matched']}, {r.get('institution') or 'no affiliation'} "
                     f"({r['id']}, {r.get('works_count')} works)")
        if r.get("alternatives"):
            lines.append(f"  - other people with this name: {'; '.join(r['alternatives'])}")
        if r.get("members"):
            label = "coauthors" if r["type"] == "coauthors" else "lab members"
            lines.append(f"  - {len(r['members'])} {label} followed: "
                         + ", ".join(f"{m['name']} ({m['joint_papers']})" for m in r["members"]))
    lines += ["", "## Preprint servers", ""]
    for n, r in (cache.get("servers") or {}).items():
        lines.append(f"- **{n}** → {'; '.join(r['matched']) or 'NOT FOUND'}")
    lines += ["", "## Institutions (preprint filter)", ""]
    for n, r in (cache.get("institutions") or {}).items():
        flag = "" if r.get("exact") else " (closest match, please check)"
        lines.append(f"- {n} → {r.get('matched') or 'NOT FOUND'}{flag if r.get('matched') else ''}")
    return "\n".join(lines) + "\n"
