"""Journals DNA 1.4.0, the buyer's view of what is new: your own tools list (empty until you write one), and every
new check working with no judge (the older behaviour) until you switch the judge on.

Run: python -m pytest tests   (everything in temporary journal homes; the judge is never called)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
_TMP = Path(tempfile.mkdtemp(prefix="journals-dna-140-"))
(_TMP / "projects").mkdir()

TOOLS = {"Mail Robot": {"names": ["mail robot", "mailbot"],
                        "sheet": "Sends the newsletter through the email API, never through a browser."},
         "Shop Scanner": "Reads competitor prices once a day from their public pages."}


def _home(name: str) -> Path:
    h = _TMP / name
    h.mkdir(parents=True, exist_ok=True)
    return h


def _run(args: list, home: Path, stdin: str = "", **extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, JOURNAL_HOME=str(home), JOURNAL_ROOTS=str(_TMP / "projects"), PYTHONIOENCODING="utf-8",
               JOURNAL_JUDGE="off", JOURNAL_MEANING_OFF="1")
    for k in ("JOURNAL_TOOLS_FILE", "JOURNAL_JUDGE_MODEL", "JOURNAL_JUDGE_STRONG_MODEL", "JOURNAL_JUDGE_CMD",
              "JOURNAL_REPLY_GATE"):
        env.pop(k, None)
    env.update(extra)
    return subprocess.run([sys.executable, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(PKG), env=env, timeout=120)


TOOLS_CODE = ("import json, quickmap as q; print(json.dumps([q.OUR_TOOLS, q.TOOL_FACTS, "
              "q._named_tools('does the mailbot post through the browser? and the shop scaner?'), "
              "q._tool_cards_block('does the mailbot post through the browser?'), "
              "q.tool_claims_check('The mail robot posts through a browser. ' * 20)]))")


def test_no_tools_are_listed_until_you_list_yours():
    r = _run(["-c", TOOLS_CODE], _home("empty"))
    assert r.returncode == 0, r.stderr
    names, facts, named, block, claims = json.loads(r.stdout.strip().splitlines()[-1])
    assert names == {} and facts == {} and named == [] and block == "" and claims == ""


def test_tools_json_in_the_journal_home_names_your_tools():
    home = _home("listed")
    (home / "tools.json").write_text(json.dumps(TOOLS), encoding="utf-8")
    r = _run(["-c", TOOLS_CODE], home)
    assert r.returncode == 0, r.stderr
    names, facts, named, block, claims = json.loads(r.stdout.strip().splitlines()[-1])
    assert names == {"Mail Robot": "mail robot|mailbot", "Shop Scanner": "shop scanner"}
    assert named == ["Mail Robot", "Shop Scanner"]   # small typos still match
    assert block.startswith("WHAT OUR TOOLS DO TODAY")
    assert "Mail Robot: Sends the newsletter through the email API" in block
    assert claims == ""   # no judge: the reply's tools check stays quiet


def test_tools_file_setting_and_a_broken_file():
    other = _TMP / "elsewhere" / "my_tools.json"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(json.dumps(TOOLS), encoding="utf-8")
    r = _run(["-c", "import quickmap as q; print(sorted(q.OUR_TOOLS))"], _home("setting"), JOURNAL_TOOLS_FILE=str(other))
    assert r.stdout.strip() == "['Mail Robot', 'Shop Scanner']", r.stderr
    bad = _home("broken")
    (bad / "tools.json").write_text("{not json", encoding="utf-8")
    r = _run(["-c", "import quickmap as q; print(q.OUR_TOOLS, q.TOOL_FACTS)"], bad)
    assert r.returncode == 0 and r.stdout.strip() == "{} {}", r.stderr


def test_no_tool_named_means_no_judge_call_even_with_a_judge(monkeypatch):
    import judge
    import quickmap
    monkeypatch.setattr(quickmap, "OUR_TOOLS", {})
    monkeypatch.setattr(quickmap, "TOOL_FACTS", {})
    monkeypatch.setattr(judge, "available", lambda: True)

    def boom(*a, **k):
        raise AssertionError("the judge was called")
    monkeypatch.setattr(judge, "_run", boom)
    assert quickmap.tool_claims_check("Social posting goes through the browser. " * 20) == ""
    assert quickmap._tool_cards_block("does the mail robot use the browser?") == ""


def test_the_judge_needs_the_switch_and_the_claude_command():
    code = "import judge; print(judge.available(), judge.judge('q', ['a', 'b']), judge.complete('p'))"
    assert _run(["-c", code], _home("j1"), JOURNAL_JUDGE="").stdout.strip() == "False None None"
    r = _run(["-c", code], _home("j2"), JOURNAL_JUDGE="on", JOURNAL_JUDGE_CMD="no-such-command-for-journals-dna")
    assert r.stdout.strip() == "False None None", r.stderr


def test_no_model_name_is_built_in(monkeypatch):
    import judge
    seen = []

    class R:
        stdout = "{}"
    monkeypatch.setattr(judge.subprocess, "run", lambda args, **k: seen.append(args) or R())
    monkeypatch.setattr(judge, "MODEL", "")
    judge._run("pick")
    assert "--model" not in seen[-1]   # the claude command's own default model
    judge._run("pick", model="my-small-model")
    assert seen[-1][-2:] == ["--model", "my-small-model"]


def test_newer_word_is_quiet_without_a_judge(monkeypatch):
    import meaning
    import quickmap
    old = {"journal": "SHOP_JOURNAL.md", "line": 10, "heading": "2026-01-05 10:00 [rule] prices are typed by hand"}
    monkeypatch.setattr(meaning, "query", lambda q, **k: [
        {"journal": "SHOP_JOURNAL.md", "line": 90, "heading": "2026-03-01 09:00 [ship] prices come from the list"}])
    assert quickmap._newer_word(old) == ""


def test_reply_gate_on_without_a_judge_lets_the_reply_through():
    home = _home("gate")
    (home / "tools.json").write_text(json.dumps(TOOLS), encoding="utf-8")
    call = {"session_id": "buyer-140", "reply": "The mail robot posts the newsletter through a browser. " * 10}
    r = _run(["quick_hook.py", "--stop"], home, json.dumps(call), JOURNAL_REPLY_GATE="on")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_owner_brief_without_a_judge_uses_your_decisions_and_starts_nothing():
    home = _home("brief")
    j = _TMP / "projects" / "BRIEF" / "BRIEF_JOURNAL.md"
    j.parent.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    j.write_text("# BRIEF JOURNAL\n\n## Decided\n"
                 "- **Every price comes from the price list file** · date: 2026-10-20 · why: one place to change it\n\n"
                 f"## {today} 10:00 [correction] Do not hard-code the shipping fee\nThe owner said \"read it from the list\".\n",
                 encoding="utf-8")
    code = ("import json, owner_brief as b; p = r'" + str(j) + "'; "
            "print(json.dumps([b.lines_for(p), b.brief_text(p)]))")
    r = _run(["-c", code], home)
    assert r.returncode == 0, r.stderr
    lines, text = json.loads(r.stdout.strip().splitlines()[-1])
    assert "- RULE [2026-10-20] Every price comes from the price list file" in lines
    assert any("Do not hard-code the shipping fee" in ln for ln in lines)
    assert text.startswith("OWNER BRIEF, BRIEF_JOURNAL.md")
    briefs = home / "owner_briefs"
    assert not briefs.exists() or not list(briefs.glob("*.lock"))   # no background rebuild without a judge


def test_prompt_hook_without_a_judge_runs_as_before():
    home = _home("prompt")
    call = {"session_id": "buyer-140-p", "prompt": "where are we on the checkout? the mail robot posted yesterday"}
    r = _run(["quick_hook.py", "--prompt"], home, json.dumps(call))
    assert r.returncode == 0, r.stderr
    assert "WHAT OUR TOOLS DO TODAY" not in r.stdout and "NEWER WORD" not in r.stdout
