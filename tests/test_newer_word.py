"""An old rule shown in the per-message map gets the newer entry that changes it (owner 2026-11-03: a September
"Social Engine is used by CLI, not as MCP" rule was shown as current; October entries say it ships as an MCP)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import judge  # noqa: E402
import meaning  # noqa: E402
import quickmap  # noqa: E402

OLD = {"journal": "POST_PILOT_JOURNAL.md", "line": 1350, "score": 0.62,
       "heading": "2026-09-08 00:44 [regla] EL SOCIAL ENGINE SE USA POR CLI, NO COMO MCP (Owner, 2026-09-08)"}
NEWER = [
    {"journal": "JOURNAL_MCP_JOURNAL.md", "line": 1261, "score": 0.6,
     "heading": "2026-11-03 17:12 [mod-miss] MOD MISS (owner: it publishes through the API)"},
    {"journal": "SOCIAL_SYSTEM_JOURNAL_USER.md", "line": 2279, "score": 0.58,
     "heading": "2026-10-12 19:33 [ship] Social Engine 1.11.14 published for buyers as an MCP"},
    {"journal": "POST_PILOT_JOURNAL.md", "line": 900, "score": 0.57,
     "heading": "2026-08-01 10:00 [note] Social Engine CLI flags"},
]


def test_old_rule_gets_the_newer_entry_that_changes_it(monkeypatch):
    seen = {}
    monkeypatch.setattr(meaning, "query", lambda q, **k: NEWER)

    def fake_judge(q, texts, **k):
        seen["texts"] = texts
        return [0]
    monkeypatch.setattr(judge, "judge", fake_judge)
    out = quickmap._newer_word(OLD)
    assert "NEWER WORD (2026-10-12 19:33, SOCIAL_SYSTEM_JOURNAL_USER.md:2279)" in out
    # older entries and notes about the memory system itself are never offered as the newer word
    assert all("2026-08-01" not in t and "[mod-miss]" not in t for t in seen["texts"])


def test_no_newer_word_when_the_judge_sees_no_change(monkeypatch):
    monkeypatch.setattr(meaning, "query", lambda q, **k: NEWER)
    monkeypatch.setattr(judge, "judge", lambda q, texts, **k: [])
    assert quickmap._newer_word(OLD) == ""


def test_only_rules_and_decisions_older_than_a_week(monkeypatch):
    called = []
    monkeypatch.setattr(meaning, "query", lambda q, **k: called.append(q) or NEWER)
    monkeypatch.setattr(judge, "judge", lambda q, texts, **k: [0])
    assert quickmap._newer_word({**OLD, "heading": "2026-09-08 00:44 [ship] Social Engine 1.9 live"}) == ""
    import time
    today = time.strftime("%Y-%m-%d")
    assert quickmap._newer_word({**OLD, "heading": f"{today} 10:00 [decision] something new"}) == ""
    assert not called
