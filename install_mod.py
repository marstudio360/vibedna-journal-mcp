#!/usr/bin/env python3
"""Journals DNA: your AI cannot skip your journal. One-command install for Claude Code.

    <venv python> install_mod.py              show each change, ask once, apply
    <venv python> install_mod.py --dry-run    print every change, write nothing
    <venv python> install_mod.py --yes        apply without asking
    <venv python> install_mod.py --uninstall  reverse it (MCP server entry, plugin, marketplace, the two settings keys)

What it does:
  1. registers the journal MCP server in Claude Code (user scope, name "journal"), run by this Python;
  2. adds the journals mod (a Claude Code plugin in ./mod) from a local marketplace folder, no account needed;
  3. writes two keys in the "env" block of ~/.claude/settings.json (JOURNAL_MCP_DIR, JOURNAL_PYTHON) so the mod
     finds this folder. A timestamped backup is written first and nothing else in the file is changed.
Your journals are never touched. Running it again changes nothing.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = (HERE / "VERSION").read_text(encoding="utf-8").strip() if (HERE / "VERSION").exists() else "?"
MARKETPLACE = "journals-dna"
PLUGIN = "journals"
MCP_NAME = "journal"
SETTINGS = Path.home() / ".claude" / "settings.json"
KEYS = {"JOURNAL_MCP_DIR": str(HERE), "JOURNAL_PYTHON": sys.executable}


def say(msg: str = "") -> None:
    print(msg, flush=True)


def run_claude(*args: str, dry: bool = False) -> tuple[int, str]:
    cmd = ["claude", *args]
    if dry:
        say("  would run: " + " ".join(f'"{a}"' if " " in a else a for a in cmd))
        return 0, ""
    # By its full path: on Windows the command is a .cmd file, which is not found by its bare name (WinError 2).
    cmd[0] = shutil.which("claude") or "claude"
    try:
        # Read as UTF-8, whatever the console's own code page: the command prints marks the Windows default cannot decode.
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def load_settings() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8") or "{}")
    except ValueError:
        say(f"Cannot read {SETTINGS} as JSON. Fix or move it, then run this again (nothing was changed).")
        sys.exit(1)


def write_settings(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak_journals_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(SETTINGS, backup)
        say(f"  backup: {backup}")
    SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def preflight() -> None:
    if sys.version_info < (3, 10):
        say("Python 3.10 or newer is needed. Install it, then run this again.")
        sys.exit(1)
    if not (HERE / "server.py").exists() or not (HERE / "quick_hook.py").exists():
        say("Run this from the unzipped Journals DNA folder (server.py and quick_hook.py must sit next to it).")
        sys.exit(1)
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError:   # missing, or a newer mcp without FastMCP: requirements.txt pins a working version
        say("The mcp package this tool needs is missing or too new for this Python:")
        say(f"  {sys.executable} -m pip install -r requirements.txt")
        say("Run that from this folder (inside your .venv), then run this again. Nothing was changed.")
        sys.exit(1)


HOOK_ENV = ("JOURNAL_ROOTS", "JOURNAL_HOME")   # where the journals and the index are: the server and the hooks must agree


def _same_file(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(os.path.expanduser(a))) == os.path.normcase(os.path.abspath(str(b)))
    except (OSError, ValueError):
        return False


def journal_entries() -> list[dict]:
    """Every server named 'journal' that Claude Code can read for this person: the project files (.mcp.json in the
    home folder and in this folder), the project blocks of ~/.claude.json and its user block. Read only.
    Claude Code uses a project entry before the user entry this installer adds, so an older copy named there keeps
    running in every session opened from that folder, with no notice (reported from a real Windows install of 1.6.3,
    where the install guide of an earlier version had put the entry in ~/.mcp.json)."""
    home, found, seen = Path.home(), [], set()

    def take(where: str, scope: str, folder: str, entry) -> None:
        if not isinstance(entry, dict):
            return
        args = [str(a) for a in (entry.get("args") or [])]
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        found.append({"where": where, "scope": scope, "folder": folder,
                      "runs": " ".join([str(entry.get("command") or ""), *args]).strip(),
                      "ours": any(_same_file(a, HERE / "server.py") for a in args),
                      "env": {k: str(env[k]) for k in HOOK_ENV if env.get(k)}})

    for folder in (home, Path.cwd()):
        f = folder / ".mcp.json"
        try:
            key = os.path.normcase(str(f.resolve()))
            if key in seen or not f.is_file():
                continue
            seen.add(key)
            take(str(f), "project", str(folder), (json.loads(f.read_text(encoding="utf-8")).get("mcpServers") or {}).get(MCP_NAME))
        except (OSError, ValueError, AttributeError):
            pass
    try:
        conf = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        take(str(home / ".claude.json"), "user", "", (conf.get("mcpServers") or {}).get(MCP_NAME))
        for folder, block in (conf.get("projects") or {}).items():
            if isinstance(block, dict):
                take(str(home / ".claude.json"), "local", str(folder), (block.get("mcpServers") or {}).get(MCP_NAME))
    except (OSError, ValueError, AttributeError):
        pass
    return found


def entry_notes(settings_env: dict) -> list[str]:
    """What is wrong with the 'journal' entries found, one text each, with what to do. Empty when nothing is."""
    notes = []
    for e in journal_entries():
        if not e["ours"]:
            if e["scope"] == "user":
                notes.append(f"an older '{MCP_NAME}' server is registered for your user ({e['where']}) and runs another copy: "
                             f"{e['runs']}. Remove it with  claude mcp remove {MCP_NAME} -s user  and run this installer again")
            else:
                notes.append(f"an older '{MCP_NAME}' server entry in {e['where']} ({e['scope']} scope, folder {e['folder']}) "
                             f"runs another copy: {e['runs']}. Claude Code uses it before the one this install adds, so in "
                             f"sessions opened from that folder the older copy keeps running. Remove it: run  claude mcp remove "
                             f"{MCP_NAME} -s {e['scope']}  from that folder (or delete the \"{MCP_NAME}\" entry in that file), "
                             f"then restart Claude Code")
        for k, v in e["env"].items():
            if str(settings_env.get(k) or "") != v:
                other = " (or list the folders as roots in ~/.journal/config.toml, which both read)" if k == "JOURNAL_ROOTS" else ""
                notes.append(f"the '{MCP_NAME}' entry in {e['where']} sets {k}={v}, and the env block of ~/.claude/settings.json "
                             f"does not. The mod's hooks never see a server entry: they run with that env block, so the hooks "
                             f"and the server would look at different folders. Add to the env block of "
                             f"~/.claude/settings.json:  \"{k}\": {json.dumps(v)}{other}")
    return notes


def mcp_registered() -> bool:
    code, out = run_claude("mcp", "get", MCP_NAME)
    return code == 0 and "server.py" in out


def install(dry: bool, yes: bool) -> int:
    preflight()
    have_claude = shutil.which("claude") is not None
    data = load_settings()
    env = dict(data.get("env") or {})
    todo = {k: v for k, v in KEYS.items() if env.get(k) != v}
    add_mcp = have_claude and not mcp_registered()
    mcp_cmd = ["mcp", "add", MCP_NAME, "-s", "user", "--", sys.executable, str(HERE / "server.py")]

    say(f"Journals DNA {VERSION}: your AI cannot skip your journal.")
    say("Changes:")
    for k, v in todo.items():
        say(f"  ~/.claude/settings.json env {k} = {v}")
    if not todo:
        say("  ~/.claude/settings.json already has both keys")
    if have_claude:
        say(f"  claude mcp add {MCP_NAME} (user scope) -> {HERE / 'server.py'}" if add_mcp
            else f"  the MCP server '{MCP_NAME}' is already registered")
        say(f"  claude plugin marketplace add {HERE / 'mod'}")
        say(f"  claude plugin install {PLUGIN}@{MARKETPLACE}")
    else:
        say("  (the claude command was not found: the three Claude Code steps are printed at the end)")
    notes = entry_notes({**env, **todo})
    if notes:
        say("Found from an earlier install, for you to fix (this installer does not edit these):")
        for n in notes:
            say("  - " + n)
    if dry:
        say("\nDry run: nothing written.")
        if have_claude:
            if add_mcp:
                run_claude(*mcp_cmd, dry=True)
            run_claude("plugin", "marketplace", "add", str(HERE / "mod"), dry=True)
            run_claude("plugin", "install", f"{PLUGIN}@{MARKETPLACE}", dry=True)
        return 0
    if not yes and input("Apply these changes? [y/N] ").strip().lower() not in ("y", "yes"):
        say("Nothing changed.")
        return 0

    if todo:
        env.update(todo)
        data["env"] = env
        write_settings(data)
    left = []
    if have_claude:
        if add_mcp:
            code, out = run_claude(*mcp_cmd)
            if code != 0 and "already" not in out.lower():
                say("  mcp add said: " + out[:200])
                left.append(" ".join(["claude", *mcp_cmd]))
        code, out = run_claude("plugin", "marketplace", "add", str(HERE / "mod"))
        if code != 0 and "already" not in out.lower():
            say("  marketplace add said: " + out[:200])
        code, out = run_claude("plugin", "install", f"{PLUGIN}@{MARKETPLACE}")
        if code != 0 and "already" not in out.lower():
            say("  plugin install said: " + out[:200])
            left += [f"claude plugin marketplace add \"{HERE / 'mod'}\"", f"claude plugin install {PLUGIN}@{MARKETPLACE}"]
    else:
        left = [f"claude mcp add {MCP_NAME} -s user -- \"{sys.executable}\" \"{HERE / 'server.py'}\"",
                f"claude plugin marketplace add \"{HERE / 'mod'}\"", f"claude plugin install {PLUGIN}@{MARKETPLACE}"]
    if left:
        say("\nSteps left for you (run them in a terminal where the claude command works):")
        for c in left:
            say("  " + c)
    if notes:
        say("\nStill to fix from an earlier install (listed above): until then an older copy can keep running. Run")
        say("install_mod.py --dry-run  to see them again.")
    say("\nDone. Restart Claude Code (close it, open a new session) and ask your AI: journal_quick(\"<a word from your project>\").")
    say("Check the mod: ask it to edit a file your Brain map names; the first touch carries that piece's journal")
    say("brief (handoff, state, pending, decisions, rules) with the call.")
    say(f"Undo: \"{sys.executable}\" install_mod.py --uninstall")
    return 0


def uninstall(dry: bool) -> int:
    data = load_settings()
    env = dict(data.get("env") or {})
    has = [k for k in KEYS if k in env]
    say("Changes:")
    for k in has:
        say(f"  remove ~/.claude/settings.json env {k}")
    if not has:
        say("  settings.json: nothing to remove")
    if shutil.which("claude"):
        if dry or mcp_registered():
            run_claude("mcp", "remove", MCP_NAME, "-s", "user", dry=dry)
        run_claude("plugin", "uninstall", f"{PLUGIN}@{MARKETPLACE}", dry=dry)
        run_claude("plugin", "marketplace", "remove", MARKETPLACE, dry=dry)
    else:
        say(f"  (no claude command: run  claude mcp remove {MCP_NAME} -s user,  claude plugin uninstall "
            f"{PLUGIN}@{MARKETPLACE}  and  claude plugin marketplace remove {MARKETPLACE}  yourself)")
    if dry:
        say("\nDry run: nothing written.")
        return 0
    data = load_settings()   # read again: the claude commands above may have changed the file
    env = dict(data.get("env") or {})
    has = [k for k in KEYS if k in env]
    stale = [(sec, key) for sec, key in (("enabledPlugins", f"{PLUGIN}@{MARKETPLACE}"), ("extraKnownMarketplaces", MARKETPLACE))
             if key in (data.get(sec) or {})]   # entries the claude command can leave behind for this plugin only
    if has or stale:
        for k in has:
            env.pop(k)
        if env:
            data["env"] = env
        else:
            data.pop("env", None)
        for sec, key in stale:
            data[sec].pop(key)
            if not data[sec]:
                data.pop(sec)
        write_settings(data)
    say("Removed. Your journals and the index in ~/.journal are untouched.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    return uninstall(a.dry_run) if a.uninstall else install(a.dry_run, a.yes)


if __name__ == "__main__":
    sys.exit(main())
