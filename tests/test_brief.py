"""Offline tests: a stub OpenAlex feeds the real pipeline; nothing touches the network."""

import json

import pytest

from brief import pipeline, resolve, state
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
                         abstract="language models")]
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
    assert stats["priority"] == 1
    assert "Kate Starbird" in html                                    # quiet scholars listed
    assert not (sandbox / "seen.json").exists()                       # preview never records state
    assert "following.md" in {p.name for p in sandbox.iterdir()}


def test_send_records_and_never_repeats(sandbox, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send", lambda to, subject, html, text, s: sent.append((to, subject)))
    pipeline.run("send", "2026-10-11", "2026-10-21", oa=StubOpenAlex())
    assert sent and sent[0][0] == ["owencheng1992930@gmail.com"]
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
