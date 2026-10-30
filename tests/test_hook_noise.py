"""Hook noise from real cases (2026-10-30, PC session).

1. Background agents' finished-task notices arrive as user prompts. The prompt map ran on the words of the agent's
   report and printed maps for Pigment, Starpair, HTMS, imagen and spring25, none of which the owner had named.
2. Four agent launches were stopped in one turn ("Stopped once") on owner rules and cards unrelated to the brief; the
   main session re-read journals that did not matter and relaunched. A brief keeps its map, it is never stopped.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import quick_hook  # noqa: E402

NOTICE = ("<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>\n<task-id>x</task-id>\n"
          "<result>Mined the failure history: Pigment SMTP, Starpair webhook, HTMS studio, SPRING25 ...</result>\n"
          "</task-notification>\n</system-reminder>")
# 2026-10-30: a peer session's reply mapped "business game", "mapleworks" and "shopsite" as if the owner had named them
PEER = ('<cross-session-message from="x" from-name="peer">Not me: this session works on the Mapleworks site and the '
        'Business Game</cross-session-message>')


def _run_main(call: dict, argv: list[str]) -> str:
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv = ["quick_hook.py", *argv]
    sys.stdin = io.StringIO(json.dumps(call))
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            quick_hook.main()
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return buf.getvalue()


def test_task_notification_is_not_an_owner_prompt():
    assert quick_hook.is_notification(NOTICE)
    assert quick_hook.is_notification(PEER)
    assert not quick_hook.is_notification("launch desk como va todo")
    assert _run_main({"prompt": NOTICE, "session_id": "noise-test"}, ["--prompt"]) == ""


def test_agent_launch_deny_becomes_context():
    deny = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "JOURNALS FOR WHAT YOU ARE ABOUT TO DO (\"x\"):\n- OWNER RULE: ...\n\n"
                                    "Stopped once: the same call passes on retry, and reading the journal named above "
                                    "opens every later call on it."}})
    h = json.loads(quick_hook._soft_for_agents(deny))["hookSpecificOutput"]
    assert "permissionDecision" not in h
    assert h["additionalContext"].startswith("JOURNALS FOR WHAT YOU ARE ABOUT TO DO")
    assert "Stopped once" not in h["additionalContext"]


def test_git_bookkeeping_is_not_an_action_to_map():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import quickmap
    real = ('cd "/c/x/journal-mcp" && git add quickmap.py tests/test_quick_map.py && git commit -q -m "Quick map: '
            'shows once; bare words (Active projects) are no state claim\n\nCo-Authored-By: C <n@x.com>" && '
            'git log --oneline -1')
    assert quickmap.git_only(real)
    assert quickmap.git_only("git status --short")
    assert not quickmap.git_only("git add x && rm -rf build")
    assert not quickmap.git_only("git push origin main")
    assert not quickmap.git_only("sed -i 's/a/b/' quickmap.py && git commit -am x")


def test_non_deny_output_is_untouched():
    note = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "map"}})
    assert quick_hook._soft_for_agents(note) == note
    assert quick_hook._soft_for_agents("") == ""
