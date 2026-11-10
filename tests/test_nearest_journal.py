"""Nearest journal (nearestjournal.py): the first touch of a file no Brain map row names delivers the brief of the
journal in its own project folder.

Regression for 2026-11-10 (Codex live test on the box): a project folder held DEMO_JOURNAL.md and notes.txt, no Brain
map; the AI's first apply_patch of notes.txt got an EMPTY PreToolUse answer. Buyers mostly have exactly that layout.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="journal-nearest-test-"))
_ROOT = _TMP / "root"
os.environ["JOURNAL_HOME"] = str(_TMP / "home")
os.environ["JOURNAL_ROOTS"] = str(_ROOT)
os.environ["JOURNAL_INCLUDE_VAULT_PATH"] = str(_TMP / "vault_names.json")
os.environ.pop("JOURNAL_EXTRA_DOCS", None)
CORE = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


X_JOURNAL = ("# X JOURNAL\n\n## Current state\n- notes.txt holds the launch notes, format A.\n\n"
             "## Handoff\nKeep every note in format A, never a second notes file.\n\n"
             "## 2026-11-10 10:00 [ship] notes format A\nbody\n")
_write(_ROOT / "OPS" / "OPS_JOURNAL.md", """# OPS JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Billing code | invoice, billing.py | Billing desk | OPS/BILLING_JOURNAL.md | message billing |
""")
_write(_ROOT / "OPS" / "BILLING_JOURNAL.md", "# BILLING JOURNAL\n\n## Handoff for next session\n- [ ] retry failed invoices\n")
_write(_ROOT / "proj" / "X_JOURNAL.md", X_JOURNAL)
A = _write(_ROOT / "proj" / "a.txt")
C = _write(_ROOT / "proj" / "sub" / "c.txt")
BILL = _write(_ROOT / "proj" / "billing.py")
LOOSE = _write(_ROOT / "loose" / "b.txt")

sys.path.insert(0, str(CORE))
import server as _server  # noqa: E402
import quickmap  # noqa: E402
import nearestjournal as nj  # noqa: E402

_server._index_refresh_internal()


@pytest.fixture(autouse=True)
def _own_index():
    """One server.py per pytest run: its index lives in the home of the first test file that imported it, and other
    test files index their own roots into it in between. The hook side (unitmap, quick_rows.json) reads the index of
    JOURNAL_HOME, as on a real machine, so each test here points the server at this file's home, indexes this
    file's roots, and puts the server back after."""
    saved = (_server._HOME, _server._DB, _server._CONFIG, _server._SCHEMA_READY)
    saved_env = {k: os.environ.get(k) for k in ("JOURNAL_HOME", "JOURNAL_ROOTS", "JOURNAL_AUTOCOMPILE")}
    home = _TMP / "own_home"  # never the home server.py was first imported with: that index is shared by every test file
    home.mkdir(parents=True, exist_ok=True)
    _server._HOME, _server._DB, _server._CONFIG, _server._SCHEMA_READY = home, home / "index.sqlite", home / "config.toml", False
    _env()
    _server._index_refresh_internal()
    yield
    _server._HOME, _server._DB, _server._CONFIG, _server._SCHEMA_READY = saved
    for k, v in saved_env.items():  # the next test file must find its own journals, not this file's
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:  # cached root names belong to this file's roots, not the next file's
        import quickmap as _qm
        _qm._ROOT_NAMES = None
    except Exception:
        pass


def _env():
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "own_home"), str(_ROOT)


def _edit(path, sid: str, cwd: str = "") -> dict:
    _env()
    call = {"session_id": sid, "reports_reads": True, "tool_name": "Edit", "cwd": cwd,
            "tool_input": {"file_path": str(path)}}
    buf = io.StringIO()
    with redirect_stdout(buf):
        quickmap.quick_hook(call)
    return json.loads(buf.getvalue()) if buf.getvalue().strip() else {}


# ---- (a) to (d): the edit hook ------------------------------------------------------------------------------------

def test_a_first_edit_delivers_the_nearest_journal_brief():
    h = _edit(A, "nj-a")["hookSpecificOutput"]
    assert "permissionDecision" not in h
    ctx = h["additionalContext"]
    assert 'JOURNAL BRIEF for project "proj" (X_JOURNAL.md)' in ctx
    assert "never a second notes file" in ctx and "format A" in ctx


def test_b_second_touch_same_session_does_not_repeat():
    assert "JOURNAL BRIEF" in json.dumps(_edit(A, "nj-b"))
    assert "JOURNAL BRIEF" not in json.dumps(_edit(A, "nj-b"))
    assert "JOURNAL BRIEF" not in json.dumps(_edit(C, "nj-b"))  # another file of the same project
    assert "JOURNAL BRIEF" in json.dumps(_edit(C, "nj-b-other"))  # another session gets it


def test_c_brain_map_row_wins_over_the_nearest_journal():
    out = json.dumps(_edit(BILL, "nj-c"))
    assert "Billing desk" in out and "retry failed invoices" in out
    assert "X_JOURNAL.md" not in out


def test_d_file_outside_any_project_gets_nothing():
    assert _edit(LOOSE, "nj-d") == {}
    elsewhere = _write(_TMP / "elsewhere" / "p2" / "file.txt")
    _write(_TMP / "elsewhere" / "p2" / "P2_JOURNAL.md", X_JOURNAL)
    assert _edit(elsewhere, "nj-d2", cwd=str(_ROOT)) == {}  # outside every root and outside the working folder


def test_outside_the_roots_the_working_folder_is_the_root():
    proj = _TMP / "codexproj"
    f = _write(proj / "notes.txt")
    _write(proj / "DEMO_JOURNAL.md", X_JOURNAL)
    ctx = _edit(f, "nj-cwd", cwd=str(proj))["hookSpecificOutput"]["additionalContext"]
    assert 'JOURNAL BRIEF for project "codexproj" (DEMO_JOURNAL.md)' in ctx


# ---- the rule, on find() --------------------------------------------------------------------------------------------

def _roots(monkeypatch, root: Path):
    monkeypatch.setenv("JOURNAL_ROOTS", str(root))


def test_root_with_several_journals_is_a_workspace(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    _write(tmp_path / "A_JOURNAL.md", X_JOURNAL)
    _write(tmp_path / "B_JOURNAL.md", X_JOURNAL)
    assert nj.find(str(_write(tmp_path / "top.txt"))) is None
    assert nj.find(str(_write(tmp_path / "tool" / "x.py"))) is None
    _write(tmp_path / "tool" / "TOOL_JOURNAL.md", X_JOURNAL)
    assert nj.find(str(tmp_path / "tool" / "x.py"))[1] == ["TOOL_JOURNAL.md"]


def test_root_with_one_journal_is_one_project(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    _write(tmp_path / "SHOP_JOURNAL.md", X_JOURNAL)
    assert nj.find(str(_write(tmp_path / "src" / "deep" / "f.ts")))[1] == ["SHOP_JOURNAL.md"]
    assert nj.find(str(_write(tmp_path / "f.ts")))[1] == ["SHOP_JOURNAL.md"]


def test_never_above_the_root(monkeypatch, tmp_path):
    _write(tmp_path / "PARENT_JOURNAL.md", X_JOURNAL)
    _roots(monkeypatch, tmp_path / "inner")
    assert nj.find(str(_write(tmp_path / "inner" / "x" / "f.py"))) is None


def test_folder_with_many_journals_maps_nothing(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    for i in range(6):
        _write(tmp_path / "ws" / f"P{i}_JOURNAL.md", X_JOURNAL)
    assert nj.find(str(_write(tmp_path / "ws" / "f.py"))) is None


def test_archives_drafts_fragments_and_worktrees_are_not_journals(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    _write(tmp_path / "p" / "X_JOURNAL_2026-07.md", X_JOURNAL)
    _write(tmp_path / "p" / "_peers_journal_entry.md", X_JOURNAL)
    _write(tmp_path / "p" / "X_journal_section.md", X_JOURNAL)
    _write(tmp_path / "p" / "JOURNAL_MARKETPLACE_CATALOG.md", X_JOURNAL)
    _write(tmp_path / "p" / "_archive" / "OLD_JOURNAL.md", X_JOURNAL)
    _write(tmp_path / "site-wt-perf" / "SITE_JOURNAL.md", X_JOURNAL)
    assert nj.find(str(_write(tmp_path / "p" / "f.py"))) is None
    assert nj.find(str(_write(tmp_path / "p" / "_archive" / "f.py"))) is None
    assert nj.find(str(_write(tmp_path / "site-wt-perf" / "src" / "a.tsx"))) is None
    _write(tmp_path / "p" / "SOCIAL_JOURNAL_USER.md", X_JOURNAL)
    assert nj.find(str(tmp_path / "p" / "f.py"))[1] == ["SOCIAL_JOURNAL_USER.md"]


def test_a_container_of_many_tools_cuts_the_walk(monkeypatch, tmp_path):
    """TOOLS HUB/servers/mail-tool/x.py is not HUB_JOURNAL.md's piece (same rule as reads)."""
    _roots(monkeypatch, tmp_path)
    hub = tmp_path / "TOOLS HUB"
    _write(hub / "HUB_JOURNAL.md", X_JOURNAL)
    for t in ("mail-tool", "keys-tool", "search-tool", "journal-mcp"):
        _write(hub / "servers" / t / "server.py")
    assert nj.find(str(hub / "servers" / "mail-tool" / "server.py")) is None
    assert nj.find(str(hub / "servers" / "journal-mcp" / "server.py"))[1] == ["HUB_JOURNAL.md"]
    assert nj.find(str(_write(hub / "notes" / "x.md")))[1] == ["HUB_JOURNAL.md"]


def test_a_small_monorepo_stays_one_project(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    _write(tmp_path / "shop" / "SHOP_JOURNAL.md", X_JOURNAL)
    f = _write(tmp_path / "shop" / "apps" / "web" / "src" / "page.tsx")
    _write(tmp_path / "shop" / "apps" / "api" / "main.py")
    assert nj.find(str(f))[1] == ["SHOP_JOURNAL.md"]


# ---- (e) the Codex adapter path -------------------------------------------------------------------------------------

def test_e_codex_apply_patch_gets_the_brief():
    _env()
    patch = "*** Begin Patch\n*** Update File: a.txt\n@@\n-x\n+y\n*** End Patch"
    payload = {"session_id": "nj-codex", "turn_id": "t1", "cwd": str(_ROOT / "proj"), "hook_event_name": "PreToolUse",
               "model": "codex-model", "tool_name": "apply_patch", "tool_use_id": "u1",
               "tool_input": {"command": patch}, "permission_mode": "default"}
    env = dict(os.environ, JOURNAL_HOME=str(_TMP / "home"), JOURNAL_ROOTS=str(_ROOT), JOURNAL_AUTOCOMPILE="off",
               JOURNAL_MEANING_OFF="1", JOURNAL_JUDGE="off", PYTHONIOENCODING="utf-8")
    env.pop("JOURNAL_GATE_CODEX", None)
    r = subprocess.run([sys.executable, str(CORE / "quick_hook.py"), "--app", "codex"], input=json.dumps(payload),
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    h = json.loads(r.stdout)["hookSpecificOutput"]
    assert "permissionDecision" not in h
    assert 'JOURNAL BRIEF for project "proj" (X_JOURNAL.md)' in h["additionalContext"]
    assert "never a second notes file" in h["additionalContext"]
