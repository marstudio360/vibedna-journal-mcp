"""Newest word wins in the stopping checks (newest.py), without the real judge or meaning service.

Real cases of 2026-11-05: the command check stopped resumed demo builds on a 2026-11-04 "paused" handoff, while a
2026-11-05 entry ("DEMO VIDEO REDO, in progress, owner: finish the demos") had lifted it; the owner's latest message
("sorry I closed it by mistake, go on") was read alone.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import actioncheck  # noqa: E402
import judge  # noqa: E402
import meaning  # noqa: E402
import newest  # noqa: E402

PAUSE = """# VISUAL REVIEW

## Handoff for next session

<!-- written 2026-11-04 16:53 -->
Updated 2026-11-04. The owner paused the demo work while another session improves the Video Studio.
- Next review due 2099-01-01.
"""
AA = """# AA

## 2026-10-31 20:28 [ship] SOUND DEMO DEMO (order 31047 G) shipped

## 2026-11-05 02:00 [handoff] DEMO VIDEO REDO, in progress 2026-11-05 (owner: "let's go, finish the demos")

## 2026-11-05 03:00 [mod-miss] the check stopped the demos

## 2026-11-05 04:00 [ship] Breathwork tempo fix live
"""


def _world(tmp_path, monkeypatch):
    """Two journals in a temp index; each entry's vector says what it is about (demos or tempo)."""
    pe, aa = tmp_path / "VISUAL_REVIEW_JOURNAL.md", tmp_path / "TONE_GARDEN_JOURNAL.md"
    pe.write_text(PAUSE, encoding="utf-8")
    aa.write_text(AA, encoding="utf-8")
    db = tmp_path / "index.sqlite"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE journals (path TEXT)")
    c.execute("CREATE TABLE entries_fts (path TEXT, line INTEGER, heading TEXT, body TEXT)")
    c.execute("CREATE TABLE entries_vec (path TEXT, line INTEGER, heading TEXT, h TEXT, vec BLOB, PRIMARY KEY(path, line))")
    demos, tempo = np.array([1, 0], dtype=np.float16), np.array([0, 1], dtype=np.float16)
    rows = [(pe, 3, "Handoff for next session", PAUSE.split("## Handoff for next session")[1], demos)]
    for i, ln in enumerate(AA.splitlines(), 1):
        if ln.startswith("## "):
            rows.append((aa, i, ln[3:], "", tempo if "tempo" in ln else demos))
    for p, ln, h, b, v in rows:
        c.execute("INSERT INTO entries_fts VALUES (?,?,?,?)", (str(p), ln, h, b))
        c.execute("INSERT INTO entries_vec VALUES (?,?,?,?,?)", (str(p), ln, h, "", v.tobytes()))
    c.executemany("INSERT INTO journals VALUES (?)", [(str(pe),), (str(aa),)])
    c.commit()
    c.close()
    monkeypatch.setattr(newest, "HOME", tmp_path)
    monkeypatch.setattr(meaning, "DB", db)
    monkeypatch.setattr(meaning, "embed", lambda qs: np.array([[1.0, 0.0] for _ in qs], dtype=np.float32))
    newest._rows.clear()
    return pe, aa


def test_a_line_is_dated_by_its_entry_and_a_future_date_is_not_its_date(tmp_path, monkeypatch):
    pe, aa = _world(tmp_path, monkeypatch)
    assert newest.date_at(str(pe), 5) == "2026-11-04 16:53"     # the "written" line, not the 2099 deadline
    assert newest.date_at(str(aa), 3) == "2026-10-31 20:28"
    assert newest.resolve("journal:VISUAL_REVIEW_JOURNAL.md:5") == (str(pe), 5)


def test_newer_lines_are_only_the_ones_written_after_on_the_same_piece(tmp_path, monkeypatch):
    pe, aa = _world(tmp_path, monkeypatch)
    got = newest.newer_lines(str(pe), 5, ["Tone Garden tool demo videos"], k=2)
    assert "TONE_GARDEN_JOURNAL.md:5, 2026-11-05 02:00" in got[0]           # the redo, newer and about demos
    assert not any(":3," in g for g in got)                                    # the 10-31 ship is older
    assert not any("mod-miss" in g for g in got)                               # a note about the check itself
    # an old "shipped" line: the newer redo comes up for it too
    assert any("DEMO VIDEO REDO" in g for g in newest.newer_lines(str(aa), 3, ["Sound Demo demo video"]))


def test_a_stop_falls_when_the_newer_word_lifts_it_and_stands_otherwise(tmp_path, monkeypatch):
    pe, _ = _world(tmp_path, monkeypatch)
    prompts = []
    monkeypatch.setattr(judge, "available", lambda: True)
    answer = {"stands": [], "fell": [{"stop": 1, "newer": "TONE_GARDEN_JOURNAL.md:5", "why": "redo ordered"}]}
    monkeypatch.setattr(judge, "_run", lambda p, **k: prompts.append(p) or json.dumps(answer))
    msgs = [["2026-11-05 12:09", "segui"], ["2026-11-05 14:08", "sorry I closed it by mistake, go on"]]
    stop = [{"text": "the owner paused the demo work", "ref": "VISUAL_REVIEW_JOURNAL.md:5", "piece": "tool demo videos"}]
    assert newest.recheck(stop, "launch three demo builds", msgs) == []
    p = prompts[-1]
    assert "written 2026-11-04 16:53" in p and "DEMO VIDEO REDO" in p
    assert "- 2026-11-05 14:08 (LATEST): sorry I closed it by mistake, go on" in p
    # the judge does not answer: the stop stands (never a silent pass)
    monkeypatch.setattr(judge, "_run", lambda p, **k: "")
    assert newest.recheck(stop, "launch three demo builds", msgs) == [0]


def test_no_newer_line_means_no_extra_call_and_the_stop_stands(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", lambda p, **k: calls.append(p) or "{}")
    stop = [{"text": "rule about something else", "ref": "RULES_JOURNAL.md:9"}]   # not indexed here
    assert newest.recheck(stop, "x", []) == [0] and calls == []


def test_the_command_check_lets_a_lifted_stop_run_and_sends_the_session_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(actioncheck, "HEADS", tmp_path / "heads.json")
    monkeypatch.setattr(actioncheck, "RECENT", tmp_path / "recent.json")
    monkeypatch.setattr(actioncheck, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(actioncheck, "OFF", False)
    monkeypatch.setattr(__import__("meaning"), "OFF", False)   # the search by meaning is set up here
    monkeypatch.setattr(actioncheck, "free_programs", lambda p: set())
    monkeypatch.setattr(actioncheck, "classify_later", lambda p: None)
    monkeypatch.setattr(actioncheck, "_closest_rules", lambda q, n=8: [{"text": "a rule", "where": "RULES_JOURNAL.md:1"}])
    monkeypatch.setattr(actioncheck, "_entries", lambda q: ["[VISUAL_REVIEW_JOURNAL.md:128, 2026-11-04 16:53] paused"])
    monkeypatch.setattr(actioncheck, "_name_lines", lambda c: [])
    prompts = []
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", lambda p, **k: prompts.append(p) or json.dumps({"applies": ["bash build_demo.sh"], "breaks": [
        {"rule": "journal:VISUAL_REVIEW_JOURNAL.md:128", "piece": "tool demo videos", "why": "paused", "right_way": "ask"}]}))
    seen = []
    monkeypatch.setattr(newest, "recheck", lambda stops, what, msgs: seen.append((stops, msgs)) or [])
    msgs = [["2026-11-05 12:09", "segui"], ["2026-11-05 14:08", "sorry I closed it by mistake, go on"]]
    assert actioncheck.check("bash build_demo.sh pc8r room8", "Build the demos", context=msgs[-1][1], msgs=msgs) == ""
    assert seen[0][0][0]["ref"] == "journal:VISUAL_REVIEW_JOURNAL.md:128" and seen[0][0][0]["piece"] == "tool demo videos"
    assert "- 2026-11-05 12:09: segui\n- 2026-11-05 14:08 (LATEST): sorry I closed it by mistake, go on" in prompts[0]
    # the recheck keeps it: the command is stopped
    monkeypatch.setattr(newest, "recheck", lambda stops, what, msgs: [0])
    assert "STOPPED BEFORE IT RUNS" in actioncheck.check("bash build_demo.sh pc8n nature8", "Build", msgs=msgs)


def test_the_session_keeps_the_owners_last_messages_in_order():
    seen = {}
    for i in range(10):
        newest.remember_msg(seen, f"msg {i}")
    assert [m[1] for m in seen["msgs"]] == [f"msg {i}" for i in range(2, 10)]
