"""Deep dives on papers readers asked for by replying with their IDs.

Replies land in inbox/ (one JSON file per email, written by the Gmail script in
docs/gmail-replies.gs). Every morning the new replies are counted as votes: each
ID in a reply is one vote, at most three per reply and one per reader and paper.
The top papers (five at most) get a deep dive each (open-access full text when
there is one, otherwise the abstract), sent the same morning as a short email.
Every requested paper is also re-sent in the next regular issue.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import asdict
from datetime import date

from .classify import call_claude
from .config import ROOT, STATE_DIR
from .models import Article, article_from_dict

log = logging.getLogger(__name__)

INBOX = ROOT / "inbox"
ISSUES = STATE_DIR / "issues"
REQUESTS = STATE_DIR / "requests.json"
DIVES = STATE_DIR / "deep_dives.json"

REF = re.compile(r"\b([A-Za-z])(\d{1,2})\b")

SCHEMA = {
    "type": "object",
    "properties": {
        "research_questions": {"type": "array", "items": {"type": "string"}},
        "methods": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["research_questions", "methods", "findings"],
    "additionalProperties": False,
}

PROMPT = (
    "You write deep-dive summaries of research papers for a computational social scientist. "
    "From the paper below, give: the research questions (1-3, each one sentence); the main methods "
    "(2-4 sentences: data, sample, design and analysis); and the main findings (3-5, each one sentence, "
    "with key numbers where the paper reports them). Use only what the paper says. If you only have the "
    "abstract, keep to what the abstract supports and do not guess details it leaves out."
)


# ------------------------------------------------------------------ issues

def save_issue(until: str, subject: str, articles: list[Article]) -> None:
    """Remember which paper each ID pointed to, so replies can be matched later."""
    ISSUES.mkdir(parents=True, exist_ok=True)
    data = {"date": until, "subject": subject, "articles": {a.ref: asdict(a) for a in articles if a.ref}}
    (ISSUES / f"{until}.json").write_text(json.dumps(data, indent=0, ensure_ascii=False), encoding="utf-8")


def _issues() -> list[dict]:
    if not ISSUES.exists():
        return []
    return sorted((json.loads(p.read_text(encoding="utf-8")) for p in ISSUES.glob("*.json")),
                  key=lambda d: d["date"])


def _issue_for(reply: dict, issues: list[dict]) -> dict | None:
    """The issue a reply answers: by the date in its subject, else the latest one sent before it."""
    subject = reply.get("subject", "")
    for issue in issues:
        if issue.get("subject") and issue["subject"] in subject:
            return issue
    sent = (reply.get("date") or date.today().isoformat())[:10]
    earlier = [i for i in issues if i["date"] <= sent]
    return earlier[-1] if earlier else None


def reply_refs(body: str, limit: int | None = None) -> list[str]:
    """IDs written in a reply, ignoring the quoted original below it; the first `limit` count."""
    lines = []
    for line in body.splitlines():
        if line.lstrip().startswith(">") or re.match(r"\s*On .+ wrote:\s*$", line) or \
                line.strip().startswith("-----Original Message"):
            break
        lines.append(line)
    refs = list(dict.fromkeys(f"{l.upper()}{n}" for l, n in REF.findall("\n".join(lines))))
    return refs[:limit] if limit else refs


# ------------------------------------------------------------------ requests

def collect_votes(per_reply: int = 3) -> tuple[list[Article], list[str]]:
    """Papers asked for in unprocessed replies, with their votes, and the reply files read.

    a.requested is the number of readers who asked for it; a.owner_pick is set when
    one of them is Calvin (the Gmail script flags his replies as "owner").
    """
    if not INBOX.exists():
        return [], []
    done = _load(REQUESTS).get("processed", {})
    issues = _issues()
    wanted: dict[str, Article] = {}
    voters: dict[str, set[str]] = {}
    files = []
    for path in sorted(INBOX.glob("*.json")):
        reply = json.loads(path.read_text(encoding="utf-8"))
        if reply.get("id") in done:
            continue
        files.append(path.name)
        issue = _issue_for(reply, issues)
        refs = reply_refs(reply.get("body", ""), per_reply)
        if not issue or not refs:
            log.info("Reply %s: no issue or IDs found", reply.get("id"))
            continue
        voter = reply.get("sender") or reply.get("id") or path.stem  # anonymous code per reader
        for ref in refs:
            saved = issue["articles"].get(ref)
            if not saved:
                log.info("Reply %s: %s is not in the %s issue", reply.get("id"), ref, issue["date"])
                continue
            a = article_from_dict(saved)
            a = wanted.setdefault(a.key, a)
            if voter in voters.setdefault(a.key, set()):
                continue  # one vote per reader and paper
            voters[a.key].add(voter)
            a.requested += 1
            a.owner_pick = a.owner_pick or bool(reply.get("owner"))
    articles = sorted(wanted.values(), key=lambda a: -a.requested)
    log.info("Votes: %d papers from %d replies", len(articles), len(files))
    return articles, files


def top_picks(articles: list[Article], n: int = 5, seed: str = "") -> list[Article]:
    """Most votes first; on equal votes Calvin's picks go first, then a random draw."""
    rng = random.Random(seed)
    ranked = sorted(articles, key=lambda a: (-a.requested, not a.owner_pick, rng.random()))
    return ranked[:n]


def mark_processed(files: list[str]) -> None:
    """After a real send: log the replies as handled and remove them from inbox/."""
    data = _load(REQUESTS)
    processed = data.setdefault("processed", {})
    today = date.today().isoformat()
    for name in files:
        path = INBOX / name
        reply = json.loads(path.read_text(encoding="utf-8"))
        processed[reply.get("id") or name] = {"on": today, "refs": reply_refs(reply.get("body", ""))}
        path.unlink()
    _save(REQUESTS, data)


def queue_resend(articles: list[Article], dived: list[Article]) -> None:
    """Remember requested papers so the next regular issue sends them again."""
    data = _load(REQUESTS)
    queue = data.setdefault("resend", {})
    dived_keys = {a.key for a in dived}
    today = date.today().isoformat()
    for a in articles:
        entry = queue.setdefault(a.key, {"article": asdict(a), "votes": 0, "dive_on": None})
        entry["votes"] += a.requested
        if a.key in dived_keys:
            entry["dive_on"] = today
    _save(REQUESTS, data)


def resend_queue() -> list[Article]:
    """Papers requested since the last regular issue, most votes first."""
    out = []
    for entry in _load(REQUESTS).get("resend", {}).values():
        a = article_from_dict(entry["article"])
        a.requested, a.dive_sent = entry["votes"], entry.get("dive_on")
        a.deep_dive, a.ref = None, ""
        out.append(a)
    return sorted(out, key=lambda a: -a.requested)


def clear_resend() -> None:
    data = _load(REQUESTS)
    data["resend"] = {}
    _save(REQUESTS, data)


# ------------------------------------------------------------------ deep dives

def write_deep_dives(articles: list[Article], cfg) -> None:
    """Fill a.deep_dive for each article; answers are cached by paper."""
    cache = _load(DIVES)
    todo = []
    for a in articles:
        if a.key in cache:
            a.deep_dive = cache[a.key]
        else:
            todo.append(a)
    if not todo:
        return
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_FEDERATION_RULE_ID")):
        log.warning("No Anthropic credentials: %d deep dives skipped", len(todo))
        return
    import anthropic

    client = anthropic.Anthropic()
    dd = cfg.settings.get("deep_dive") or {}
    for a in todo:
        try:
            a.deep_dive = _one(client, a, dd)
        except Exception as e:  # one bad paper must not stop the brief
            log.error("Deep dive failed for %s: %s", a.key, e)
            continue
        cache[a.key] = {**a.deep_dive, "on": date.today().isoformat()}
    _save(DIVES, cache)


def _one(client, a: Article, dd: dict) -> dict:
    import anthropic

    meta = f"Title: {a.title}\nVenue: {a.venue}\nDate: {a.date}\n\nAbstract: {a.abstract or '(none)'}"
    sources = [("full text", a.pdf_url)] if a.pdf_url else []
    sources.append(("abstract", None))
    for based_on, pdf in sources:
        content = [{"type": "text", "text": meta}]
        if pdf:
            content.insert(0, {"type": "document", "source": {"type": "url", "url": pdf}})
        request = dict(
            model=dd.get("model", "claude-sonnet-5-5"), max_tokens=16000, system=PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": dd.get("effort", "medium"),
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        try:
            response = call_claude(client, request)
        except anthropic.APIStatusError as e:
            if pdf:  # PDF behind a paywall or not a PDF: fall back to the abstract
                log.warning("Full text unavailable for %s (%s); using the abstract", a.key, e)
                continue
            raise
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined")
        text = next(b.text for b in response.content if b.type == "text")
        return {**json.loads(text), "based_on": based_on}
    raise RuntimeError("no source could be read")


def _save(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _load(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
