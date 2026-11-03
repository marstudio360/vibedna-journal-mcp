"""The relevance judge: wiring and fallbacks, without calling the real CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import judge  # noqa: E402
import server  # noqa: E402


def test_judge_is_off_in_tests():
    assert judge.judge("anything", ["a", "b"]) is None


def test_search_cards_follow_the_judge(monkeypatch):
    cards = [{"what": "Capture cold outreach replies", "journal": "X.md"},
             {"what": "Ad Scope ranks winning ads", "journal": "Y.md"},
             {"what": "Office game skins", "journal": "Z.md"}]
    out = server._search_cards("winning ad scope", cards, judged=[1])
    assert [c["what"] for c in out] == ["Ad Scope ranks winning ads"]
    assert server._search_cards("winning ad scope", cards, judged=[]) == []


def test_append_card_sync_uses_the_judge_and_rereads_the_file(tmp_path, monkeypatch):
    p = tmp_path / "X_JOURNAL.md"
    p.write_text("# X\n\n## Already exists\n- **Render the PDF report** · how: reportgen 2.1 · status: partial · since: 2026-11-01\n"
                 "- **Old HTML report** · how: reportgen 1.0 · status: working · since: 2026-10-20\n", encoding="utf-8")

    def fake_judge(q, texts, task=""):
        # another session appends while the judge thinks
        p.write_text(p.read_text(encoding="utf-8") + "\n## 2026-11-03 02:10 [note] written meanwhile\n", encoding="utf-8")
        return [0]
    monkeypatch.setattr(server, "_judge", fake_judge)
    touched = server._sync_cards_after_append(p, "2026-11-03 02:09", "[ship] reportgen PDF deployed", "body")
    text = p.read_text(encoding="utf-8")
    assert touched == ["Render the PDF report"]
    assert "written meanwhile" in text                       # nothing appended meanwhile is lost
    first, second = [ln for ln in text.splitlines() if ln.startswith("- **")]
    assert "latest: 2026-11-03 02:09 [ship] reportgen PDF deployed" in first and "latest:" not in second
