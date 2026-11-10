"""App adapters (adapters/): Codex, GitHub Copilot and Cursor hook payloads -> the Claude Code-style call quick_hook.py
handles, and the core's answer -> each app's output JSON. Sample payloads are the shapes in each app's docs (URL next
to each one, read 2026-11-10). Most tests use a fake core; the end-to-end ones run the real quick_hook.py on a read
of a temporary project (light path: no server import, no judge).
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters import base, run  # noqa: E402
from adapters.codex import ADAPTER as CODEX, parse_patch  # noqa: E402
from adapters.copilot import ADAPTER as COPILOT  # noqa: E402
from adapters.cursor import ADAPTER as CURSOR  # noqa: E402

GATE_DENY = {"hookEventName": "PreToolUse", "permissionDecision": "deny",
             "permissionDecisionReason": 'JOURNALS: you are reading code or data of\n- project "x": JOURNALS GATE, '
                                         "STOPPED. Before touching x, read its journal."}
HARD_DENY = {"hookEventName": "PreToolUse", "permissionDecision": "deny",
             "permissionDecisionReason": "STOPPED BY THE OWNER'S RULES (exact test, no AI): this command breaks: ..."}
BRIEF = {"hookEventName": "PreToolUse",
         "additionalContext": 'JOURNAL BRIEF for project "x" (X_JOURNAL.md), read it before acting'}


class FakeCore:
    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or {}

    def __call__(self, flag, call):
        self.calls.append((flag, call))
        a = self.answer
        return dict(a(flag, call) if callable(a) else a)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for app in ("CODEX", "COPILOT", "CURSOR"):
        monkeypatch.delenv(f"JOURNAL_GATE_{app}", raising=False)
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


# ---- Codex (https://learn.chatgpt.com/docs/hooks.md) -------------------------------------------------------------

CODEX_BASH = {"session_id": "s1", "turn_id": "t1", "transcript_path": None, "cwd": "/repo",
              "hook_event_name": "PreToolUse", "model": "codex-model", "tool_name": "Bash", "tool_use_id": "u1",
              "tool_input": {"command": "ls -la"}, "permission_mode": "default"}

PATCH = """*** Begin Patch
*** Update File: src/app.py
@@ def main():
-    return 1
+    return 2
*** Add File: docs/new.md
+# New
+text
*** Delete File: old.txt
*** Update File: src/move_me.py
*** Move to: src/moved.py
@@
+moved = True
*** Update File: NOTES_JOURNAL.md
+journal line
*** End Patch"""


def test_default_gate_is_note():
    assert base.DEFAULT_GATE == "note"
    assert base.gate_mode("codex") == "note"
    os.environ["JOURNAL_GATE_CODEX"] = "bogus"
    try:
        assert base.gate_mode("codex") == "note"
    finally:
        del os.environ["JOURNAL_GATE_CODEX"]


def test_codex_bash_normalized():
    assert CODEX.normalize(CODEX_BASH) == [("", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": "ls -la", "description": ""},
                                                 "session_id": "s1", "cwd": "/repo"})]


def test_codex_bash_argv_array():
    p = dict(CODEX_BASH, tool_input={"command": ["bash", "-lc", "git status"]})
    assert CODEX.normalize(p)[0][1]["tool_input"]["command"] == "git status"


def test_parse_patch_paths_and_added_text():
    cwd = "/repo"
    got = parse_patch(PATCH, cwd)
    j = lambda rel: os.path.normpath(os.path.join(cwd, rel))  # noqa: E731
    assert [fp for fp, _ in got] == [j("src/app.py"), j("docs/new.md"), j("old.txt"), j("src/move_me.py"),
                                     j("src/moved.py"), j("NOTES_JOURNAL.md")]
    assert dict(got)[j("src/app.py")] == "    return 2"
    assert dict(got)[j("docs/new.md")] == "# New\ntext"
    assert parse_patch("*** Begin Patch\n*** Update File: /abs/x.py\n+a\n*** End Patch", cwd) == [("/abs/x.py", "a")]


def test_codex_apply_patch_becomes_edits():
    p = dict(CODEX_BASH, tool_name="apply_patch", tool_input={"command": PATCH})
    calls = [c for _, c in CODEX.normalize(p)]
    names = [(c["tool_name"], os.path.basename(c["tool_input"]["file_path"])) for c in calls]
    assert names == [("Edit", "app.py"), ("Write", "new.md"), ("Edit", "old.txt"), ("Edit", "move_me.py"),
                     ("Edit", "moved.py")]   # the journal file itself is never gated
    assert calls[0]["tool_input"]["content"] == "    return 2"
    assert all(c["session_id"] == "s1" and c["cwd"] == "/repo" for c in calls)


def test_codex_apply_patch_as_shell_argv():
    p = dict(CODEX_BASH, tool_input={"command": ["apply_patch", PATCH]})
    assert CODEX.normalize(p)[0][1]["tool_name"] == "Edit"


def test_codex_gate_note_mode_never_denies():
    core = FakeCore(GATE_DENY)
    out = CODEX.handle(CODEX_BASH, core=core)
    h = out["hookSpecificOutput"]
    assert "permissionDecision" not in h and "nothing was stopped" in h["additionalContext"]
    assert "reports_reads" not in core.calls[0][1]


def test_codex_gate_deny_mode(monkeypatch):
    monkeypatch.setenv("JOURNAL_GATE_CODEX", "deny")
    core = FakeCore(GATE_DENY)
    h = CODEX.handle(CODEX_BASH, core=core)["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny" and "JOURNALS GATE" in h["permissionDecisionReason"]
    assert core.calls[0][1]["reports_reads"] is True


def test_codex_other_stops_stay_stops_in_note_mode():
    h = CODEX.handle(CODEX_BASH, core=FakeCore(HARD_DENY))["hookSpecificOutput"]
    assert h == {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                 "permissionDecisionReason": HARD_DENY["permissionDecisionReason"]}


def test_codex_brief_as_pre_context():
    assert CODEX.handle(CODEX_BASH, core=FakeCore(BRIEF)) == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": BRIEF["additionalContext"]}}
    assert CODEX.render(CODEX.handle(CODEX_BASH, core=FakeCore())) == ""


def test_codex_post_journal_read_is_recorded():
    p = {"session_id": "s1", "cwd": "/repo", "hook_event_name": "PostToolUse", "turn_id": "t1",
         "tool_name": "mcp__journal__journal_handoff_brief", "tool_input": {"name": "X_JOURNAL.md"},
         "tool_response": {"content": [{"type": "text", "text": "# X\n## Handoff\nnext"}]}}
    [(flag, call)] = CODEX.normalize(p)
    assert flag == "" and call["tool_name"] == "mcp__journal__journal_handoff_brief"
    assert call["tool_input"] == {"journal_tool": "journal_handoff_brief", "args": {"name": "X_JOURNAL.md"},
                                  "text": "# X\n## Handoff\nnext", "ok": True}
    assert CODEX.handle(p, core=FakeCore()) is None
    bad = dict(p, tool_response={"isError": True, "content": []})
    assert CODEX.normalize(bad)[0][1]["tool_input"]["ok"] is False


def test_codex_post_shell_output_check():
    p = {"session_id": "s1", "cwd": "/repo", "hook_event_name": "PostToolUse", "tool_name": "Bash",
         "tool_input": {"command": "systemctl --failed"}, "tool_response": "unit-a.service failed to start, see logs"}
    [(flag, call)] = CODEX.normalize(p)
    assert flag == "--output" and call["output"].startswith("unit-a.service")
    out = CODEX.handle(p, core=FakeCore({"additionalContext": "the owner already said"}))
    assert out == {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "the owner already said"}}


def test_codex_prompt_session_stop():
    pr = {"session_id": "s1", "cwd": "/repo", "hook_event_name": "UserPromptSubmit", "turn_id": "t1",
          "prompt": "fix the checkout page"}
    assert CODEX.normalize(pr) == [("--prompt", {"hook_event_name": "UserPromptSubmit",
                                                 "prompt": "fix the checkout page", "session_id": "s1",
                                                 "cwd": "/repo"})]
    assert CODEX.handle(pr, core=FakeCore({"additionalContext": "MAP"})) == {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "MAP"}}
    ss = {"session_id": "s1", "cwd": "/repo", "hook_event_name": "SessionStart", "source": "startup"}
    h = CODEX.handle(ss, core=FakeCore())["hookSpecificOutput"]
    assert h["hookEventName"] == "SessionStart" and h["additionalContext"].startswith("JOURNALS (one brain)")
    st = {"session_id": "s1", "cwd": "/repo", "hook_event_name": "Stop", "turn_id": "t1",
          "stop_hook_active": False, "last_assistant_message": "Done, I shipped it."}
    core = FakeCore({"block": "That repeats a rejected plan."})
    assert CODEX.handle(st, core=core) == {"decision": "block", "reason": "That repeats a rejected plan."}
    assert core.calls[0] == ("--stop", {"hook_event_name": "Stop", "reply": "Done, I shipped it.",
                                        "stop_hook_active": False, "session_id": "s1", "cwd": "/repo"})
    assert CODEX.handle(dict(st, last_assistant_message=None), core=FakeCore()) is None


# ---- Copilot (https://docs.github.com/en/copilot/reference/hooks-reference,
#      https://code.visualstudio.com/docs/agent-customization/hooks) -------------------------------------------------

def test_copilot_camelcase_payload():
    p = {"timestamp": 1762800000000, "cwd": "/w", "sessionId": "c1", "toolName": "bash",
         "toolArgs": json.dumps({"command": "cat src/app.py", "description": "show it"})}
    assert COPILOT.normalize(p, "preToolUse") == [("", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                        "tool_input": {"command": "cat src/app.py",
                                                                       "description": "show it"},
                                                        "session_id": "c1", "cwd": "/w"})]


def test_copilot_pascalcase_edit_and_vscode_names():
    p = {"hook_event_name": "PreToolUse", "session_id": "p1", "timestamp": "2026-11-10T20:00:00Z", "cwd": "/w",
         "tool_name": "edit", "tool_input": {"path": "src/a.py", "old_str": "x", "new_str": "y"}}
    [(_, c)] = COPILOT.normalize(p)
    assert c["tool_name"] == "Edit" and c["tool_input"] == {"file_path": os.path.normpath("/w/src/a.py"),
                                                            "content": "y"}
    vs = {"hook_event_name": "PreToolUse", "session_id": "p1", "cwd": "/w", "tool_name": "create_file",
          "tool_input": {"filePath": "/w/b.py", "content": "print(1)"}}
    assert COPILOT.normalize(vs)[0][1]["tool_name"] == "Write"
    term = {"toolName": "runInTerminal", "toolArgs": {"command": "npm test"}, "sessionId": "p1", "cwd": "/w"}
    assert COPILOT.normalize(term, "preToolUse")[0][1]["tool_input"]["command"] == "npm test"


def test_copilot_context_rides_on_post_tool_use():
    pre = {"toolName": "view", "toolArgs": {"path": "/w/src/a.py"}, "sessionId": "q1", "cwd": "/w"}
    out = COPILOT.handle(pre, "preToolUse", core=FakeCore(BRIEF))
    assert out is None and COPILOT.render(out) == "{}"
    post = dict(pre, toolResult={"resultType": "success", "textResultForLlm": "file text"})
    assert COPILOT.handle(post, "postToolUse", core=FakeCore()) == {"additionalContext": BRIEF["additionalContext"]}
    assert COPILOT.handle(post, "postToolUse", core=FakeCore()) is None   # delivered once


def test_copilot_deny_is_flat():
    p = {"toolName": "bash", "toolArgs": {"command": "rm -rf build"}, "sessionId": "q2", "cwd": "/w"}
    assert COPILOT.handle(p, "preToolUse", core=FakeCore(HARD_DENY)) == {
        "permissionDecision": "deny", "permissionDecisionReason": HARD_DENY["permissionDecisionReason"]}
    soft = COPILOT.handle(p, "preToolUse", core=FakeCore(GATE_DENY))
    assert soft is None   # note mode: the gate stop became context, queued for postToolUse


def test_copilot_deny_mode_brief_rides_on_one_deny(monkeypatch):
    monkeypatch.setenv("JOURNAL_GATE_COPILOT", "deny")
    p = {"toolName": "edit", "toolArgs": {"path": "/w/a.py", "new_str": "y"}, "sessionId": "q3", "cwd": "/w"}
    out = COPILOT.handle(p, "preToolUse", core=FakeCore(BRIEF))
    assert out["permissionDecision"] == "deny" and "JOURNAL BRIEF for" in out["permissionDecisionReason"]


def test_copilot_prompt_map_waits_for_first_tool():
    pr = {"timestamp": 1, "cwd": "/w", "sessionId": "q4", "prompt": "the checkout page"}
    core = FakeCore({"additionalContext": "MAP of checkout"})
    assert COPILOT.handle(pr, "userPromptSubmitted", core=core) is None
    assert core.calls[0][0] == "--prompt" and core.calls[0][1]["prompt"] == "the checkout page"
    post = {"toolName": "bash", "toolArgs": {"command": "ls"}, "sessionId": "q4", "cwd": "/w",
            "toolResult": {"resultType": "success", "textResultForLlm": "a"}}
    assert COPILOT.handle(post, "postToolUse", core=FakeCore()) == {"additionalContext": "MAP of checkout"}


def test_copilot_session_start():
    ss = {"sessionId": "q5", "timestamp": 1, "cwd": "/w", "source": "new", "initialPrompt": "work on billing"}
    core = FakeCore({"additionalContext": "MAP of billing"})
    out = COPILOT.handle(ss, "sessionStart", core=core)
    assert out["additionalContext"].startswith("JOURNALS (one brain)") and out["additionalContext"].endswith(
        "MAP of billing")
    assert core.calls[0][1]["prompt"] == "work on billing"


# ---- Cursor (https://cursor.com/docs/hooks) ----------------------------------------------------------------------

CURSOR_COMMON = {"conversation_id": "k1", "generation_id": "g1", "model": "auto", "cursor_version": "2.0",
                 "workspace_roots": ["/project"], "user_email": None, "transcript_path": None}


def test_cursor_shell_doc_sample():
    p = dict(CURSOR_COMMON, hook_event_name="preToolUse", tool_name="Shell",
             tool_input={"command": "npm install", "working_directory": "/project"}, tool_use_id="abc123",
             cwd="/project")
    assert CURSOR.normalize(p) == [("", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "npm install", "description": ""},
                                         "session_id": "k1", "cwd": "/project"})]


def test_cursor_write_and_read():
    w = dict(CURSOR_COMMON, hook_event_name="preToolUse", tool_name="Write",
             tool_input={"file_path": "src/a.ts", "contents": "export const a = 1"})
    [(_, c)] = CURSOR.normalize(w)
    assert c["tool_name"] == "Write" and c["tool_input"] == {"file_path": os.path.normpath("/project/src/a.ts"),
                                                             "content": "export const a = 1"}
    r = dict(CURSOR_COMMON, hook_event_name="preToolUse", tool_name="Read", tool_input={"file_path": "/project/b.ts"})
    assert CURSOR.normalize(r)[0][1]["tool_input"] == {"paths": ["/project/b.ts"]}
    rj = dict(r, tool_input={"file_path": "/project/APP_JOURNAL.md"})
    assert CURSOR.normalize(rj) == []   # reading a journal is never gated


def test_cursor_output_shapes():
    p = dict(CURSOR_COMMON, hook_event_name="preToolUse", tool_name="Shell", tool_input={"command": "rm x"})
    d = CURSOR.handle(p, core=FakeCore(HARD_DENY))
    assert d["permission"] == "deny" and d["agent_message"] == HARD_DENY["permissionDecisionReason"]
    assert set(d) == {"permission", "agent_message", "user_message"}
    assert CURSOR.handle(p, core=FakeCore(BRIEF)) == {"additional_context": BRIEF["additionalContext"]}
    soft = CURSOR.handle(p, core=FakeCore(GATE_DENY))
    assert set(soft) == {"additional_context"} and "nothing was stopped" in soft["additional_context"]
    assert CURSOR.render(CURSOR.handle(p, core=FakeCore())) == "{}"


def test_cursor_prompt_map_rides_on_next_pre_tool_use():
    pr = dict(CURSOR_COMMON, hook_event_name="beforeSubmitPrompt", prompt="the invoice job", attachments=[])
    assert CURSOR.handle(pr, core=FakeCore({"additionalContext": "MAP of invoice"})) == {"continue": True}
    pre = dict(CURSOR_COMMON, hook_event_name="preToolUse", tool_name="Shell", tool_input={"command": "ls"})
    assert CURSOR.handle(pre, core=FakeCore()) == {"additional_context": "MAP of invoice"}
    assert CURSOR.handle(pre, core=FakeCore()) is None


def test_cursor_reply_then_stop():
    CURSOR.handle(dict(CURSOR_COMMON, hook_event_name="afterAgentResponse", text="All done, deployed."),
                  core=FakeCore())
    st = dict(CURSOR_COMMON, hook_event_name="stop", status="completed", loop_count=0)
    core = FakeCore({"block": "Say what you did not check."})
    assert CURSOR.handle(st, core=core) == {"followup_message": "Say what you did not check."}
    assert core.calls[0][1]["reply"] == "All done, deployed." and core.calls[0][1]["stop_hook_active"] is False
    assert CURSOR.handle(dict(st, status="aborted"), core=FakeCore({"block": "x"})) is None


def test_cursor_post_journal_reads_recorded():
    p = dict(CURSOR_COMMON, hook_event_name="postToolUse", tool_name="MCP:journal_search",
             tool_input={"query": "billing"}, duration=40,
             tool_output=json.dumps({"content": [{"type": "text", "text": "{\"matches\": []}"}]}))
    [(flag, c)] = CURSOR.normalize(p)
    assert flag == "" and c["tool_input"]["journal_tool"] == "journal_search"
    assert c["tool_input"]["text"] == "{\"matches\": []}" and c["tool_input"]["ok"] is True
    r = dict(CURSOR_COMMON, hook_event_name="postToolUse", tool_name="Read",
             tool_input={"file_path": "/project/APP_JOURNAL.md"}, tool_output="{}")
    assert CURSOR.normalize(r)[0][1]["tool_input"] == {"journal_read": "/project/APP_JOURNAL.md", "ok": True}


# ---- entry point -----------------------------------------------------------------------------------------------

def test_run_never_fails_closed(capsys):
    assert run.main(["quick_hook.py", "--app", "copilot", "--event", "preToolUse"], stdin_text="not json") == 0
    assert capsys.readouterr().out.strip() == "{}"
    assert run.main(["quick_hook.py", "--app", "nope"], stdin_text="{}") == 0
    assert capsys.readouterr().out.strip() == "{}"
    assert run.main(["quick_hook.py", "--app", "codex"], stdin_text="{}") == 0
    assert capsys.readouterr().out == ""


# ---- real core, end to end (light: a read of a temporary project) -------------------------------------------------

def _project(tmp_path):
    proj = tmp_path / "shopproj"
    (proj / "src").mkdir(parents=True)
    (proj / "SHOPPROJ_JOURNAL.md").write_text("# Shop\n\n## Handoff\nUse the billing module, never a new script.\n\n"
                                              "## 2026-11-10 10:00 [ship] billing\nbody\n", encoding="utf-8")
    f = proj / "src" / "app.py"
    f.write_text("x = 1\n", encoding="utf-8")
    return proj, str(f)


def _env_for(home):
    env = dict(os.environ, JOURNAL_HOME=str(home), JOURNAL_AUTOCOMPILE="off", JOURNAL_MEANING_OFF="1",
               JOURNAL_JUDGE="off", PYTHONIOENCODING="utf-8")
    for app in ("CODEX", "COPILOT", "CURSOR"):
        env.pop(f"JOURNAL_GATE_{app}", None)
    return env


def _hook(args, payload, home):
    r = subprocess.run([sys.executable, str(ROOT / "quick_hook.py")] + args, input=json.dumps(payload),
                       capture_output=True, text=True, encoding="utf-8", env=_env_for(home), timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_e2e_cursor_read_gets_brief(tmp_path):
    proj, f = _project(tmp_path)
    p = dict(CURSOR_COMMON, workspace_roots=[str(proj)], hook_event_name="preToolUse", tool_name="Read",
             tool_input={"file_path": f}, cwd=str(proj))
    out = json.loads(_hook(["--app", "cursor"], p, tmp_path / "home"))
    assert "permission" not in out
    assert "JOURNAL BRIEF for project" in out["additional_context"]
    assert "Use the billing module" in out["additional_context"]


def test_e2e_copilot_brief_after_tool(tmp_path):
    proj, f = _project(tmp_path)
    pre = {"hook_event_name": "PreToolUse", "session_id": "e2e-cp", "cwd": str(proj), "tool_name": "view",
           "tool_input": {"path": f}}
    assert json.loads(_hook(["--app", "copilot", "--event", "PreToolUse"], pre, tmp_path / "home")) == {}
    post = dict(pre, hook_event_name="PostToolUse", tool_result={"resultType": "success", "textResultForLlm": "x"})
    out = json.loads(_hook(["--app", "copilot", "--event", "PostToolUse"], post, tmp_path / "home"))
    assert "JOURNAL BRIEF for project" in out["additionalContext"]


def test_no_app_output_unchanged(tmp_path, monkeypatch, capsys):
    """quick_hook.py without --app: the script prints exactly what main() prints (the adapter branch is skipped)."""
    proj, f = _project(tmp_path)
    call = {"tool_name": "Read", "tool_input": {"paths": [f]}, "session_id": "same", "cwd": str(proj)}
    via_script = _hook([], call, tmp_path / "home_a")
    (tmp_path / "home_b").mkdir()
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path / "home_b"))
    monkeypatch.setenv("JOURNAL_AUTOCOMPILE", "off")
    import quick_hook
    monkeypatch.setattr(sys, "argv", ["quick_hook.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(call)))
    quick_hook.main()
    direct = capsys.readouterr().out
    assert via_script == direct
    h = json.loads(via_script)["hookSpecificOutput"]
    assert h["hookEventName"] == "PreToolUse" and "JOURNAL BRIEF for project" in h["additionalContext"]


def test_no_app_never_loads_adapters(tmp_path):
    code = ("import io, runpy, sys\n"
            "sys.argv = ['quick_hook.py']\n"
            "sys.stdin = io.StringIO('{}')\n"
            f"runpy.run_path({str(ROOT / 'quick_hook.py')!r}, run_name='__main__')\n"
            "print('LOADED' if any(m == 'adapters' or m.startswith('adapters.') for m in sys.modules) else 'CLEAN')\n")
    (tmp_path / "home").mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=_env_for(tmp_path / "home"),
                       cwd=str(ROOT), timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "CLEAN"
