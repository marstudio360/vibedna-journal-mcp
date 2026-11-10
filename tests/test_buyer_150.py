"""Journals DNA 1.5.0, the buyer's view of what is new, on a fresh folder of invented journals.

- the AI checks of each command, tool call and write are off by default (JOURNAL_AI_CHECKS=off|risky|all), and no
  model name is built in;
- the first touch of a mapped piece carries its journal brief instead of a stop;
- an exact rule test stops a command once, and the same command again passes;
- a rule reminder shows once per session;
- the server flood counter counts nothing without your hosts, and stops the 7th call in a minute with them;
- rules come from your rules journals (RULES_JOURNAL.md included) and the files you list, nothing else;
- without the search by meaning set up, the reply check never answers "NOT CHECKED";
- the money guard checks nothing without your paid_patterns.txt, then stops a paid run until your latest message says
  yes (English words, plus your own in JOURNAL_APPROVAL_WORDS);
- the background rule compile starts only when a rule LINE changed, never on a dated entry alone.

Run: python -m pytest tests   (everything in temporary journal homes; the real judge is never called)
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
_TMP = Path(tempfile.mkdtemp(prefix="journals-dna-150-"))
ROOT = _TMP / "projects"


def _write(rel: str, text: str, root: Path = ROOT) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


_write("SHOP/SHOP_JOURNAL.md", """# SHOP JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Checkout | checkout, cart, payments.py | the shop team | SHOP/SHOP_JOURNAL.md | hosted payment page only |

## Handoff for next session
- [ ] add the tax line to the receipt

## 2026-10-20 10:00 [ship] checkout retries a failed card once
The retry lives in payments.py.
""")
_write("SHOP/RULES_JOURNAL.md", "# RULES\n\n## Deploys\n"
       "- 2026-03-06: Production deploys go through the release script, never a bare deploy command from a laptop.\n")
_write("SHOP/SHOP_RULES_JOURNAL.md", "# SHOP RULES\n\n- 2026-03-07: Every price shown to customers comes from the price list file.\n")
_write("SHOP/NOTES_JOURNAL.md", "# NOTES\n\n- 2026-03-08: This is a note, not a rule, about the weekly newsletter schedule.\n")

ENV_KEYS = ("JOURNAL_AI_CHECKS", "JOURNAL_ACTION_CHECK_ALL", "JOURNAL_ACTION_CHECK", "JOURNAL_BOX_HOSTS", "JOURNAL_RULE_FILES",
            "JOURNAL_JUDGE_MODEL", "JOURNAL_JUDGE_STRONG_MODEL", "JOURNAL_VERDICT_MODEL", "JOURNAL_COMPILE_MODEL",
            "JOURNAL_JUDGE_CMD", "JOURNAL_REPLY_GATE", "JOURNAL_MEANING_URL", "JOURNAL_INCLUDE_VAULT_PATH",
            "JOURNAL_BRAND_NAMES", "JOURNAL_TOOLS_FILE", "JOURNAL_APPROVAL_WORDS", "JOURNAL_AUTOCOMPILE")


def _home(name: str) -> Path:
    h = _TMP / name
    h.mkdir(parents=True, exist_ok=True)
    return h


def _env(home: Path, **extra) -> dict:
    env = dict(os.environ, JOURNAL_HOME=str(home), JOURNAL_ROOTS=str(ROOT), PYTHONIOENCODING="utf-8", JOURNAL_JUDGE="off")
    for k in ENV_KEYS:
        env.pop(k, None)
    env.pop("JOURNAL_MEANING_OFF", None)   # 1.5.0: off until set up, whatever the test runner says
    env.update(extra)
    return env


def _run(args: list, home: Path, stdin: str = "", **extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(PKG), env=_env(home, **extra), timeout=180)


def _hook(call: dict, home: Path, *flags, **extra) -> dict:
    r = _run(["quick_hook.py", *flags], home, json.dumps(call), **extra)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    return json.loads(out.splitlines()[-1]).get("hookSpecificOutput", {}) if out else {}


def _bash(cmd: str, session: str = "s1") -> dict:
    return {"session_id": session, "reports_reads": True, "tool_name": "Bash",
            "tool_input": {"command": cmd, "description": "run it"}}


# A driver that runs the hook in one process with the judge and the AI checks replaced by recorders, so a test sees
# which AI work a call would start (nothing reaches a real model).
DRIVER = r"""
import io, json, sys
sys.argv = ["quick_hook.py"]
import judge, actioncheck, quick_hook
calls = []
judge.available = lambda: True
judge._run = lambda prompt, *a, **k: calls.append("JUDGE " + prompt[:60]) or "{}"
actioncheck.check = lambda *a, **k: calls.append("COMMAND CHECK") or ""
actioncheck.check_mcp = lambda *a, **k: calls.append("MCP CHECK") or ""
actioncheck.check_write = lambda *a, **k: calls.append("WRITE CHECK") or ""
sys.stdin = io.StringIO(sys.argv_call)
quick_hook.main()
print("CALLS=" + json.dumps(calls))
"""


def _ai_calls(call: dict, home: Path, **extra) -> list:
    code = DRIVER.replace("sys.argv_call", repr(json.dumps(call)))
    r = _run(["-c", code], home, **extra)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1][len("CALLS="):])


def test_ai_checks_are_off_by_default_and_on_only_when_asked():
    home = _home("ai")
    risky = _bash("ssh build-server 'rm -rf /tmp/old'")
    write = {"session_id": "w1", "tool_name": "Write",
             "tool_input": {"file_path": str(ROOT / "SHOP" / "README.md"), "content": "Our new checkout page, live today."}}
    mcp = {"session_id": "m1", "tool_name": "mcp__mail__send_message", "tool_input": {"mcp_tool": "mcp__mail__send_message", "args": "{}"}}
    for call in (risky, write, mcp):
        got = _ai_calls(call, home)
        assert not [c for c in got if c.endswith("CHECK")], got   # off: no AI check of commands, writes or tool calls
    assert "COMMAND CHECK" in _ai_calls(risky, home, JOURNAL_AI_CHECKS="risky")
    assert "COMMAND CHECK" not in _ai_calls(_bash("ls -la"), home, JOURNAL_AI_CHECKS="risky")   # only risky commands
    assert "COMMAND CHECK" in _ai_calls(_bash("ls -la", "s2"), home, JOURNAL_AI_CHECKS="all")
    assert "MCP CHECK" in _ai_calls(mcp, home, JOURNAL_AI_CHECKS="risky")
    code = "import quick_hook; print(quick_hook._ai_mode())"
    assert _run(["-c", code], home).stdout.strip() == "off"
    assert _run(["-c", code], home, JOURNAL_AI_CHECKS="nonsense").stdout.strip() == "off"


def test_no_model_name_is_built_in():
    home = _home("models")
    code = ("import json, subprocess, judge, rulecompile\n"
            "seen = []\n"
            "class R: stdout = '{\"result\": \"ok\"}'\n"
            "subprocess.run = lambda args, **k: seen.append(args) or R()\n"
            "judge._run('hello', model=judge.VERDICT)\n"
            "print(json.dumps([judge.MODEL, judge.STRONG, judge.VERDICT, rulecompile.MODEL, seen[0]]))")
    model, strong, verdict, compile_model, args = json.loads(_run(["-c", code], home).stdout.strip().splitlines()[-1])
    assert model == strong == compile_model == "" and verdict == "cli-default"
    assert "--model" not in args   # the claude command's own default model
    out = _run(["-c", code], home, JOURNAL_VERDICT_MODEL="big-model").stdout.strip().splitlines()[-1]
    assert json.loads(out)[2] == "big-model" and json.loads(out)[4][-2:] == ["--model", "big-model"]


def test_a_stop_never_falls_back_to_the_quick_or_strong_model():
    # measured on our own computer: a small model deciding stops stopped 93-97% of what it read, almost all false
    home = _home("verdict")
    code = ("import json, subprocess, judge, rulecompile\n"
            "seen = []\n"
            "class R: stdout = '{\"result\": \"ok\"}'\n"
            "subprocess.run = lambda args, **k: seen.append(args) or R()\n"
            "judge._run('a stop', model=judge.VERDICT)\n"
            "judge._run('a compile', model=rulecompile.MODEL or judge.VERDICT)\n"
            "judge._run('a pick', model=judge.STRONG)\n"
            "judge._run('a quick pick')\n"
            "print(json.dumps(seen))")
    stop, compile_, pick, quick = json.loads(_run(["-c", code], home, JOURNAL_JUDGE_MODEL="small-model",
                                                  JOURNAL_JUDGE_STRONG_MODEL="mid-model").stdout.strip().splitlines()[-1])
    assert "--model" not in stop and "--model" not in compile_   # verdict unset: the command's own default model
    assert pick[-2:] == ["--model", "mid-model"] and quick[-2:] == ["--model", "small-model"]   # picks keep theirs


def test_first_touch_of_a_mapped_piece_delivers_the_brief_not_a_stop():
    home = _home("brief")
    call = {"session_id": "b1", "reports_reads": True, "tool_name": "Edit",
            "tool_input": {"file_path": str(ROOT / "SHOP" / "payments.py"), "content": "x = 1\n"}}
    first = _hook(call, home)
    assert "permissionDecision" not in first, first
    ctx = first.get("additionalContext", "")
    assert "JOURNAL BRIEF" in ctx and "SHOP_JOURNAL.md" in ctx and "add the tax line to the receipt" in ctx, ctx
    events = [json.loads(x)["kind"] for x in (home / "mod_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "brief" in events
    again = _hook(call, home)
    assert "JOURNAL BRIEF" not in json.dumps(again) and again.get("permissionDecision") != "deny"   # counted as read


def _compiled(home: Path, rules: dict) -> None:
    (home / "compiled_rules.json").write_text(json.dumps(rules), encoding="utf-8")


def test_an_exact_rule_test_stops_once_and_the_same_command_passes_on_retry():
    home = _home("exact")
    _compiled(home, {"k1": {"kind": "mechanical", "on": "command", "pattern": r"\bdeploy\s+--prod\b", "unless": "",
                            "paths": "", "say": "Ship through the release script, not a bare production deploy.",
                            "where": "RULES_JOURNAL.md:4", "rule": "Production deploys go through the release script."}})
    cmd = _bash("hostcli deploy --prod --yes", "e1")
    first = _hook(cmd, home)
    assert first.get("permissionDecision") == "deny", first
    why = first["permissionDecisionReason"]
    assert "STOPPED BY THE OWNER'S RULES (exact test, no AI)" in why and "RULES_JOURNAL.md:4" in why
    assert _hook(cmd, home).get("permissionDecision") != "deny"   # run again unchanged: it passes
    assert _hook(_bash("npm run release", "e1"), home).get("permissionDecision") != "deny"   # the right way never stops
    kinds = [json.loads(x)["kind"] for x in (home / "mod_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kinds.count("exact_stop") == 1 and kinds.count("exact_override") == 1


def test_a_rule_reminder_shows_once_per_session():
    home = _home("remind")
    _compiled(home, {"k2": {"kind": "judgment", "remind": r"\bnpm\s+install\b", "where": "RULES_JOURNAL.md:9",
                            "rule": "Installs and builds run on the build server, not on this laptop"}})
    first = _hook(_bash("npm install left-pad", "r1"), home)
    assert first.get("permissionDecision") != "deny"   # a reminder never stops
    assert "OWNER RULES FOR THIS COMMAND (reminder" in first.get("additionalContext", "")
    assert "build server" in first["additionalContext"]
    assert "OWNER RULES FOR THIS COMMAND" not in json.dumps(_hook(_bash("npm install other-pkg", "r1"), home))
    assert "OWNER RULES FOR THIS COMMAND" in json.dumps(_hook(_bash("npm install left-pad", "r2"), home))   # new session
    assert "OWNER RULES FOR THIS COMMAND" not in json.dumps(_hook(_bash("ls", "r3"), home))


def test_server_flood_counter_is_off_without_hosts_and_on_with_box_hosts(monkeypatch):
    import cmdguard
    monkeypatch.delenv("JOURNAL_BOX_HOSTS", raising=False)
    none = _home("flood-none")
    assert all(cmdguard.box_flood("ssh myserver uptime", str(none)) == "" for _ in range(12))
    assert not (none / "box_calls.json").exists()   # nothing is counted
    on = _home("flood-on")
    (on / "box_hosts.txt").write_text("# my shared servers\nmyserver*\n", encoding="utf-8")
    got = [cmdguard.box_flood(f"ssh myserver-direct 'cat log{i}'", str(on)) for i in range(7)]
    assert got[:6] == [""] * 6 and "SERVER FLOOD" in got[6]   # the 7th call in 60 s is stopped
    assert cmdguard.box_flood("ssh myserver-direct 'cat log6'", str(on)) == ""   # the same call again passes
    assert cmdguard.box_flood("ssh otherhost uptime", str(on)) == ""   # a host you did not list is never counted
    monkeypatch.setenv("JOURNAL_BOX_HOSTS", "10.0.0.7")
    env_home = _home("flood-env")
    assert [cmdguard.box_flood(f"scp a{i} me@10.0.0.7:/tmp", str(env_home)) for i in range(7)][-1].startswith("STOPPED")


def test_the_flood_counter_runs_in_the_hook():
    home = _home("flood-hook")
    (home / "box_hosts.txt").write_text("myserver\n", encoding="utf-8")
    (home / "box_calls.json").write_text(json.dumps({"t": [time.time()] * 6}), encoding="utf-8")
    out = _hook(_bash("ssh myserver 'df -h'", "f1"), home)
    assert out.get("permissionDecision") == "deny" and "SERVER FLOOD" in out["permissionDecisionReason"], out


def test_rules_come_from_your_rules_journals_and_the_files_you_list():
    home = _home("rules")
    code = ("import server, actioncheck; server._index_refresh_internal(); "
            "print(sorted(p.name for p in actioncheck._rule_files()))")
    assert _run(["-c", code], home).stdout.strip().splitlines()[-1] == "['RULES_JOURNAL.md', 'SHOP_RULES_JOURNAL.md']"
    extra = _write("AGENT_RULES.md", "# My standing rules\n\n- Keys live in the secrets vault, code reads them from env.\n",
                   _TMP / "elsewhere")
    got = _run(["-c", code], home, JOURNAL_RULE_FILES=str(extra)).stdout.strip().splitlines()[-1]
    assert got == "['AGENT_RULES.md', 'RULES_JOURNAL.md', 'SHOP_RULES_JOURNAL.md']", got
    # the plain RULES_JOURNAL.md is also a rules source for the quick map (1.4.0 read only *_RULES_JOURNAL.md)
    code = ("import server, quickmap; server._index_refresh_internal(); "
            "print('\\n'.join(quickmap._owner_rule_lines('run a production deploy command from my laptop')))")
    assert "release script" in _run(["-c", code], home).stdout


def test_the_rule_compiler_never_starts_with_the_judge_off():
    home = _home("compile")
    for _ in range(2):   # the first message builds the index; the second finds the rules journals and stays quiet
        r = _run(["quick_hook.py", "--prompt"], home, json.dumps({"session_id": "c1", "prompt": "deploy the shop today"}))
        assert r.returncode == 0, r.stderr
    assert (home / "index.sqlite").exists()
    assert not (home / "rulecompile.lock").exists() and not (home / "compiled_rules.json").exists()
    r = _run(["rulecompile.py", "build"], home)
    assert r.returncode == 0 and "0 rules compiled" in r.stdout, (r.stdout, r.stderr)


def test_without_the_search_by_meaning_the_reply_check_still_checks():
    home = _home("said")
    code = ("import json, judge, meaning, quickmap\n"
            "judge.available = lambda: True\n"
            "def run(prompt, **k):\n"
            "    if 'From the Reply' in prompt:\n"
            "        return json.dumps({'items': [{'quote': 'the checkout retries a failed card once', 'kind': 'claim', 'query': 'checkout retry'}]})\n"
            "    return json.dumps({'wrong': []})\n"
            "judge._run = run\n"
            "print(json.dumps([meaning.OFF, quickmap.said_check('Done: the checkout retries a failed card once, as before.')]))")
    off, out = json.loads(_run(["-c", code], home).stdout.strip().splitlines()[-1])
    assert off is True and out == ""   # not "NOT CHECKED": nothing to search is not a search that failed


def test_the_money_guard_is_off_without_your_list_and_then_waits_for_your_yes():
    import cmdguard
    none = _home("money-none")
    assert cmdguard.money_guard("modal run train.py", "", str(none)) == ""   # no paid_patterns.txt: nothing is checked
    assert "PAID RUN" not in json.dumps(_hook(_bash("modal run train.py", "m0"), none))
    on = _home("money-on")
    (on / "paid_patterns.txt").write_text("# what spends money, one regex per line\n\\bmodal\\s+run\\b\n"
                                          "api\\.paid-example\\.com\n", encoding="utf-8")
    assert "PAID RUN" in cmdguard.money_guard("modal run train.py", "check the disk", str(on))
    assert "PAID RUN" in cmdguard.money_guard("modal run train.py", "check the disk", str(on))   # a retry does not pass
    assert cmdguard.money_guard("modal run train.py", "yes, run it", str(on)) == ""
    assert cmdguard.money_guard('grep -n "modal run" notes.md', "", str(on)) == ""   # reading a paid name is no run
    out = _hook(_bash("modal run train.py", "m1"), on)
    assert out.get("permissionDecision") == "deny" and "PAID RUN" in out["permissionDecisionReason"], out
    # the yes words are English by default; your own words (any language) come from JOURNAL_APPROVAL_WORDS
    code = "import cmdguard, sys; print(cmdguard.money_guard('modal run train.py', 'oui', sys.argv[1]) == '')"
    assert _run(["-c", code, str(on)], on).stdout.strip() == "False"
    assert _run(["-c", code, str(on)], on, JOURNAL_APPROVAL_WORDS="oui, vas-y").stdout.strip() == "True"


def test_the_background_compile_starts_only_when_a_rule_line_changed():
    home, root = _home("light"), _TMP / "light-projects"
    rules = _write("RULES_JOURNAL.md", "# RULES\n\n- 2026-03-06: Production deploys go through the release script, "
                   "never a bare deploy command.\n", root)
    code = ("import json, os, subprocess, server, judge, quick_hook\n"
            "from pathlib import Path\n"
            "server._index_refresh_internal()\n"
            "judge.available = lambda: True\n"
            "starts = []\n"
            "subprocess.Popen = lambda args, **k: starts.append([str(a) for a in args] + [k.get('creationflags', 0)])\n"
            "home, rules = Path(os.environ['JOURNAL_HOME']), Path(os.environ['TEST_RULES'])\n"
            "def again(extra=''):\n"
            "    (home / 'rulecompile.lock').unlink(missing_ok=True)\n"
            "    if extra:\n"
            "        rules.write_text(rules.read_text(encoding='utf-8') + extra, encoding='utf-8')\n"
            "    out = home / 'compiled_rules.json'\n"
            "    if out.exists():\n"
            "        os.utime(out, (1, 1))   # older than the rules file: a date check alone would compile\n"
            "    quick_hook._compile_later()\n"
            "    return len(starts)\n"
            "first = again()\n"
            "(home / 'compiled_rules.json').write_text('{}', encoding='utf-8')\n"
            "same = again('\\n## 2026-03-09 10:00 [note] a dated entry, no new rule line\\n')\n"
            "changed = again('- 2026-03-10: Every price shown to customers comes from the price list file.\\n')\n"
            "print(json.dumps([first, same, changed, starts[0]]))")
    r = _run(["-c", code], home, JOURNAL_ROOTS=str(root), TEST_RULES=str(rules))
    first, same, changed, start = json.loads(r.stdout.strip().splitlines()[-1])
    assert (first, same, changed) == (1, 1, 2), r.stdout   # a dated entry alone starts nothing
    assert start[-3].endswith("rulecompile.py") and start[-2] == "build"
    if os.name == "nt":
        assert start[-1] & 0x40   # IDLE_PRIORITY_CLASS: the computer gives it only spare time
    else:
        assert start[:3] == ["nice", "-n", "19"]

