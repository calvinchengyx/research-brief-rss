"""recipe.html: what the brief follows, how it chooses, and what the latest run did."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .classify import system_prompt
from .config import ROOT, TEMPLATE_DIR, Config
from .render import nice_date

# OpenAlex field ids, for showing which preprint fields were matched
FIELD_NAMES = {"12": "Arts and Humanities", "14": "Business, Management and Accounting", "17": "Computer Science",
               "18": "Decision Sciences", "20": "Economics, Econometrics and Finance", "32": "Psychology",
               "33": "Social Sciences"}

SCHOLAR_TYPES = {"person": "Person", "coauthors": "Person and coauthors", "group": "Person and lab",
                 "institution": "Institution"}


def build_context(cfg: Config, resolved: dict, report: dict) -> dict:
    journals = []
    for t in cfg.topics:
        rows = []
        for j in cfg.journals:
            if j["topic"] != t["id"]:
                continue
            r = resolved.get("journals", {}).get(j["name"], {})
            rows.append({"name": j["name"], "issn": j.get("issn", ""), "kind": j.get("kind", "journal"),
                         "filter": j.get("filter") == "social-science", "matched": r.get("matched", []),
                         "ids": r.get("ids", []), "exact": r.get("exact", False)})
        journals.append({"id": t["id"], "topic": t["name"], "rows": rows})

    scholars = []
    for sc in cfg.scholars:
        r = resolved.get("scholars", {}).get(sc["name"], {})
        scholars.append({"name": sc["name"], "topic": cfg.topic_names.get(sc["topic"], ""),
                         "type": SCHOLAR_TYPES.get(r.get("type") or sc.get("type", "person"), "Person"),
                         "id": r.get("id"), "matched": r.get("matched"), "institution": r.get("institution"),
                         "members": len(r.get("members", [])), "alternatives": len(r.get("alternatives", []))})

    inst = cfg.institutions
    resolved_inst = resolved.get("institutions", {})

    def inst_rows(names):
        return [{"name": n, "matched": (resolved_inst.get(n) or {}).get("matched"),
                 "exact": (resolved_inst.get(n) or {}).get("exact", False)} for n in names or []]

    pp = cfg.settings.get("preprints") or {}
    ai = cfg.settings.get("ai") or {}
    s = cfg.settings
    stages = [
        ("Works fetched from OpenAlex", report["sources"].get("raw", report["found"])),
        ("Research items matched to a list", report["found"]),
        ("Not sent in an earlier issue", report["new"]),
        ("Passed the quick keyword and field check", report["after_prefilter"]),
        ("Kept by the AI filter", report["kept"]),
        ("Shown in the email", report["shown"]),
    ]
    top = max(n for _, n in stages) or 1
    return {
        "cfg": cfg, "s": s, "r": report, "ai": ai, "pp": pp, "report": report, "journals": journals, "scholars": scholars,
        "n_journals": len(cfg.journals), "n_scholars": len(cfg.scholars),
        "n_members": sum(x["members"] for x in scholars),
        "universities": inst_rows(inst.get("universities")), "institutes": inst_rows(inst.get("institutes")),
        "companies": inst_rows(inst.get("companies")),
        "servers": [{"name": k, "matched": v.get("matched", [])} for k, v in resolved.get("servers", {}).items()],
        "fields": [FIELD_NAMES.get(f, f) for f in resolved.get("preprint_fields", [])],
        "prompt": system_prompt(cfg), "stages": [{"label": l, "n": n, "pct": 100 * n / top} for l, n in stages],
        "window": f"{nice_date(report['since'])} to {nice_date(report['until'])}",
        "generated": nice_date(report.get("generated", report["until"])),
        "n_recipients": len(cfg.recipients),
    }


def render_recipe(cfg: Config, resolved: dict, report: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["num"] = lambda n: f"{int(n):,}"
    return env.get_template("recipe.html.j2").render(**build_context(cfg, resolved, report))


RECIPE = ROOT / "recipe.html"


def write_recipe(cfg: Config, resolved: dict, report: dict) -> None:
    RECIPE.write_text(render_recipe(cfg, resolved, report), encoding="utf-8")
