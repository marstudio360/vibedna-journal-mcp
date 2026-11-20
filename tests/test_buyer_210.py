"""What 2.1.0 adds, checked on the package itself: the judge starts lean, a name asked about keeps its map, the
Decided cards about a named thing survive a dropped map, an incident is never a ship, journal tools through a
connector count, and the version is the same everywhere."""
import json
import os
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
import judge  # noqa: E402
import quick_hook  # noqa: E402
import quickmap  # noqa: E402


def test_the_version_is_the_same_everywhere():
    v = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    assert v == "2.1.0"
    assert f'VERSION = "{v}"' in (PKG / "server.py").read_text(encoding="utf-8")
    assert json.loads((PKG / "mod" / "journals" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"] == v
    assert f'"version": "{v}"' in (PKG / "mod" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    assert f"# Install Neural DNA {v}" in (PKG / "INSTALL.md").read_text(encoding="utf-8")
    assert f"## {v} " in (PKG / "CHANGELOG.md").read_text(encoding="utf-8")


def test_the_judge_starts_lean_and_can_be_put_back(monkeypatch):
    seen = {}

    class R:
        stdout = '{"result": "ok"}'

    def fake_run(argv, **k):
        seen["env"] = k.get("env")
        return R()
    monkeypatch.setattr(judge.subprocess, "run", fake_run)
    monkeypatch.delenv("JOURNAL_JUDGE_LEAN", raising=False)
    judge._run("hello")
    assert all(seen["env"].get(k) == v for k, v in judge.LEAN_ENV.items()) and seen["env"]["MAX_THINKING_TOKENS"] == "0"
    judge._run("hello", think=True)
    assert all(seen["env"].get(k) == v for k, v in judge.LEAN_ENV.items()) and "MAX_THINKING_TOKENS" not in \
        {k for k in seen["env"] if k not in os.environ}
    monkeypatch.setenv("JOURNAL_JUDGE_LEAN", "off")
    for k in judge.LEAN_ENV:
        monkeypatch.delenv(k, raising=False)
    judge._run("hello")
    assert not any(k in seen["env"] for k in judge.LEAN_ENV)


def test_a_name_negated_inside_a_question_is_asked_about_not_sent_away():
    q = quickmap._fold("and why is the review page on the old site and not on the launch board? look at the capture")
    i = q.index("launch board")
    assert quickmap._NEGATED.search(q[max(0, i - 60):i])       # the old rule alone would drop the name
    assert quickmap._asked_about(q, i)
    w = quickmap._fold("do not show me the launch board while we talk about something else. Go on with the rest")
    assert not quickmap._asked_about(w, w.index("launch board"))
    f = quickmap._fold("why is it not on the launch board man")       # a question typed fast, no question mark
    assert quickmap._asked_about(f, f.index("launch board"))


def test_a_decided_card_about_a_name_the_owner_uses_survives_a_dropped_map():
    cards = [{"what": "Every clip shown for review (Launch board, Library) is shown looped", "journal": "A_JOURNAL.md", "date": "2026-10-28"},
             {"what": "A review is ONE direct link to ONE page; the Launch board is not a feed", "journal": "B_JOURNAL.md", "date": "2026-11-14"},
             {"what": "A review is ONE direct link to ONE page; the Launch board is not a feed", "journal": "C_JOURNAL.md", "date": "2026-11-14"}]
    out = quickmap._ruled_block({"launch board": cards}, 'JOURNAL QUICK MAP for "shop":\n- ABOUT IT ...')
    assert out.startswith("DECIDED ABOUT WHAT THE MESSAGE NAMES")
    assert out.count("\n- ") == 2                              # the same card kept in two journals is shown once
    assert out.index("2026-11-14") < out.index("2026-10-28")   # newest first
    assert quickmap._ruled_block({"launch board": cards}, 'JOURNAL QUICK MAP for "launch board":\n- DECIDED: ...') == ""
    assert quickmap._ruled_block({"launch board": []}, "") == ""


def test_an_incident_is_never_a_ship_whatever_its_title_says():
    assert not quickmap._is_ship_heading("2026-09-20 10:00 [incident] A SECRET KEY TYPED IN A COMMAND WHILE THE SHOP WAS LIVE")
    assert not quickmap._is_ship_heading("2026-11-16 10:00 [bug] THE CHECK FIRED ON A PAGE THAT IS LIVE")
    assert quickmap._is_ship_heading("2026-11-06 18:49 [ship] SHOP PAYMENTS MOVED TO THE NEW PROCESSOR")
    assert quickmap._is_ship_heading("2026-11-06 18:49 [build] THE NEW CHECKOUT IS LIVE")


def test_the_not_done_test_of_a_ship_entry_has_its_own_pattern():
    assert quickmap._NOT_NEAR.search("the importer is not done yet") and quickmap._NOT_NEAR.search("still pending")
    assert quickmap._NOT_NEAR is not quickmap._NEGATED


def test_the_journal_tool_name_is_read_under_any_server():
    assert quick_hook._jtool("mcp__journal__journal_quick") == "journal_quick"
    assert quick_hook._jtool("mcp__some_connector__local_journal_journal_quick") == "journal_quick"
    assert quick_hook._jtool("mcp__some_connector__local_journal_journal_read_section") == "journal_read_section"
    assert quick_hook._jtool("mcp__browser__navigate") == "navigate"
    assert quick_hook._jtool(None) == ""


def test_the_mod_knows_connector_journal_tools_and_says_when_a_map_is_late():
    ts = (PKG / "mod" / "journals" / "hooks" / "register.ts").read_text(encoding="utf-8")
    m = re.search(r"const JOURNAL_READ_TOOL = /(.+)/\n", ts)
    rx = re.compile(m.group(1))
    assert rx.match("mcp__journal__journal_quick") and rx.match("mcp__some_connector__local_journal_journal_search")
    assert not rx.match("mcp__browser__journal_quick_look")
    assert "did not arrive in time" in ts and "ctx.push(LATE)" in ts


def test_the_brief_pick_is_split_so_it_can_run_alongside(monkeypatch):
    import owner_brief
    monkeypatch.setattr(quickmap, "_projects_in_play", lambda seen, names=frozenset(), cap=2: ["/x/A_JOURNAL.md", "/x/B_JOURNAL.md"])
    monkeypatch.setattr(owner_brief, "lines_for", lambda p: [f"RULE [01/01] the first rule of {Path(p).stem} is long enough",
                                                              f"RULE [02/01] the second rule of {Path(p).stem} is long enough"])
    monkeypatch.setattr(owner_brief, "brief_text", lambda p, lines, partial=False: f"{Path(p).stem}{' (part)' if partial else ''}: " + " | ".join(lines))
    seen = {"ob:" + owner_brief._key("/x/A_JOURNAL.md"): 5}   # A had its whole brief at message 5; B never had one
    slots = quickmap._brief_slots(seen, 6)
    assert [(Path(p).stem, whole) for p, _, whole in slots] == [("A_JOURNAL", False), ("B_JOURNAL", True)]
    asked = []
    monkeypatch.setattr(judge, "judge", lambda msg, lines, task="": asked.append(lines) or [1])
    picks = quickmap._brief_picks("what about the second rule?", slots)
    assert picks == {0: [1]} and len(asked) == 1
    text = quickmap._brief_text(slots, picks, shown="")
    assert "A_JOURNAL (part): RULE [02/01]" in text and "B_JOURNAL: RULE [01/01]" in text
    # a line the map already shows is not repeated
    assert "second rule of A_JOURNAL" not in quickmap._brief_text(slots, picks, shown="the second rule of A_JOURNAL is long enough")
