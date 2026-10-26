"""Load the editable YAML files in config/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
PREVIEW_DIR = ROOT / "preview"
ARCHIVE_DIR = ROOT / "archive"
TEMPLATE_DIR = ROOT / "templates"


JOURNAL_KEYS = {"name", "issn", "topic", "filter", "kind", "short"}
SCHOLAR_KEYS = {"name", "hint", "topic", "type", "openalex", "min_joint_papers", "max_members"}


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    topics: list[dict]
    journals: list[dict]
    scholars: list[dict]
    institutions: dict
    recipients: list[str]
    settings: dict
    topic_names: dict[str, str] = field(default_factory=dict)


def load_config() -> Config:
    topics = _load("topics.yaml")["topics"]
    cfg = Config(
        topics=topics,
        journals=_load("journals.yaml")["journals"],
        scholars=_load("scholars.yaml")["scholars"],
        institutions=_load("institutions.yaml"),
        recipients=[r for r in _load("recipients.yaml").get("recipients", []) if r],
        settings=_load("settings.yaml"),
        topic_names={t["id"]: t["name"] for t in topics},
    )
    for entry, allowed in [(j, JOURNAL_KEYS) for j in cfg.journals] + [(sc, SCHOLAR_KEYS) for sc in cfg.scholars]:
        stray = set(entry) - allowed
        if stray:  # usually a name with a comma that needs "quotes"
            raise ValueError(f"{entry['name']}: unexpected {sorted(stray)}; put names containing commas in quotes")
        if entry.get("topic") not in cfg.topic_names:
            raise ValueError(f"{entry['name']}: unknown topic {entry.get('topic')!r} (see topics.yaml)")
    return cfg
