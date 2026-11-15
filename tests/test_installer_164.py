"""1.6.4: the installer finds the claude command on Windows (a .cmd file), and names an older 'journal' entry and a
JOURNAL_ROOTS the hooks cannot see, without editing either. From a real Windows install of 1.6.3."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="journals-dna-164-"))


def _env(name: str) -> dict:
    """A fresh machine: an empty home folder, no JOURNAL_* setting, no claude command on the PATH."""
    home = _TMP / "homes" / name
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOURNAL_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8", PATH=str(Path(sys.executable).parent))
    return env


def _run(args: list, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(PKG), env=env, timeout=300)


def _snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_claude_command_is_found_and_run_when_it_is_a_cmd_file_on_windows(tmp_path):
    # a stand-in for that command line tool: it writes down what it was asked; on Windows it is a .cmd file, as the real one
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "calls.txt"
    script = fake / "fake_claude.py"
    script.write_text("import sys" + chr(10) + "a = sys.argv[1:]" + chr(10)
                      + "open(%r, 'a', encoding='utf-8').write(' '.join(a[:3]) + chr(10))" % str(log) + chr(10)
                      + "if a[:2] == ['mcp', 'get']: print('No MCP server found'); sys.exit(1)" + chr(10)
                      + "print(chr(0x2713) + ' ok'); sys.exit(0)" + chr(10), encoding="utf-8")
    env = _env("claude-cmd")
    if os.name == "nt":
        (fake / "claude.cmd").write_text('@"%s" "%s" %%*' % (sys.executable, script) + chr(13) + chr(10), encoding="utf-8")
        env["PATHEXT"] = ".CMD;.EXE;.BAT"
    else:
        launcher = fake / "claude"
        launcher.write_text("#!/bin/sh" + chr(10) + 'exec "%s" "%s" "$@"' % (sys.executable, script) + chr(10), encoding="utf-8")
        launcher.chmod(0o755)
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    r = _run(["install_mod.py", "--yes"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert "mcp add journal" in calls and "plugin marketplace add" in calls and "plugin install journals@journals-dna" in calls
    assert "Steps left for you" not in r.stdout and " said: " not in r.stdout


def test_an_older_journal_entry_and_a_roots_setting_the_hooks_cannot_see_are_named_and_never_edited():
    env = _env("older-entry")
    home = Path(env["HOME"])
    old = {"mcpServers": {"journal": {"command": "python", "args": [str(home / "old-journal" / "server.py")],
                                      "env": {"JOURNAL_ROOTS": str(home / "notes")}},
                          "other": {"command": "node", "args": ["x.js"]}}}
    (home / ".mcp.json").write_text(json.dumps(old, indent=2), encoding="utf-8")
    before = _snapshot(home)

    r = _run(["install_mod.py", "--dry-run"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Found from an earlier install" in r.stdout and str(home / ".mcp.json") in r.stdout
    assert "old-journal" in r.stdout and "claude mcp remove journal -s project" in r.stdout
    assert "JOURNAL_ROOTS" in r.stdout and "hooks never see a server entry" in r.stdout and "config.toml" in r.stdout
    assert _snapshot(home) == before   # named, never edited

    r = _run(["install_mod.py", "--yes"], env)
    assert r.returncode == 0 and "Still to fix from an earlier install" in r.stdout, r.stdout + r.stderr
    assert json.loads((home / ".mcp.json").read_text(encoding="utf-8")) == old
    conf = home / ".claude" / "settings.json"
    assert set(json.loads(conf.read_text(encoding="utf-8"))["env"]) == {"JOURNAL_MCP_DIR", "JOURNAL_PYTHON"}

    # the person does the two things it named: nothing is left to say
    data = json.loads(conf.read_text(encoding="utf-8"))
    data["env"]["JOURNAL_ROOTS"] = str(home / "notes")
    conf.write_text(json.dumps(data, indent=2), encoding="utf-8")
    del old["mcpServers"]["journal"]
    (home / ".mcp.json").write_text(json.dumps(old, indent=2), encoding="utf-8")
    r = _run(["install_mod.py", "--dry-run"], env)
    assert r.returncode == 0 and "Found from an earlier install" not in r.stdout, r.stdout + r.stderr

    # an entry that already runs THIS copy is fine wherever it is
    (home / ".mcp.json").write_text(json.dumps({"mcpServers": {"journal": {"command": sys.executable,
                                    "args": [str(PKG / "server.py")]}}}), encoding="utf-8")
    r = _run(["install_mod.py", "--dry-run"], env)
    assert r.returncode == 0 and "Found from an earlier install" not in r.stdout, r.stdout + r.stderr
