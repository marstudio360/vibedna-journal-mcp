"""Newest word wins (owner 2026-11-03): cards get the newest state-changing entry about the same thing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

JOURNAL = """# ADSCOPE: Engineering Journal

## Already exists (extend, never rebuild)
- **Turn the ads that keep running into ranked winners and product cards**: ADSCOPE 4.0 (PC: ADSCOPE/, git f26887a): adscope.py report --score; run_group.sh <group> · status: partial: built and tested on the PC, NOT deployed on gpubox yet · since: 2026-10-29
- **See which competitor ads run longest**: ADSCOPE v3 on gpubox: adscope.py run/report · status: working · since: 2026-10-26

## 2026-10-29 02:28 [ship] ADSCOPE 4.0 built and tested on the PC, NOT deployed (2026-10-29, PC agent)

body

## 2026-10-29 02:36 [ship] ADSCOPE 4.0 DEPLOYED on gpubox (PC session, 2026-10-29 ~05:25-05:37 UTC)

body

## 2026-10-31 21:17 [watchlist] group shopsite gained keywords

body
"""


def _journal(tmp_path):
    p = tmp_path / "ADSCOPE_JOURNAL.md"
    p.write_text(JOURNAL, encoding="utf-8")
    return p


def test_latest_word_finds_the_deploy_by_identity(tmp_path):
    p = _journal(tmp_path)
    cap = server._parse_capabilities(JOURNAL)[0]
    cap["path"] = str(p)
    lw = server.latest_word(cap, use_meaning=False)
    assert lw and lw["when"] == "2026-10-29 02:36" and "DEPLOYED" in lw["entry"]


def test_a_watchlist_note_is_not_a_state_change(tmp_path):
    p = _journal(tmp_path)
    cap = server._parse_capabilities(JOURNAL)[1]
    cap["path"] = str(p)
    lw = server.latest_word(cap, use_meaning=False)
    assert lw is None or "watchlist" not in lw["entry"]


def test_append_without_a_judge_writes_no_card_marks(tmp_path, monkeypatch):
    # 2026-11-03: the identity rule marked an unrelated AI_TEAM card; without a judge nothing is written
    p = _journal(tmp_path)
    monkeypatch.setattr(server, "_resolve", lambda name: {"path": str(p)})
    monkeypatch.setattr(server, "manual_hint", lambda *a, **k: None)
    res = server.journal_append(name_or_path="ADSCOPE_JOURNAL.md", tag="ship",
                                entry="ADSCOPE 4.0 product cards live for every company group")
    assert "latest:" not in p.read_text(encoding="utf-8") and not res.get("cards_updated")


def test_identity_sync_still_works_when_called_directly(tmp_path, monkeypatch):
    p = _journal(tmp_path)
    monkeypatch.setattr(server, "_resolve", lambda name: {"path": str(p)})
    monkeypatch.setattr(server, "manual_hint", lambda *a, **k: None)
    server.journal_append(name_or_path="ADSCOPE_JOURNAL.md", tag="ship",
                          entry="ADSCOPE 4.0 product cards live for every company group")
    ts = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "product cards live" in ln][0][3:19]
    res = {"cards_updated": server._sync_cards_after_append(p, ts, "[ship] ADSCOPE 4.0 product cards live for every company group", use_judge=False)}
    text = p.read_text(encoding="utf-8")
    first, second = [ln for ln in text.splitlines() if ln.startswith("- **")]
    assert "latest:" in first and "product cards live" in first
    assert "NOT deployed on gpubox yet" in first          # nothing else in the card is touched
    assert "latest:" not in second
    assert res.get("cards_updated")
    # a second ship replaces the latest mark instead of piling up
    server.journal_append(name_or_path="ADSCOPE_JOURNAL.md", tag="fix", entry="ADSCOPE 4.0 cards fixed for ES")
    ts2 = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "cards fixed for ES" in ln][0][3:19]
    server._sync_cards_after_append(p, ts2, "[fix] ADSCOPE 4.0 cards fixed for ES", use_judge=False)
    first = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- **")][0]
    assert first.count("latest:") == 1 and "cards fixed for ES" in first


def test_exact_identifiers_are_recognised():
    # real case 2026-11-03: "203.0.113.65" became the term "203011365" and nothing was found
    assert server._exact_ids("203.0.113.65") == ["203.0.113.65"]
    assert server._exact_ids("who is @demoacct_ on X") == ["@demoacct_"]
    assert server._exact_ids("box:8812 panel") == ["box:8812"]
    assert server._exact_ids("commit f26887a") == ["f26887a"]
    assert server._exact_ids("quick_hook.py and the journal") == []
    assert server._exact_ids("decade facade") == []


def test_code_name_search_keeps_only_cards_that_name_it():
    cards = [{"what": "Capture cold outreach replies", "how": "worker", "journal": "X.md"},
             {"what": "Open questions hook", "how": "hooks/owner_answer_guard.py shows them", "journal": "Y.md"}]
    out = server._search_cards("owner_answer_guard", cards)
    assert [c["what"] for c in out] == ["Open questions hook"]
    assert server._search_cards("owner_answer_guard", cards[:1]) == []
