"""Which articles were already sent (state/seen.json), so nothing is sent twice."""

from __future__ import annotations

import json
from datetime import date, timedelta

from .config import STATE_DIR
from .models import Article

SEEN = STATE_DIR / "seen.json"
KEEP_DAYS = 180


class Seen:
    def __init__(self):
        data = json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.exists() else {}
        self.sent: dict[str, dict] = data.get("sent", {})          # key -> {title, preprint, on}
        self.screened: dict[str, str] = data.get("screened", {})   # key -> date (filtered out)
        self.sent_titles = {v["title"]: v for v in self.sent.values()}

    def is_new(self, a: Article) -> bool:
        if a.key in self.sent or a.key in self.screened:
            return False
        earlier = self.sent_titles.get(a.title_key)
        if earlier:
            if earlier.get("preprint") and not a.is_preprint:
                a.now_published = True  # show the published version once
                return True
            return False
        return True

    def record(self, sent: list[Article], screened: list[Article]) -> None:
        today = date.today().isoformat()
        for a in sent:
            self.sent[a.key] = {"title": a.title_key, "preprint": a.is_preprint, "on": today}
        for a in screened:
            self.screened.setdefault(a.key, today)

    def save(self) -> None:
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        sent = {k: v for k, v in self.sent.items() if v["on"] >= cutoff}
        screened = {k: v for k, v in self.screened.items() if v >= cutoff}
        STATE_DIR.mkdir(exist_ok=True)
        SEEN.write_text(json.dumps({"sent": sent, "screened": screened}, indent=0), encoding="utf-8")
