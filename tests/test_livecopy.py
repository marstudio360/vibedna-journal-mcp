"""Wrong-copy path check (livecopy.py). Real case 2026-10-28: Social Engine code imported from the old copy in
/home/deploy/social-engine while the live install is /home/deploy/.social-engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import livecopy  # noqa: E402

# Lines as the journals wrote them (SOCIAL_SYSTEM_JOURNAL_USER, AI_TEAM_JOURNAL, MAPLEWORKS_JOURNAL).
JOURNAL = "\n".join([
    "X LANE: FIRST REPLY WITH THE LINK (Social Engine commit ecfca60, deployed to gpubox /home/deploy/.social-engine/server.py)",
    "product 4c68a00 deployed to /home/deploy/.social-engine (server 5d0ea8dc, lane_runner md5 ok)",
    "deploy server.py to /home/deploy/.social-engine, load the linkedin config",
    "SB_HOME=/home/deploy/.social-engine is the live install for every lane",
    "cron: cd /home/deploy/.social-engine && /home/deploy/social-engine/venv/bin/python lane_runner.py",
    "anchor on ^/home/deploy/social-engine/venv/bin/python (cron line)",
    "crontab runs /home/deploy/social-engine/venv/bin/python for the drip runner",
    "queue at /home/deploy/.social-engine/engage/mapleworks.json",
])
IDX = livecopy.scan_text(JOURNAL)


def call(cmd, files=""):
    return {"tool_name": "Bash", "tool_input": {"command": cmd + ("\n" + files if files else "")}}


def test_old_copy_import_is_stopped_once():
    script = 'import sys\nsys.path.insert(0, "/home/deploy/social-engine")\nimport server as sb\n'
    c = call("ssh gpubox 'cd /home/deploy/social-engine && timeout 120 venv/bin/python /tmp/xrel.py'", script)
    seen = {}
    r = livecopy.check(c, seen, IDX)
    assert r and "WRONG COPY" in r["deny"] and "/home/deploy/.social-engine" in r["deny"]
    assert livecopy.check(c, seen, IDX) is None   # the retry passes


def test_live_install_with_the_venv_never_stops():
    c = call("ssh gpubox 'cd /home/deploy/.social-engine && SB_HOME=$PWD "
             "/home/deploy/social-engine/venv/bin/python -c 1'")
    assert livecopy.check(c, {}, IDX) is None


def test_only_the_venv_of_the_old_folder_never_stops():
    c = call("ssh gpubox '/home/deploy/social-engine/venv/bin/python -m pip list'")
    assert livecopy.check(c, {}, IDX) is None


def test_unrelated_server_paths_never_stop():
    for cmd in ("ssh gpubox 'ls /data/appuser-out/now/shopsite'", "ssh gpubox 'python3 /opt/studio-helper/browser.py tabs'",
                "ssh gpubox 'cat /home/appuser/journal-mcp/server.py'"):
        assert livecopy.check(call(cmd), {}, IDX) is None


def test_reads_and_edits_are_not_checked():
    assert livecopy.check({"tool_name": "Read", "tool_input": {"file_path": "/home/deploy/social-engine/x.py"}},
                          {}, IDX) is None


def test_two_loose_lines_are_not_enough():
    idx = livecopy.scan_text("\n".join([
        "Fix: product code deployed to /home/appuser/ai-team for the employees",
        "Run as: sudo -u siteship env AI_TEAM_HOME=/home/appuser/ai-team ./publish.sh",
        "the shared files live in /home/appuser/.ai-team (core.py, status.py, venv)",
    ]))
    c = call("ssh gpubox 'cd /home/appuser/.ai-team && venv/bin/python status.py'")
    assert livecopy.check(c, {}, idx) is None
