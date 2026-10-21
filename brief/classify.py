"""Social-science filter, topic assignment and relevance scoring.

With ANTHROPIC_API_KEY set, Claude reads title + abstract in batches. Without it,
a keyword filter decides and relevance is a simple keyword overlap score.
Claude's answers are cached in state/classified.json, so a paper is only ever
screened once per model, however many previews or reruns there are.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta

from .config import STATE_DIR
from .models import Article

log = logging.getLogger(__name__)

# Fields that pass straight to Claude; everything else from a filtered venue must
# first match a social keyword (keeps physics/biology papers out cheaply).
SOCIAL_FIELDS = {"Social Sciences", "Psychology", "Arts and Humanities", "Economics, Econometrics and Finance",
                 "Decision Sciences", "Business, Management and Accounting"}

SCHEMA = {
    "type": "object",
    "properties": {
        "papers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "topic": {"type": "string"},
                    "relevance": {"type": "integer"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "keep", "topic", "relevance", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["papers"],
    "additionalProperties": False,
}


def keyword_match(a: Article, keywords: list[str]) -> bool:
    text = f"{a.title} {a.abstract}".lower()
    return any(k.lower() in text for k in keywords)


def prefilter(articles: list[Article], keywords: list[str]) -> list[Article]:
    """Cheap first pass for filtered venues, preprints and coauthors' work."""
    out = []
    for a in articles:
        if not a.needs_filter or a.research_field in SOCIAL_FIELDS or keyword_match(a, keywords):
            out.append(a)
    return out


CACHE_DAYS = 60


def _cache_path():
    return STATE_DIR / "classified.json"


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    cutoff = (date.today() - timedelta(days=CACHE_DAYS)).isoformat()
    cache = {k: v for k, v in cache.items() if v.get("on", "") >= cutoff}
    STATE_DIR.mkdir(exist_ok=True)
    _cache_path().write_text(json.dumps(cache, indent=0, ensure_ascii=False), encoding="utf-8")


def _cache_key(a: Article, model: str) -> str:
    return f"{model}|{'F' if a.needs_filter else '-'}|{a.key}"


def classify(articles: list[Article], cfg, use_ai: bool) -> dict:
    """Returns how many papers each method decided, for the run report."""
    s = cfg.settings
    model = (s.get("ai") or {}).get("model", "claude-haiku-5-5")
    has_credentials = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_FEDERATION_RULE_ID")
    if not (use_ai and has_credentials):
        _classify_keywords(articles, cfg, s.get("social_keywords") or [])
        return {"model": None, "ai": 0, "cached": 0, "keywords": len(articles)}

    cache = _load_cache()
    todo = []
    for a in articles:
        hit = cache.get(_cache_key(a, model))
        if hit:
            a.keep, a.topic, a.relevance, a.summary = hit["keep"], a.topic or hit["topic"], hit["relevance"], hit["summary"]
        else:
            todo.append(a)
    log.info("Classifying %d papers (%d cached)", len(todo), len(articles) - len(todo))

    done: list[Article] = []
    try:
        _classify_ai(todo, cfg, done)
    except Exception as e:  # never lose the week's brief to an API problem
        log.error("AI classification stopped after %d papers, using keywords for the rest: %s", len(done), e)
        finished = {a.id for a in done}
        _classify_keywords([a for a in todo if a.id not in finished], cfg, s.get("social_keywords") or [])
    finally:
        today = date.today().isoformat()
        for a in done:
            cache[_cache_key(a, model)] = {"keep": a.keep, "topic": a.topic, "relevance": a.relevance,
                                           "summary": a.summary, "on": today}
        _save_cache(cache)
    return {"model": model, "ai": len(done), "cached": len(articles) - len(todo),
            "keywords": len(todo) - len(done)}


def _classify_keywords(articles: list[Article], cfg, keywords: list[str]) -> None:
    interests = " ".join(cfg.settings.get("research_interests") or []).lower().split()
    interest_words = {w for w in interests if len(w) > 4}
    for a in articles:
        if a.needs_filter:
            a.keep = keyword_match(a, keywords)
        text = f"{a.title} {a.abstract}".lower()
        a.relevance = min(10.0, float(sum(w in text for w in interest_words)))
        if not a.topic:
            a.topic = "cl" if a.research_field == "Computer Science" else "css"


def system_prompt(cfg) -> str:
    """The instructions Claude gets with every batch (also shown in recipe.html)."""
    s = cfg.settings
    topics = "\n".join(f"- {t['id']}: {t['name']}. {t.get('description', '')}" for t in cfg.topics)
    preprint_topics = (s.get("preprints") or {}).get("topics") or ["css", "cl"]
    interests = "\n".join(f"- {i}" for i in s.get("research_interests") or [])
    return (
        "You screen new research papers for a weekly newsletter read by a computational social "
        "scientist.\n\nTheir research interests:\n" + interests + "\n\nNewsletter topics:\n" + topics +
        "\n\nFor each paper return:\n"
        "- keep: false if it is not a research article or review (news, editorial, comment, "
        "correction, dataset, data or code deposit, supplementary material). For papers marked FILTER, "
        "also false unless it is about society, human behaviour, social media, communication, "
        "politics, psychology, science and the public, or the social uses and impacts of AI and "
        "language technology; false for pure natural science, medicine, mathematics, or purely "
        "technical ML/NLP work with no social-science angle. Otherwise true.\n"
        f"- topic: one of {', '.join(t['id'] for t in cfg.topics)}. For preprints choose only from "
        f"{', '.join(preprint_topics)}.\n"
        "- relevance: 0-10, how close the paper is to the reader's research interests.\n"
        "- summary: one plain sentence (max 25 words) on what the paper finds."
    )


def _classify_ai(articles: list[Article], cfg, done: list[Article]) -> None:
    """Classify in batches; append each finished paper to `done` as it completes."""
    import anthropic

    s = cfg.settings
    ai = s.get("ai") or {}
    client = anthropic.Anthropic()
    preprint_topics = (s.get("preprints") or {}).get("topics") or ["css", "cl"]
    system = system_prompt(cfg)
    by_id = {a.id: a for a in articles}
    batch_size = int(ai.get("batch_size", 20))
    for start in range(0, len(articles), batch_size):
        batch = articles[start:start + batch_size]
        papers = "\n\n".join(
            f"<paper id=\"{a.id}\"{' FILTER' if a.needs_filter else ''}"
            f"{' PREPRINT' if a.is_preprint else ''}>\nTitle: {a.title}\nVenue: {a.venue}\n"
            f"Abstract: {a.abstract[:2500] or '(none)'}\n</paper>"
            for a in batch)
        request = dict(
            model=ai.get("model", "claude-haiku-5-5"),
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": papers}],
            output_config={"effort": ai.get("effort", "low"),
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if "haiku" in request["model"]:  # Haiku has no server-side fallback
            response = client.messages.create(**request)
        else:
            try:
                # Server-side fallback reruns a declined request on another model
                response = client.beta.messages.create(**request, betas=["server-side-fallback-2026-07-01"],
                                                       fallbacks="default")
            except anthropic.BadRequestError as e:
                log.warning("Request with fallbacks rejected (%s); retrying without", e)
                response = client.messages.create(**request)
        if response.stop_reason == "refusal":
            log.warning("Batch at %d declined; using keyword filter for it", start)
            _classify_keywords(batch, cfg, s.get("social_keywords") or [])
            continue
        text = next(b.text for b in response.content if b.type == "text")
        for r in json.loads(text)["papers"]:
            a = by_id.get(r["id"])
            if not a:
                continue
            a.keep = bool(r["keep"])
            a.relevance = float(max(0, min(10, r["relevance"])))
            a.summary = r["summary"].strip()
            if not a.topic:
                t = r["topic"]
                allowed = preprint_topics if a.is_preprint else list(cfg.topic_names)
                a.topic = t if t in allowed else allowed[0]
            done.append(a)
    for a in articles:  # anything the model skipped
        if not a.topic:
            a.topic = "cl" if a.research_field == "Computer Science" else "css"
