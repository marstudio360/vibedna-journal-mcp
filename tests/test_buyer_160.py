"""Journals DNA 1.6.0, the buyer's view of what is new, as on a fresh unzip: an empty home folder, no JOURNAL_* setting,
no index, no rules of your own.

- the default rules pack is on with no setup and stops a force push to main once (the same call again passes);
- JOURNAL_DEFAULT_RULES=off turns it off;
- a project folder with its own X_JOURNAL.md and no Brain map: the first edit of a file inside it carries the
  journal's brief (the nearest journal);
- the Codex adapter (quick_hook.py --app codex) gives the same brief on an apply_patch of that file;
- no file of the package carries a name of the vendor's own projects, people or machines.

Run: python -m pytest tests   (everything in temporary folders; your journals and your home folder are not touched)
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="journals-dna-160-"))

PROJECT = _TMP / "work" / "launchpad"
PROJECT.mkdir(parents=True)
(PROJECT / "X_JOURNAL.md").write_text(
    "# X JOURNAL\n\n## Current state\n- notes.txt holds the launch notes, format A.\n\n"
    "## Handoff\nKeep every note in format A, never a second notes file.\n\n"
    "## 2026-11-10 10:00 [ship] notes format A\nbody\n", encoding="utf-8")
(PROJECT / "notes.txt").write_text("x\n", encoding="utf-8")


def _env(name: str, **extra) -> dict:
    """A fresh machine: an empty home folder, no JOURNAL_* setting (the journal home is the default ~/.journal)."""
    home = _TMP / "homes" / name
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOURNAL_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    env.update(extra)
    return env


def _hook(payload: dict, env: dict, *flags) -> dict:
    r = subprocess.run([sys.executable, str(PKG / "quick_hook.py"), *flags], input=json.dumps(payload),
                       capture_output=True, text=True, encoding="utf-8", cwd=str(PROJECT), env=env, timeout=180)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    return json.loads(out.splitlines()[-1]).get("hookSpecificOutput", {}) if out else {}


def _bash(cmd: str, session: str) -> dict:
    return {"session_id": session, "reports_reads": True, "tool_name": "Bash", "cwd": str(PROJECT),
            "tool_input": {"command": cmd, "description": "push it"}}


def test_the_default_pack_is_on_with_no_setup_and_stops_a_force_push_to_main_once():
    env = _env("pack-on")
    call = _bash("git push --force origin main", "p1")
    first = _hook(call, env)
    assert first.get("permissionDecision") == "deny", first
    assert "default rule: force_push" in first["permissionDecisionReason"]
    assert "Force push to main caught" in first["permissionDecisionReason"]
    assert _hook(call, env).get("permissionDecision") != "deny"   # the same call again passes
    assert _hook(_bash("git push origin my-branch", "p1"), env).get("permissionDecision") != "deny"
    assert not (Path(env["HOME"]) / ".journal" / "compiled_rules.json").exists()   # no judge, nothing compiled


def test_journal_default_rules_off_turns_it_off():
    env = _env("pack-off", JOURNAL_DEFAULT_RULES="off")
    assert _hook(_bash("git push --force origin main", "o1"), env).get("permissionDecision") != "deny"


def test_the_first_edit_in_a_project_with_a_journal_carries_its_brief_without_a_brain_map():
    env = _env("nearest")
    call = {"session_id": "n1", "reports_reads": True, "tool_name": "Edit", "cwd": str(PROJECT),
            "tool_input": {"file_path": str(PROJECT / "notes.txt"), "old_string": "x", "new_string": "y"}}
    h = _hook(call, env)
    assert "permissionDecision" not in h, h
    ctx = h.get("additionalContext", "")
    assert 'JOURNAL BRIEF for project "launchpad" (X_JOURNAL.md)' in ctx, ctx
    assert "never a second notes file" in ctx
    assert "JOURNAL BRIEF" not in json.dumps(_hook(call, env))   # once per session


def test_the_codex_adapter_gives_the_same_brief_on_apply_patch():
    env = _env("codex")
    patch = "*** Begin Patch\n*** Update File: notes.txt\n@@\n-x\n+y\n*** End Patch"
    payload = {"session_id": "c1", "turn_id": "t1", "cwd": str(PROJECT), "hook_event_name": "PreToolUse",
               "model": "codex-model", "tool_name": "apply_patch", "tool_use_id": "u1",
               "tool_input": {"command": patch}, "permission_mode": "default"}
    h = _hook(payload, env, "--app", "codex")
    assert h.get("hookEventName") == "PreToolUse" and "permissionDecision" not in h, h
    assert 'JOURNAL BRIEF for project "launchpad" (X_JOURNAL.md)' in h["additionalContext"]
    assert "never a second notes file" in h["additionalContext"]


# The names of the vendor's own projects, people, machines and paths (the release audit's list), base64-encoded so
# this file does not carry them itself.
_NAMES_B64 = """
XGIoYWljb3xhbGNoZW15NGt8YXVyYWxbIF8tXT9hbGNoZW15fG1hcnN0dWRpb3xwcm9tb3NwbGl0fGl2eWZvbGxvd3x2ZW50dXJl
WyBfLV0/ZGVza3xwcmVkaWN0aW9uWyBfLV0/ZGVza3xhdG9taWt8aGV0em5lcnxtYXJpYW5vfG5hbm9tYXJjaGV8cGllcmluYXxt
YXJjaGVzb25pfHBpZXJpbn4xfHF3ZW5cdyp8cG9seW1hcmtldHx3ZWJsb29tfGRyZWFtc2NhcGV8cGl4ZWxmb3JnZXxmYXRob218
YXN0cmFkdWFsfGh2c218cGFsZXRvfHNlcmVuaXR5fGhpZ2hlclsgXy1dP3Zpc2lvbnxhZ2VuY2lhWyBfLV0/Y29udGVuaWRvfHZl
Y3RvcmNyYWZ0fGxpcWh1bnR8aW5zaWRlcjI1fGZhbTRldmVyfHVydWd1YXl8dHJhYmFqb3JlbW90b3xjdnllbnRyZXZpc3Rhc3xt
Y3Agc3R1ZGlvfG5hbm9bIF8tXXZpYmV8YWlbIF8tXWNvbXBhbnl8bWVtb3J5IG9wc3xtZW1vcnkgbWFwfG93bmVycyBtYXB8ZnJl
ZV9zaGlmdHxsdW1hfGh2WyBfLV0/Y2xpcGZhcm18Y2xpcGZhcm18YWRyYWRhcnxhZHNbIF8tXT9yYWRhcnxuYW4wbVx3KnxnZXRp
dnlmb2xsb3d8Y2hpcGZvcmdlfHNvY2lhbFsgXy1dP2F1dG9waWxvdHxhZHNib3R8NzJcLjFcLjEzMFwuNjV8MTAwXC4xMDhcLjQ5
XC4xMDV8MzhcLjI0N1wuMTkwXC4yNDh8aGVhdnlbIF8tXT9ydW58Y3JlYXRvclsgXy1dP3N0dWRpb3xjcmVhdGl2ZVsgXy1dP2h1
YnxlZmZlY3RjcmFmdHxqZXN0ZXJ8YmVhdVsgXy1dP25vcnRvbnxjb3JyZWN0aW9uc1sgXy1dam91cm5hbHx2aWJlZ2VufFx3K1sg
Xy1ddmRuYXxwcm9bIF8tXWV5ZXN8YXVkaW9bIF8tXWV2b3xib3hbIF8tXWRlcGxveXxmdW5uZWxbIF8tXXRyYWNrfHZlbnRhc1sg
Xy1dYWdyZXNpdmFzfHNoaXBcLnNofCg/LWk6dmliZWRuYS1zaXRlKXxnbWFpbFsgXy1dbWNwfGplc3RlclsgXy1dbWNwKVxifCg/
PD1cXG4pKD86YXN0cmFkdWFsfGh2WyBfLV0/Y2xpcGZhcm18YWljb3xhbGNoZW15NGspfEM6Wy9cXF1Vc2Vyc1svXFxdKFBpZXJp
bmF8UElFUklOKXwvaG9tZS8oYWljb3xhZG1pbmlzdHJhdG9yfG1hcmlhbm8pXGJ8RDpbL1xcXShIaXZlfE1hclN0dWRpb3xWaWJl
RE5BfG5wbS1nbG9iYWx8bnBtLWNhY2hlfHBpcC1jYWNoZXxwbGF5d3JpZ2h0LWJyb3dzZXJzfEF1cmFsKQ==
"""
NAMES = re.compile(base64.b64decode("".join(_NAMES_B64.split())).decode("utf-8"), re.I)
TEXT_EXT = {".py", ".md", ".json", ".ts", ".txt", ".toml", ".yaml", ".yml", ".sh", ".cfg", ""}


def test_no_file_of_the_package_carries_the_vendors_own_names():
    found = []
    for f in sorted(PKG.rglob("*")):
        rel = f.relative_to(PKG)
        if not f.is_file() or f.suffix.lower() not in TEXT_EXT or any(p.startswith(".") and p not in (".claude-plugin", ".github", ".cursor")
                                                                       or p == "__pycache__" for p in rel.parts[:-1]):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = NAMES.search(line)
            if m:
                found.append(f"{rel.as_posix()}:{i}: [{m.group(0)}]")
    assert not found, found[:20]
    assert NAMES.search("ssh " + "alchemy" + "4k uptime")   # the list is really read
