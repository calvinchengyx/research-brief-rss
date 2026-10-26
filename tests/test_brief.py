"""Offline tests: a stub OpenAlex feeds the real pipeline; nothing touches the network."""

import json

import pytest

from brief import deepdive, pipeline, recipe, resolve, state
from brief.models import Article, Author
from brief.render import author_line
from brief.select import apply_cap

SETTINGS = {"max_articles": 20, "topic_priority": ["css", "comm", "cl"],
            "topic_quota": {"comm": {"min": 3, "max": 5}, "cl": {"min": 3, "max": 5}}}


def art(i, topic, preprint=False, scholar=False, journal=True, relevance=0.0):
    a = Article(id=f"W{i}", title=f"Paper {i}", venue="V", venue_id="S1", date="2026-10-15",
                authors=[Author("A")], abstract="", url="u", is_preprint=preprint)
    a.topic, a.scholar_hit, a.journal_hit, a.relevance = topic, scholar, journal and not preprint, relevance
    return a


def count(items, topic):
    return sum(a.topic == topic and not a.top_priority for a in items)


def test_no_cap_when_twenty_or_fewer():
    items = [art(i, "cl") for i in range(20)]
    selected, overflow = apply_cap(items, SETTINGS)
    assert len(selected) == 20 and overflow == []


def test_cap_order_css_then_comm_then_cl():
    items = ([art(i, "css") for i in range(8)] + [art(100 + i, "comm") for i in range(30)]
             + [art(200 + i, "cl") for i in range(30)] + [art(300, "css", scholar=True)])  # 1 top priority
    selected, overflow = apply_cap(items, SETTINGS)
    assert len(selected) == 20
    assert sum(a.top_priority for a in selected) == 1
    assert count(selected, "css") == 8
    assert count(selected, "comm") + count(selected, "cl") == 11
    assert 3 <= count(selected, "cl") <= 11 - 3
    assert len(overflow) == len(items) - 20


def test_cap_keeps_minimums_when_css_is_large():
    items = [art(i, "css") for i in range(40)] + [art(100 + i, "comm") for i in range(10)] \
        + [art(200 + i, "cl") for i in range(10)]
    selected, _ = apply_cap(items, SETTINGS)
    assert (count(selected, "css"), count(selected, "comm"), count(selected, "cl")) == (14, 3, 3)


def test_cap_fills_spare_slots_when_css_is_small():
    items = [art(i, "css") for i in range(2)] + [art(100 + i, "comm") for i in range(30)] \
        + [art(200 + i, "cl") for i in range(30)]
    selected, _ = apply_cap(items, SETTINGS)
    assert len(selected) == 20
    assert count(selected, "css") == 2


def test_scholar_watch_has_its_own_quota():
    items = ([art(i, "css") for i in range(30)] + [art(100 + i, "comm") for i in range(10)]
             + [art(200 + i, "cl") for i in range(10)]
             + [art(300 + i, "cl", preprint=True, scholar=True, journal=False) for i in range(10)])
    selected, _ = apply_cap(items, {**SETTINGS, "scholar_watch": {"max": 5}})
    watch = [a for a in selected if a.scholar_hit and not a.journal_hit]
    assert len(watch) == 5
    assert count([a for a in selected if a not in watch], "css") == 9
    assert sum(1 for a in selected if a.topic == "comm") == 3


def test_scholar_preprints_rank_before_other_preprints():
    items = [art(i, "cl", preprint=True, relevance=9) for i in range(30)] + \
        [art(99, "cl", preprint=True, scholar=True, relevance=1)] + [art(500 + i, "css") for i in range(19)]
    selected, _ = apply_cap(items, SETTINGS)
    assert "W99" in {a.id for a in selected}


def test_author_line_nature_style_keeps_followed():
    a = art(1, "css")
    a.authors = [Author(n) for n in "ABCDEFG"]
    a.authors[3].followed = True
    shown = author_line(a)
    names = [x.get("name", "[...]") for x in shown]
    assert names == ["A", "B", "[...]", "D", "[...]", "G"]
    assert shown[3]["bold"]


# ---------------------------------------------------------------- end to end

def work(wid, title, source_id, source_type="journal", authors=(), abstract="social media users",
         field="Social Sciences", wtype="article"):
    return {
        "id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/10.1/{wid.lower()}",
        "display_name": title, "publication_date": "2026-10-16", "type": wtype,
        "primary_location": {"source": {"id": f"https://openalex.org/{source_id}", "display_name": source_id,
                                        "type": source_type}, "landing_page_url": None},
        "authorships": [{"author": {"id": f"https://openalex.org/{aid}", "display_name": name},
                         "institutions": [{"id": f"https://openalex.org/{inst}", "lineage": [
                             f"https://openalex.org/{inst}"]}] if inst else []}
                        for aid, name, inst in authors],
        "abstract_inverted_index": {w: [i] for i, w in enumerate(abstract.split())},
        "primary_topic": {"field": {"display_name": field}},
    }


class StubOpenAlex:
    calls = 0

    def resolve_source(self, entry):
        ids = {"Journal of Communication": "SJOC", "Nature": "SNAT"}
        return {"ids": [ids[entry["name"]]] if entry["name"] in ids else [], "matched": [entry["name"]],
                "exact": True}

    def resolve_author(self, entry):
        ids = {"Jennifer Pan": "APAN", "Kate Starbird": "ASTAR"}
        aid = ids.get(entry["name"])
        return {"id": aid, "matched": entry["name"], "institution": "X", "alternatives": []}

    def resolve_institution(self, name):
        return {"id": "IOX" if name == "University of Oxford" else None, "matched": name, "exact": True}

    def resolve_repository(self, name):
        return {"ids": ["SARX"] if name == "arXiv" else [], "matched": [name]}

    def field_ids(self, names):
        return ["33", "17"]

    def expand(self, author_id, mode, min_joint, years, cap=60):
        return [{"id": "ACO", "name": "Coauthor Person", "joint_papers": 3}] if author_id == "APAN" else []

    def works_by(self, key, ids, since, until, extra=None, max_results=5000):
        if key == "primary_location.source.id":
            return [
                work("W1", "Pan in J Comm", "SJOC", authors=[("APAN", "Jennifer Pan", None)]),
                work("W2", "Plain J Comm paper", "SJOC", authors=[("AX", "Someone", None)]),
                work("W3", "Physics in Nature", "SNAT", abstract="quantum lattice spins", field="Physics"),
                work("W4", "Erratum", "SJOC", wtype="erratum"),
            ]
        if key == "authorships.author.id":
            return [work("W5", "Coauthor preprint", "SARX", "repository",
                         authors=[("ACO", "Coauthor Person", None)], field="Computer Science",
                         abstract="language models and social media"),
                    work("W7", "Coauthor math paper", "SMATH", "journal",
                         authors=[("ACO", "Coauthor Person", None)], field="Mathematics",
                         abstract="tail bounds for convex programs")]
        if key == "authorships.institutions.lineage":
            return [work("W6", "Oxford preprint on online harms", "SARX", "repository",
                         authors=[("AQ", "Q", "IOX")])]
        return []


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(resolve, "STATE_DIR", tmp_path)
    monkeypatch.setattr(resolve, "CACHE", tmp_path / "resolved.json")
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "SEEN", tmp_path / "seen.json")
    monkeypatch.setattr(pipeline.cls, "STATE_DIR", tmp_path)
    monkeypatch.setattr(recipe, "RECIPE", tmp_path / "recipe.html")
    monkeypatch.setattr(deepdive, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(deepdive, "ISSUES", tmp_path / "issues")
    monkeypatch.setattr(deepdive, "REQUESTS", tmp_path / "requests.json")
    monkeypatch.setattr(deepdive, "DIVES", tmp_path / "deep_dives.json")
    monkeypatch.setattr(pipeline, "PREVIEW_DIR", tmp_path / "preview")
    monkeypatch.setattr(pipeline, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_FEDERATION_RULE_ID", raising=False)
    return tmp_path


def test_pipeline_end_to_end(sandbox):
    stats = pipeline.run("preview", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    html = (sandbox / "preview" / "latest.html").read_text()
    assert "Pan in J Comm" in html and "Top priority" in html          # overlap flagged
    assert "Plain J Comm paper" in html
    assert "Physics in Nature" not in html                            # filtered venue, off topic
    assert "Erratum" not in html
    assert "Coauthor preprint" in html and "coauthor of Pan" in html  # scholar watch
    assert "Oxford preprint on online harms" in html                  # institution-filtered preprint
    assert "Coauthor math paper" not in html                          # coauthors' work is topic-filtered
    assert stats["priority"] == 1
    assert "Kate Starbird" in html                                    # quiet scholars listed
    assert not (sandbox / "seen.json").exists()                       # preview never records state
    assert "following.md" in {p.name for p in sandbox.iterdir()}


def test_recipe_explains_the_run(sandbox):
    pipeline.run("preview", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    page = (sandbox / "recipe.html").read_text()
    report = json.loads((sandbox / "preview" / "run.json").read_text())
    assert "What was picked and why" in page
    assert report["selected"] and all(a["reason"] for a in report["selected"])
    assert report["sources"]["raw"] >= report["found"]
    for a in report["selected"]:
        assert a["title"].replace("&", "&amp;") in page


def test_send_records_and_never_repeats(sandbox, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send", lambda to, subject, html, text, s: sent.append((to, subject)))
    pipeline.run("send", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    assert sent and sent[0][0] == pipeline.load_config().recipients
    seen = json.loads((sandbox / "seen.json").read_text())
    assert len(seen["sent"]) >= 4
    stats = pipeline.run("preview", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    assert stats["new"] == 0


def test_lookups_resume_after_rate_limit(sandbox):
    calls = []

    def flaky(name):
        calls.append(name)
        if name == "c" and calls.count("c") == 1:
            raise RuntimeError("429")
        return {"id": name.upper()}

    cache = {}
    with pytest.raises(RuntimeError):
        resolve._section(cache, "institutions", ["a", "b", "c", "d"], flaky)
    cache = resolve.load_cache()                       # saved progress survives the crash
    resolve._section(cache, "institutions", ["a", "b", "c", "d"], flaky)
    assert cache["institutions"] == {"a": {"id": "A"}, "b": {"id": "B"}, "c": {"id": "C"}, "d": {"id": "D"}}
    assert calls == ["a", "b", "c", "c", "d"]          # a and b were not looked up twice


def test_classification_is_cached(sandbox, monkeypatch):
    from brief import classify as cls
    from brief.config import load_config
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []

    def fake_ai(articles, cfg, done):
        calls.append(len(articles))
        for a in articles:
            a.keep, a.topic, a.relevance, a.summary = True, "css", 7.0, "s"
            done.append(a)

    monkeypatch.setattr(cls, "_classify_ai", fake_ai)
    cfg = load_config()
    papers = [Article(id=f"W{i}", title=f"T{i}", venue="V", venue_id=None, date="2026-10-20", authors=[], abstract="", url="") for i in range(3)]
    cls.classify(papers, cfg, use_ai=True)
    again = [Article(id=f"W{i}", title=f"T{i}", venue="V", venue_id=None, date="2026-10-20", authors=[], abstract="", url="") for i in range(3)]
    cls.classify(again, cfg, use_ai=True)
    assert calls == [3, 0]
    assert all(a.keep and a.relevance == 7.0 for a in again)


def test_reply_refs_ignore_quoted_text():
    body = "Please send a deep dive on b2 and A1, thanks!\n\nOn Mon, 2 Nov 2026 Calvin wrote:\n> A3 Some title"
    assert deepdive.reply_refs(body) == ["B2", "A1"]
    assert deepdive.reply_refs("a 1-year study") == []
    assert deepdive.reply_refs("A1 A2 A3 A4 B1", limit=3) == ["A1", "A2", "A3"]


def _art(key, votes, owner=False):
    a = Article(id=key, title=key, venue="V", venue_id=None, date="2026-10-20", authors=[], abstract="", url="")
    a.requested, a.owner_pick = votes, owner
    return a


def test_top_picks_break_ties_for_calvin_then_at_random():
    papers = [_art("W1", 1), _art("W2", 3), _art("W3", 1, owner=True), _art("W4", 1), _art("W5", 1),
              _art("W6", 1, owner=True), _art("W7", 1), _art("W8", 1, owner=True)]
    picks = [a.id for a in deepdive.top_picks(papers, 5, seed="2026-11-10")]
    assert picks[0] == "W2"                                   # most votes first
    assert set(picks[1:4]) == {"W3", "W6", "W8"}              # then Calvin's tied picks
    assert len(set(picks[4:]) & {"W1", "W4", "W5", "W7"}) == 1
    assert picks == [a.id for a in deepdive.top_picks(papers, 5, seed="2026-11-10")]  # same draw on rerun


def test_replies_get_a_next_day_deep_dive_and_come_back(sandbox, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send", lambda to, subject, *a, **k: sent.append(subject))
    pipeline.run("send", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    issue = json.loads((sandbox / "issues" / "2026-10-21.json").read_text())
    ref = next(r for r, a in issue["articles"].items() if a["title"] == "Plain J Comm paper")
    html = (sandbox / "preview" / "latest.html").read_text()
    assert f">{ref}<" in html and "reply to this email" in html.lower()

    def reply(n, refs, sender="r1", owner=False):
        (sandbox / "inbox").mkdir(exist_ok=True)
        (sandbox / "inbox" / f"m{n}.json").write_text(json.dumps({
            "id": f"m{n}", "sender": sender, "owner": owner, "date": "2026-10-22T09:00:00Z",
            "subject": f"Re: {issue['subject']}", "body": f"{refs}\n\n> quoted"}))

    def fake_dive(articles, cfg):
        for a in articles:
            a.deep_dive = {"research_questions": ["Q?"], "methods": "Survey.", "findings": ["F."],
                           "based_on": "abstract"}
    monkeypatch.setattr(pipeline, "write_deep_dives", fake_dive)

    assert pipeline.run_dives("send")["dives"] == 0 and len(sent) == 1   # no replies: no email

    others = [r for r in issue["articles"] if r != ref]
    reply(1, f"{ref}, {others[0]}, {others[1]}, {others[2]}")           # fourth ID is ignored
    reply(2, ref, sender="r1")                                            # same reader again: no extra vote
    reply(3, ref, sender="r2")
    stats = pipeline.run_dives("send")
    assert stats == {"requested": 3, "dives": 3, "votes": 4} and "deep dives" in sent[-1]
    dives = (sandbox / "preview" / "dives.html").read_text()
    assert "Plain J Comm paper" in dives and "Research questions" in dives and f">{ref}<" in dives
    assert not list((sandbox / "inbox").glob("*.json"))                  # handled once
    assert pipeline.run_dives("send")["dives"] == 0                      # and not again

    # Replies to a [TEST] email count in test runs only
    (sandbox / "inbox" / "t1.json").write_text(json.dumps({
        "id": "t1", "sender": "r3", "date": "2026-10-22T10:00:00Z",
        "subject": f"Re: [TEST] {issue['subject']}", "body": ref}))
    assert pipeline.run_dives("test")["dives"] == 1
    assert pipeline.run_dives("send")["dives"] == 0 and not (sandbox / "inbox" / "t1.json").exists()

    # The next regular issue re-sends every requested paper at the top
    stats = pipeline.run("send", "2026-10-26", "2026-11-02", oa=StubOpenAlex())
    html = (sandbox / "preview" / "latest.html").read_text()
    assert stats["requested"] == 3 and "You asked for these" in html and "Asked for by 2 readers" in html
    later = json.loads((sandbox / "issues" / "2026-11-02.json").read_text())
    assert later["articles"]["A1"]["title"] == "Plain J Comm paper"
    assert pipeline.run("preview", "2026-11-02", "2026-11-09", oa=StubOpenAlex())["requested"] == 0


def test_test_sends_go_to_test_recipients_only(sandbox, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send", lambda to, *a, **k: sent.append(to))
    first = pipeline.run("test", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    cfg = pipeline.load_config()
    assert sent == [cfg.test_recipients] and "aliya.andrich@uzh.ch" not in sent[0]
    assert pipeline.run("preview", "2026-10-11", "2026-10-21", oa=StubOpenAlex())["shown"] == first["shown"]


def test_scheduled_runs_send_every_other_week(sandbox):
    from datetime import date
    (sandbox / "archive").mkdir()
    (sandbox / "archive" / "2026-10-26.html").write_text("issue")
    assert not pipeline.due(date(2026, 11, 2))   # one week later: skip
    assert pipeline.due(date(2026, 11, 9))       # two weeks later: send
