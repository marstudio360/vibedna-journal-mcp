"""The check before a command runs (actioncheck.py), without the real judge or meaning service.

Real cases from 2026-11-04: a bare GitHub fetch went down the read path and the memory was never asked; the owner's
GitHub rule sat inside a big CORRECTIONS section and never came up; an IP was taken for another machine.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import actioncheck  # noqa: E402

GIT = "git"
FETCH = f'cd "D:/aa-wt/checkout-track-1030" && {GIT} fetch -q origin main 2>/dev/null; {GIT} log -1 --oneline origin/main'


def test_heads_name_what_each_piece_runs():
    assert actioncheck.heads(FETCH) == ["git fetch", "git log"]
    assert actioncheck.heads("for i in 1 2; do ssh appuser@10.0.0.1 'uptime'; done") == ["ssh"]
    assert actioncheck.heads("T=$(grep X .env.local | cut -d= -f2); GIT_TERMINAL_PROMPT=0 git -c a= fetch u main")[-1] == "git fetch"
    assert actioncheck.heads('python "C:/x/deploy/site_deploy.py" --dry') == ["python site_deploy.py"]
    assert actioncheck.heads("ls src/app") == ["ls"]


def test_names_are_the_things_a_command_reaches():
    assert actioncheck._names("ssh appuser@198.51.100.105 'uptime'") == ["198.51.100.105"]
    assert "gpubox" in actioncheck._names("ssh gpubox 'df -h'")


def _setup(tmp_path, monkeypatch, verdict):
    monkeypatch.setattr(actioncheck, "HEADS", tmp_path / "heads.json")
    monkeypatch.setattr(actioncheck, "RECENT", tmp_path / "recent.json")
    monkeypatch.setattr(actioncheck, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(actioncheck, "OFF", False)
    monkeypatch.setattr(__import__("meaning"), "OFF", False)   # the search by meaning is set up here
    monkeypatch.setattr(actioncheck, "_closest_rules", lambda q, n=8: [
        {"text": "Every git command that reaches GitHub carries the key itself", "where": "RULES_JOURNAL.md:121"}])
    monkeypatch.setattr(actioncheck, "_entries", lambda q: [])
    monkeypatch.setattr(actioncheck, "_name_lines", lambda c: [])
    import judge
    calls = []
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", lambda prompt, model="", **k: calls.append(prompt) or json.dumps(verdict))
    return calls


def test_a_broken_rule_stops_the_command_with_the_right_way(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"applies": ["git fetch"], "breaks": [
        {"rule": "1", "why": "bare fetch, no key", "right_way": "carry GITHUB_PUSH_TOKEN"}]})
    why = actioncheck.check(FETCH, "Fetch latest main")
    assert "STOPPED BEFORE IT RUNS" in why and "RULES_JOURNAL.md:121" in why and "GITHUB_PUSH_TOKEN" in why
    # the same command again passes: the judge can be wrong, never a deadlock
    assert actioncheck.check(FETCH, "Fetch latest main") == ""


RULES = [{"text": "Nothing heavy runs on his PC: renders, installs and video jobs go to the remote box", "where": "RULES_JOURNAL.md:94"},
         {"text": "Every git command that reaches GitHub carries the key itself", "where": "RULES_JOURNAL.md:121"}]


def _progs(tmp_path, monkeypatch, about, rules=RULES):
    """Programs judged against ALL rules: about = {program: [rule numbers about it]}."""
    monkeypatch.setattr(actioncheck, "PROGS", tmp_path / "progs.json")
    monkeypatch.setattr(actioncheck, "PROGS_LOCK", tmp_path / "progs.lock")
    monkeypatch.setattr(actioncheck, "_rules", lambda: list(rules))
    started = []
    monkeypatch.setattr(actioncheck, "classify_later", lambda progs: started.append(set(progs)))
    import judge
    real = judge._run

    def fake(prompt, model="", **k):
        if "Programs the assistants run" in prompt:
            return json.dumps(about)
        return real(prompt, model=model, **k)
    monkeypatch.setattr(judge, "_run", fake)
    return started


def test_a_program_is_free_only_after_all_rules_say_so(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, {"applies": [], "breaks": []})
    started = _progs(tmp_path, monkeypatch, {"ls": [], "ffmpeg": [1]})
    assert actioncheck.check("ls src/app", "List files") == ""
    assert len(calls) == 2 and started == [{"ls"}]      # not classified yet: judged, classification started
    actioncheck.classify(["ls", "ffmpeg"])
    assert actioncheck.check("ls other", "List files") == ""
    assert len(calls) == 2                                # ls is free against every rule: no judge
    actioncheck.check("ffmpeg -v error -i a.mp4 -frames:v 1 f.png", "Grab a frame")
    assert len(calls) == 4                                # a rule (heavy work on the PC) is about ffmpeg: always judged


def test_a_new_rule_makes_a_free_program_judged_again(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, {"applies": [], "breaks": []})
    _progs(tmp_path, monkeypatch, {"npm": []})
    actioncheck.classify(["npm"])
    assert actioncheck.free_programs({"npm"}) == {"npm"}
    # the owner corrects an npm install on his PC: the new rule has not been judged for npm yet
    RULES2 = RULES + [{"text": "Installs and builds go to the box, never npm install on the PC", "where": "RULES_JOURNAL.md:350"}]
    monkeypatch.setattr(actioncheck, "_rules", lambda: list(RULES2))
    assert actioncheck.free_programs({"npm"}) == set()
    actioncheck.check("npm install @pump-fun/pump-swap-sdk", "Install SDK")
    assert len(calls) == 2


def test_no_answer_from_the_memory_stops_once_and_says_so(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"applies": [], "breaks": []})
    _progs(tmp_path, monkeypatch, {})

    def down(q, n=8):
        raise RuntimeError("embedding service timed out")
    monkeypatch.setattr(actioncheck, "_closest_rules", down)
    why = actioncheck.check("ffmpeg -i a.mp4 b.mp4", "Encode")
    assert why.startswith("NOT CHECKED")
    assert actioncheck.check("ffmpeg -i a.mp4 b.mp4", "Encode") == ""   # same command again: never a deadlock


def test_recent_commands_reach_the_judge(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, {"applies": ["ssh"], "breaks": []})
    actioncheck.check("ssh host1 'uptime'", "load")
    actioncheck.check("ssh host1 'free -m'", "memory")
    assert "ssh host1 'uptime'" in calls[-1]


def _setup_write(tmp_path, monkeypatch, maybe, breaks):
    monkeypatch.setattr(actioncheck, "HEADS", tmp_path / "heads.json")
    monkeypatch.setattr(actioncheck, "WRITE_RULES", tmp_path / "write_rules.json")
    monkeypatch.setattr(actioncheck, "OFF", False)
    monkeypatch.setattr(__import__("meaning"), "OFF", False)   # the search by meaning is set up here
    rules = [{"text": "Never write the em-dash or en-dash anywhere (first said 2026-05-18)", "where": "RULES_JOURNAL.md:24"},
             {"text": "Deploy with npm run ship", "where": "RULES_JOURNAL.md:120"}]
    monkeypatch.setattr(actioncheck, "_rules", lambda: rules)
    import judge
    calls = []

    def fake(prompt, model="", **k):
        calls.append(prompt)
        if "Which of them can be broken by the TEXT" in prompt:
            return json.dumps({"write": [1]})
        if '"maybe"' in prompt:
            return json.dumps({"maybe": maybe})
        return json.dumps({"breaks": breaks})
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", fake)
    return calls


def test_a_write_that_breaks_a_rule_is_stopped(tmp_path, monkeypatch):
    calls = _setup_write(tmp_path, monkeypatch, [1], [{"rule": "1", "why": "em dash in copy", "right_way": "use a colon"}])
    why = actioncheck.check_write("C:/site/src/app/hero.tsx", "export const HERO = 'Fifty loops " + chr(8212) + " drag them in'")
    assert "STOPPED BEFORE IT IS WRITTEN" in why and "RULES_JOURNAL.md:24" in why
    # the fast scan only sees the rules about written text (the deploy rule was left out once, by the judge)
    scan = next(p for p in calls if '"maybe"' in p)
    assert "em-dash" in scan and "npm run ship" not in scan


def test_a_clean_write_costs_one_fast_call(tmp_path, monkeypatch):
    calls = _setup_write(tmp_path, monkeypatch, [], [])
    assert actioncheck.check_write("C:/x/usd.ts", "export const usd = (c: number) => '$' + c / 100") == ""
    assert actioncheck.check_write("C:/x/usd2.ts", "export const usd2 = (c: number) => '$' + c / 100") == ""
    picks = [p for p in calls if "Which of them can be broken by the TEXT" in p]
    assert len(picks) == 1  # the rule subset is judged once and kept
    assert len(calls) == 3


def test_journals_are_never_checked_as_writes(tmp_path, monkeypatch):
    calls = _setup_write(tmp_path, monkeypatch, [1], [{"rule": "1", "why": "x", "right_way": "y"}])
    assert actioncheck.check_write("C:/x/TONE_GARDEN_JOURNAL.md", "a long entry that quotes " + chr(8212) + " on purpose") == ""
    assert calls == []


def test_silent_without_a_judge(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {})
    import judge
    monkeypatch.setattr(judge, "available", lambda: False)
    assert actioncheck.check(FETCH, "x") == ""


def test_no_verdict_from_the_judge_is_not_a_pass(tmp_path, monkeypatch):
    # 2026-11-04: both verdicts came back empty (judge calls timed out) and the command ran as if checked
    _setup(tmp_path, monkeypatch, {})
    _progs(tmp_path, monkeypatch, {})
    import judge
    monkeypatch.setattr(judge, "_run", lambda prompt, model="", **k: "")
    why = actioncheck.check("ffmpeg -i a.mp4 b.mp4", "Encode")
    assert why.startswith("NOT CHECKED")
    assert actioncheck.check("ffmpeg -i a.mp4 b.mp4", "Encode") == ""


def test_an_mcp_call_is_judged_with_the_owner_message_searched_on_its_own(tmp_path, monkeypatch):
    # 2026-11-04: a browser call to look for a mail the journals had already read ran with no check at all, and once
    # checked, the tool's words buried the owner's topic when mixed into one search
    calls = _setup(tmp_path, monkeypatch, {"applies": [], "breaks": [
        {"rule": "SHOPSITE_FULL_JOURNAL.md:6825", "why": "the mail was already read", "right_way": "read the entry first"}]})
    _progs(tmp_path, monkeypatch, {})
    asked = []
    monkeypatch.setattr(actioncheck, "_entries", lambda q: asked.append(q) or ["[SHOPSITE_FULL_JOURNAL.md:6825] Sam part 2"])
    why = actioncheck.check_mcp("mcp__webweave__navigate", '{"url": "https://mail.google.com"}', "el mail de sam carter")
    assert "STOPPED BEFORE IT RUNS" in why and "6825" in why
    assert any(q.startswith("What the owner asked: el mail de sam carter") for q in asked)
    assert "el mail de sam carter" in calls[-1]


def test_an_mcp_tool_judged_fine_is_not_judged_again_for_the_same_message(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, {"applies": [], "breaks": []})
    _progs(tmp_path, monkeypatch, {})
    assert actioncheck.check_mcp("mcp__shopsite__whoami", "{}", "qué plan tengo") == ""
    n = len(calls)
    assert actioncheck.check_mcp("mcp__shopsite__whoami", "{}", "qué plan tengo") == ""
    assert len(calls) == n
    actioncheck.check_mcp("mcp__shopsite__whoami", "{}", "otra cosa")
    assert len(calls) > n
