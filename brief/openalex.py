"""OpenAlex client: resolve names in config/ to OpenAlex IDs, and fetch new works."""

from __future__ import annotations

import logging
import os
import time
from collections import Counter, defaultdict
from datetime import date, timedelta

import requests

from .models import Article, Author, normalize_title

log = logging.getLogger(__name__)

API = "https://api.openalex.org"
CHUNK = 50  # OpenAlex allows up to 100 OR-values per filter; stay well under
WORK_FIELDS = ",".join([
    "id", "doi", "display_name", "publication_date", "type", "primary_location",
    "authorships", "abstract_inverted_index", "primary_topic", "best_oa_location",
])


class OpenAlex:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.params: dict[str, str] = {}
        if os.environ.get("OPENALEX_API_KEY"):
            self.params["api_key"] = os.environ["OPENALEX_API_KEY"]
        if os.environ.get("OPENALEX_MAILTO"):
            self.params["mailto"] = os.environ["OPENALEX_MAILTO"]
        self.calls = 0

    def get(self, path: str, **params) -> dict:
        params = {**self.params, **{k.replace("_", "-") if k == "per_page" else k: v for k, v in params.items()}}
        for attempt in range(5):
            self.calls += 1
            resp = self.session.get(f"{API}{path}", params=params, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After", "")
                wait = min(int(retry_after), 120) if retry_after.isdigit() else 2 ** attempt * 2
                log.warning("OpenAlex %s on %s, retrying in %ss", resp.status_code, path, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        if resp.status_code == 429 and "api_key" not in self.params:
            raise RuntimeError("OpenAlex rate limit reached. Add a free OpenAlex API key as the "
                               "OPENALEX_API_KEY repository secret (https://openalex.org/settings/api).")
        resp.raise_for_status()
        return {}

    def paged(self, path: str, max_results: int = 5000, **params) -> list[dict]:
        out: list[dict] = []
        cursor = "*"
        while cursor and len(out) < max_results:
            data = self.get(path, cursor=cursor, per_page=200, **params)
            out.extend(data.get("results", []))
            cursor = data.get("meta", {}).get("next_cursor")
        return out[:max_results]

    # ------------------------------------------------------------------ resolve

    def resolve_source(self, entry: dict) -> dict:
        """A journals.yaml entry -> {ids, matched, exact}."""
        if entry.get("issn"):
            res = self.get("/sources", filter=f"issn:{entry['issn']}").get("results", [])
            if res:
                return {"ids": [_short(res[0]["id"])], "matched": [res[0]["display_name"]], "exact": True}
        res = self.get("/sources", search=entry["name"], per_page=25).get("results", [])
        want = normalize_title(entry["name"])
        if entry.get("kind") == "conference":
            hits = [r for r in res if want in normalize_title(r["display_name"])]
            if hits:
                return {"ids": [_short(r["id"]) for r in hits],
                        "matched": [r["display_name"] for r in hits], "exact": True}
        exact = [r for r in res if normalize_title(r["display_name"]) == want]
        pick = exact[:1] or res[:1]
        return {"ids": [_short(r["id"]) for r in pick], "matched": [r["display_name"] for r in pick],
                "exact": bool(exact)}

    def resolve_author(self, entry: dict) -> dict:
        """A scholars.yaml entry -> {id, matched, institution, alternatives}."""
        if entry.get("openalex"):
            a = self.get(f"/authors/{entry['openalex']}")
            return _author_summary(a, [], pinned=True)
        candidates = self.get("/authors", search=entry["name"], per_page=10).get("results", [])
        if not candidates:
            # "Mike S. Schäfer" -> "Mike Schäfer"
            simple = " ".join(t for t in entry["name"].replace(".", " ").split() if len(t) > 1)
            if simple != entry["name"]:
                candidates = self.get("/authors", search=simple, per_page=10).get("results", [])
        if not candidates:
            return {"id": None, "matched": None, "institution": None, "alternatives": []}
        hint = (entry.get("hint") or "").lower()

        def score(a: dict) -> tuple:
            insts = [i.get("display_name", "") for i in a.get("last_known_institutions") or []]
            insts += [aff["institution"].get("display_name", "") for aff in a.get("affiliations") or []]
            hint_hit = bool(hint) and any(hint in (i or "").lower() for i in insts)
            return (hint_hit, a.get("works_count", 0))

        ranked = sorted(candidates, key=score, reverse=True)
        return _author_summary(ranked[0], ranked[1:4])

    def resolve_institution(self, name: str) -> dict:
        res = self.get("/institutions", search=name, per_page=5).get("results", [])
        if not res:
            return {"id": None, "matched": None}
        want = normalize_title(name)
        exact = [r for r in res if normalize_title(r["display_name"]) == want]
        pick = (exact or res)[0]
        return {"id": _short(pick["id"]), "matched": pick["display_name"], "exact": bool(exact)}

    def resolve_repository(self, name: str) -> dict:
        res = self.get("/sources", search=name, filter="type:repository", per_page=5).get("results", [])
        if not res:
            return {"ids": [], "matched": []}
        want = normalize_title(name)
        hits = [r for r in res if want in normalize_title(r["display_name"])] or res[:1]
        return {"ids": [_short(r["id"]) for r in hits], "matched": [r["display_name"] for r in hits]}

    def field_ids(self, names: list[str]) -> list[str]:
        fields = self.paged("/fields", max_results=200)
        lookup = {f["display_name"].lower(): _short(f["id"]) for f in fields}
        return [lookup[n.lower()] for n in names if n.lower() in lookup]

    def expand(self, author_id: str, mode: str, min_joint: int, years: int, cap: int = 60) -> list[dict]:
        """Coauthors (mode='coauthors') or same-institution lab members (mode='group')."""
        since = (date.today() - timedelta(days=365 * years)).isoformat()
        works = self.paged("/works", max_results=1000, select="id,authorships",
                           filter=f"authorships.author.id:{author_id},from_publication_date:{since}")
        counts: Counter[str] = Counter()
        names: dict[str, str] = {}
        for w in works:
            auths = w.get("authorships") or []
            anchor = next((a for a in auths if _short((a.get("author") or {}).get("id")) == author_id), None)
            anchor_insts = {_short(i["id"]) for i in (anchor or {}).get("institutions") or [] if i.get("id")}
            for a in auths:
                aid = _short((a.get("author") or {}).get("id"))
                if not aid or aid == author_id:
                    continue
                if mode == "group":
                    insts = {_short(i["id"]) for i in a.get("institutions") or [] if i.get("id")}
                    if not anchor_insts or not (insts & anchor_insts):
                        continue
                counts[aid] += 1
                names[aid] = a["author"].get("display_name") or aid
        return [{"id": aid, "name": names[aid], "joint_papers": n}
                for aid, n in counts.most_common() if n >= min_joint][:cap]

    # ------------------------------------------------------------------ fetch

    def works(self, filters: list[str], max_results: int = 5000) -> list[dict]:
        return self.paged("/works", max_results=max_results, select=WORK_FIELDS, filter=",".join(filters))

    def works_by(self, key: str, ids: list[str], since: str, until: str, extra: list[str] | None = None,
                 max_results: int = 5000) -> list[dict]:
        out: list[dict] = []
        for chunk in _chunks(sorted(set(ids)), CHUNK):
            filters = [f"{key}:{'|'.join(chunk)}", f"from_publication_date:{since}",
                       f"to_publication_date:{until}"] + (extra or [])
            out.extend(self.works(filters, max_results=max_results))
        return out


# ---------------------------------------------------------------------- helpers

def _short(openalex_id: str | None) -> str | None:
    return openalex_id.rsplit("/", 1)[-1] if openalex_id else None


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _author_summary(a: dict, alts: list[dict], pinned: bool = False) -> dict:
    def inst(x: dict) -> str | None:
        lk = x.get("last_known_institutions") or []
        return lk[0].get("display_name") if lk else None
    return {
        "id": _short(a.get("id")),
        "matched": a.get("display_name"),
        "institution": inst(a),
        "works_count": a.get("works_count"),
        "orcid": a.get("orcid"),
        "pinned": pinned,
        "alternatives": [f"{x.get('display_name')} ({inst(x) or 'no affiliation'}, {_short(x.get('id'))})"
                         for x in alts],
    }


def abstract_from_index(index: dict | None) -> str:
    if not index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def to_article(w: dict) -> Article:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    authors = []
    for a in w.get("authorships") or []:
        lineage: list[str] = []
        for i in a.get("institutions") or []:
            lineage += [_short(x) for x in (i.get("lineage") or [i.get("id")]) if x]
        authors.append(Author(name=(a.get("author") or {}).get("display_name") or a.get("raw_author_name") or "",
                              id=_short((a.get("author") or {}).get("id")), institution_ids=lineage))
    doi = w.get("doi")
    url = doi or loc.get("landing_page_url") or w.get("id")
    topic = w.get("primary_topic") or {}
    return Article(
        id=_short(w["id"]),
        title=(w.get("display_name") or "").strip(),
        venue=src.get("display_name") or "",
        venue_id=_short(src.get("id")),
        date=w.get("publication_date") or "",
        authors=authors,
        abstract=abstract_from_index(w.get("abstract_inverted_index")),
        url=url,
        doi=doi.replace("https://doi.org/", "") if doi else None,
        is_preprint=src.get("type") == "repository" or w.get("type") == "preprint",
        research_field=(topic.get("field") or {}).get("display_name"),
        pdf_url=(w.get("best_oa_location") or {}).get("pdf_url"),
    )


def fill_abstracts(articles: list[Article], session: requests.Session | None = None) -> None:
    """Best effort: fill missing abstracts from Semantic Scholar (Elsevier etc. hide them in OpenAlex)."""
    missing = [a for a in articles if not a.abstract and a.doi]
    if not missing:
        return
    session = session or requests.Session()
    by_doi = defaultdict(list)
    for a in missing:
        by_doi[a.doi.lower()].append(a)
    dois = list(by_doi)
    for chunk in _chunks(dois, 400):
        try:
            resp = session.post("https://api.semanticscholar.org/graph/v1/paper/batch",
                                params={"fields": "abstract,externalIds"},
                                json={"ids": [f"DOI:{d}" for d in chunk]}, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("Semantic Scholar abstract lookup failed: %s", e)
            return
        for doi, paper in zip(chunk, resp.json()):
            if paper and paper.get("abstract"):
                for a in by_doi[doi]:
                    a.abstract = paper["abstract"]
