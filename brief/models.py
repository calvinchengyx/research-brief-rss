"""The Article record that flows through the pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Author:
    name: str
    id: str | None = None
    institution_ids: list[str] = field(default_factory=list)  # lineage, includes parents
    followed: bool = False


@dataclass
class Article:
    id: str                       # OpenAlex work ID (W...)
    title: str
    venue: str
    venue_id: str | None
    date: str                     # YYYY-MM-DD
    authors: list[Author]
    abstract: str
    url: str
    doi: str | None = None
    is_preprint: bool = False
    research_field: str | None = None  # OpenAlex primary_topic field, e.g. "Social Sciences"
    pdf_url: str | None = None    # open-access PDF, used for deep dives

    # Set by the pipeline
    journal_hit: bool = False     # published in a listed journal/conference
    scholar_hit: bool = False     # written by a followed scholar (or their coauthor/lab member)
    anchor_hit: bool = False      # written by someone named in scholars.yaml
    scholar_names: list[str] = field(default_factory=list)
    needs_filter: bool = False    # from a `filter: social-science` venue or a preprint
    topic: str | None = None
    keep: bool = True
    relevance: float = 0.0        # 0-10, closeness to my research interests
    summary: str = ""             # one-line AI summary
    editors_pick: bool = False
    now_published: bool = False   # an earlier preprint of this article was already sent
    ref: str = ""                 # ID shown in the email (A1, B2 ...) that readers reply with
    requested: int = 0            # readers who asked for a deep dive
    owner_pick: bool = False      # Calvin was one of them (wins ties)
    dive_sent: str | None = None  # date the deep-dive email covered it
    deep_dive: dict | None = None

    @property
    def top_priority(self) -> bool:
        return self.journal_hit and self.scholar_hit

    @property
    def key(self) -> str:
        return (self.doi or self.id).lower()

    @property
    def title_key(self) -> str:
        return normalize_title(self.title)


def article_from_dict(d: dict) -> Article:
    """Rebuild an Article saved with dataclasses.asdict (state/issues/*.json)."""
    d = dict(d)
    d["authors"] = [Author(**a) for a in d.get("authors", [])]
    known = Article.__dataclass_fields__
    return Article(**{k: v for k, v in d.items() if k in known})


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
