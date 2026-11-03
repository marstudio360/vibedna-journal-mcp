# Named test_write_* so it runs after test_quick_map: indexing its temp roots changes the shared test index.
"""A lesson appended to a living journal points at the refined manual whose section means the same thing.

Real case 2026-11-01 (owner: "is it synced with everything we have been learning in the journals lately?"): the
non-expiring system user token for the ad account was learned on 2026-10-15 and written in two other projects'
journals; the sold manual "Run Meta Ads With Your AI" kept teaching a sixty-day token until 2026-11-01, because the
rule "lessons go up to the sold manual" only covered its own source journal and nothing pointed at it.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-manual-hint-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest  # noqa: E402
import meaning  # noqa: E402
import server as s  # noqa: E402

LESSON = ("Ads token + Conversions API: now a system user token that never expires. Before: a sixty-day user token of "
          "the ads app; it died when the owner's session closed and server-side purchases stopped reaching Meta. Now: "
          "system user Adsuser, ads_management + ads_read + business_management, debug_token SYSTEM_USER, expires_at 0. "
          "Steps: assign the ad account and pixel, give the system user Develop app on the app, Generate token Never.")
MANUAL = ("---\nkind: refined\ntitle: \"Run Meta Ads With Your AI: The Journal\"\n---\n\n# Run Meta Ads With Your AI\n\n"
          "## Part 1: Your own app and a sixty-day token\n\nIssue the token from the Graph API Explorer and exchange it "
          "for a long-lived one that lives about sixty days.\n")


@pytest.fixture(autouse=True)
def _restore_index():
    """Indexing this file's temp roots drops the other test files' journals from the shared test index: put the
    roots back and re-index after each test (2026-11-01: two test_quick_map tests failed after this file ran)."""
    before = os.environ.get("JOURNAL_ROOTS")
    yield
    if before is None:
        os.environ.pop("JOURNAL_ROOTS", None)
    else:
        os.environ["JOURNAL_ROOTS"] = before
    s._index_refresh_internal()


def _setup(tmp: Path, monkeypatch):
    root = tmp / "projects"
    (root / "shop").mkdir(parents=True, exist_ok=True)
    (root / "journals-drafts").mkdir(parents=True, exist_ok=True)
    living = root / "shop" / "SHOP_JOURNAL.md"
    living.write_text("# SHOP\n\n## Recent entries\n", encoding="utf-8")
    manual = root / "journals-drafts" / "run-meta-ads-with-ai.md"
    manual.write_text(MANUAL, encoding="utf-8")
    os.environ["JOURNAL_ROOTS"] = str(root)
    s._index_refresh_internal()
    return living, manual


def _fake_query(manual: Path, score: float):
    def query(q, k=8, min_score=0.0, path_like="", timeout=1.5):
        if path_like and path_like.lower() not in str(manual).lower():
            return []
        return [{"path": str(manual), "journal": manual.name, "line": 9,
                 "heading": "Part 1: Your own app and a sixty-day token", "score": score, "by": "meaning"}]
    return query


def _path_as_indexed(p: Path) -> str:
    c = s._conn()
    try:
        row = c.execute("SELECT path FROM journals WHERE name=?", (p.name,)).fetchone()
    finally:
        c.close()
    return row[0]


def test_real_case_points_at_the_manual(monkeypatch):
    living, manual = _setup(_TMP / "a", monkeypatch)
    monkeypatch.setattr(meaning, "query", _fake_query(Path(_path_as_indexed(manual)), 0.644))
    res = s.journal_append(str(living), LESSON, tag="meta")
    assert res.get("ok") and res["manual_hint"]["journal"] == "run-meta-ads-with-ai.md"
    assert "add it there in the same turn" in res["manual_hint"]["hint"]


def test_below_floor_readings_and_short_entries_say_nothing(monkeypatch):
    living, manual = _setup(_TMP / "b", monkeypatch)
    real = Path(_path_as_indexed(manual))
    monkeypatch.setattr(meaning, "query", _fake_query(real, 0.60))
    assert "manual_hint" not in s.journal_append(str(living), LESSON, tag="fix")
    monkeypatch.setattr(meaning, "query", _fake_query(real, 0.9))
    assert "manual_hint" not in s.journal_append(str(living), LESSON, tag="reading")
    assert "manual_hint" not in s.journal_append(str(living), "short note about the token", tag="fix")


def test_no_service_and_the_manual_itself_say_nothing(monkeypatch):
    living, manual = _setup(_TMP / "c", monkeypatch)
    monkeypatch.setattr(meaning, "query", lambda *a, **k: [])
    assert "manual_hint" not in s.journal_append(str(living), LESSON, tag="fix")
    monkeypatch.setattr(meaning, "query", _fake_query(Path(_path_as_indexed(manual)), 0.9))
    assert "manual_hint" not in s.journal_append(_path_as_indexed(manual), LESSON, tag="fix")
