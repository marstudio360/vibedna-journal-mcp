"""Units (unitmap.py): a service, timer or cron script named in a command or its output brings the newest incident /
pause / kill switch entry about it and the line that a running timer is not proof the job works.

Regression for a real case: `systemctl list-timers | grep warmer` showed
pw-warmer@shopsite.timer firing; the session told the owner "Reddit comments running" while the warmer's journal had
the 2026-11-03 [incident] with the kill switch STOP.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="journal-unit-test-"))
_ROOT = _TMP / "root"
os.environ["JOURNAL_HOME"] = str(_TMP / "home")
os.environ["JOURNAL_ROOTS"] = str(_ROOT)
os.environ["JOURNAL_INCLUDE_VAULT_PATH"] = str(_TMP / "vault_names.json")
os.environ.pop("JOURNAL_EXTRA_DOCS", None)
CORE = Path(__file__).resolve().parents[1]

WARMER = _ROOT / "WARMER" / "PRODUCT_WARMER_JOURNAL.md"
WARMER.parent.mkdir(parents=True, exist_ok=True)
WARMER.write_text("""# PRODUCT WARMER JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Product warmer | warmer, pw-warmer | Warmer desk | WARMER/PRODUCT_WARMER_JOURNAL.md | lanes per brand |

## 2026-10-26 10:00 [ship] Shopsite Reddit + X LIVE
pw-warmer@shopsite.timer comments on Reddit every 2 hours.

## 2026-11-03 14:27 [incident] Reddit automated activity check on the brand account
Reddit flagged automated activity on the account. The pw-warmer lane for shopsite got the kill switch STOP file; the
timer keeps firing but every run exits with event=not_due.
""", encoding="utf-8")

LIST_TIMERS = """NEXT                        LEFT       LAST                        PASSED   UNIT                     ACTIVATES
Tue 2026-11-10 23:00:00 UTC 1h 58min   Tue 2026-11-10 21:00:00 UTC 2min ago pw-warmer@shopsite.timer  pw-warmer@shopsite.service
Wed 2026-11-11 00:00:00 UTC 2h 58min   Tue 2026-11-10 00:00:00 UTC 21h ago  logrotate.timer          logrotate.service

2 timers listed.
"""

sys.path.insert(0, str(CORE))
import server as _server  # noqa: E402
import quickmap  # noqa: E402
import unitmap  # noqa: E402

_server._index_refresh_internal()
quickmap._write_rows_cache()


@pytest.fixture(autouse=True)
def _own_index():
    """One server.py per pytest run: its index lives in the home of the first test file that imported it, and other
    test files index their own roots into it in between. The hook side (unitmap, quick_rows.json) reads the index of
    JOURNAL_HOME, as on a real machine, so each test here points the server at this file's home, indexes this
    file's roots (and the Brain map rows cache), and puts the server back after."""
    saved = (_server._HOME, _server._DB, _server._CONFIG, _server._SCHEMA_READY)
    saved_env = {k: os.environ.get(k) for k in ("JOURNAL_HOME", "JOURNAL_ROOTS", "JOURNAL_AUTOCOMPILE")}
    home = _TMP / "own_home"  # never the home server.py was first imported with: that index is shared by every test file
    home.mkdir(parents=True, exist_ok=True)
    _server._HOME, _server._DB, _server._CONFIG, _server._SCHEMA_READY = home, home / "index.sqlite", home / "config.toml", False
    _env()
    _server._index_refresh_internal()
    quickmap._write_rows_cache()
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
    os.environ["JOURNAL_AUTOCOMPILE"] = "off"


def _run(monkeypatch, capsys, args: list, call: dict) -> str:
    _env()
    import quick_hook
    monkeypatch.setattr(sys, "argv", ["quick_hook.py"] + args)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(call)))
    cwd = os.getcwd()
    try:
        quick_hook.main()
    finally:
        os.chdir(cwd)
    return capsys.readouterr().out


def test_units_in_output_and_cron_lines():
    got = unitmap.units_in(LIST_TIMERS + "\n*/30 * * * * /opt/warm/run_warmer.sh >> /var/log/w.log 2>&1\n")
    assert ("pw-warmer@shopsite.timer", "timer", "pw-warmer", "shopsite") in got
    assert ("pw-warmer@shopsite.service", "service", "pw-warmer", "shopsite") not in got  # same unit, once
    assert ("run_warmer.sh", "cron", "run_warmer", "") in got
    assert unitmap.units_in("journalctl -u journal-embed -n 20", command=True)[0][2] == "journal-embed"


def test_list_timers_output_shows_the_incident_and_the_log_line(monkeypatch, capsys):
    out = _run(monkeypatch, capsys, ["--output"], {"session_id": "u-out", "output": LIST_TIMERS})
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]  # ONE json document
    assert "pw-warmer@shopsite.timer" in ctx and 'piece "Product warmer"' in ctx
    assert "2026-11-03 14:27" in ctx and "kill switch STOP" in ctx
    assert "2026-10-26" not in ctx  # the old LIVE entry is not a state entry
    assert ("A running timer is not proof the job works: check its log (journalctl -u pw-warmer@shopsite.service -n 20) "
            "before saying it runs.") in ctx
    assert "logrotate" not in ctx
    again = _run(monkeypatch, capsys, ["--output"], {"session_id": "u-out", "output": LIST_TIMERS})
    assert "pw-warmer" not in again  # once per session per unit


def test_command_naming_the_unit_gets_the_note_before_it_runs(monkeypatch, capsys):
    call = {"session_id": "u-cmd", "tool_name": "Bash", "cwd": str(_ROOT),
            "tool_input": {"command": "journalctl -u pw-warmer@shopsite -n 20 --no-pager", "description": "warmer log"}}
    h = json.loads(_run(monkeypatch, capsys, [], call))["hookSpecificOutput"]
    assert "permissionDecision" not in h
    assert "2026-11-03 14:27" in h["additionalContext"]
    assert "journalctl -u pw-warmer@shopsite.service -n 20" in h["additionalContext"]


def test_newest_state_entry_wins():
    _env()
    with WARMER.open("a", encoding="utf-8") as fh:
        fh.write("\n## 2026-11-12 09:00 [resume] pw-warmer shopsite resumed\nSTOP removed after the owner's yes; the "
                 "pw-warmer lane for shopsite resumed at 2 comments a day.\n")
    _server._index_refresh_internal()
    st = unitmap.newest_state("pw-warmer", "shopsite", conn=quickmap._conn)
    assert st["when"].startswith("2026-11-12") and "resumed" in st["said"]


def test_unknown_units_say_nothing():
    _env()
    text, ids = unitmap.note("Wed 2026-11-11 00:00:00 UTC logrotate.timer logrotate.service apt-daily.timer", set(),
                             conn=quickmap._conn)
    assert text == "" and ids == set()
