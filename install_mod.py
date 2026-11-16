#!/usr/bin/env python3
"""Neural DNA: Memory for your AI. One-command install for Claude Code.

    <venv python> install_mod.py --dry-run    1. dry run: print every change, write nothing
    <venv python> install_mod.py              2. install: show each change, ask once, apply (--yes applies without asking)
    <venv python> install_mod.py --check      3. check: is it installed and does it answer; changes nothing
    <venv python> install_mod.py --uninstall  4. uninstall: reverse it (MCP server entry, plugin, marketplace, the two settings keys)

It adds, it never replaces. What it does:
  1. registers the journal MCP server in Claude Code (user scope, name "journal"), run by this Python;
  2. adds the journals mod (a Claude Code plugin in ./mod) from a local marketplace folder, no account needed;
  3. writes two keys in the "env" block of ~/.claude/settings.json (JOURNAL_MCP_DIR, JOURNAL_PYTHON) so the mod
     finds this folder. A timestamped backup is written first and nothing else in the file is changed.
Your journals, your rule files (CLAUDE.md, AGENTS.md) and your AI's own memory are never edited, moved or replaced.
Running it again changes nothing.
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
    # By its full path: on Windows the command can be a .cmd file, which is not found by its bare name.
    cmd[0] = shutil.which("claude") or "claude"
    try:
        # Read as UTF-8, whatever the console's own code page: the command prints marks (a tick, an arrow) that
        # the Windows default cannot decode (found by the first real install: the check crashed on "plugin list").
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
        say("Run this from the unzipped Neural DNA folder (server.py and quick_hook.py must sit next to it).")
        sys.exit(1)
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError:   # missing, or a newer mcp without FastMCP: requirements.txt pins a working version
        say("The mcp package this tool needs is missing or too new for this Python:")
        say(f"  {sys.executable} -m pip install -r requirements.txt")
        say("Run that from this folder (inside your .venv), then run this again. Nothing was changed.")
        sys.exit(1)


def mcp_registered() -> bool:
    code, out = run_claude("mcp", "get", MCP_NAME)
    return code == 0 and "server.py" in out


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


def yours() -> list[str]:
    """What this person already has for rules and memory. Read to be listed, never opened for writing."""
    home, cwd, found = Path.home(), Path.cwd(), []
    for label, p in (("your global rules", home / ".claude" / "CLAUDE.md"),
                     ("your rules folder", home / ".claude" / "rules"),
                     ("your project rules", cwd / "CLAUDE.md"),
                     ("your project rules", cwd / "AGENTS.md"),
                     ("your Codex rules", home / ".codex" / "AGENTS.md"),
                     ("your Cursor rules", home / ".cursor" / "rules")):
        try:
            if p.exists() and p.resolve() != (HERE / p.name).resolve():
                found.append(f"{label}: {p}")
        except OSError:
            pass
    try:
        memories = [d for d in (home / ".claude" / "projects").glob("*/memory") if d.is_dir()]
    except OSError:
        memories = []
    if memories:
        found.append(f"your AI's own memory: {len(memories)} folder(s) under {home / '.claude' / 'projects'}")
    return found


def say_yours() -> None:
    found = yours()
    say("Yours, left exactly as they are (Neural DNA adds beside them and never edits, moves or replaces them):")
    for line in found:
        say("  " + line)
    if not found:
        say("  no rules or memory files found yet: nothing to keep safe")
    say("  When a rule of yours and a default rule of ours disagree, yours wins: switch ours off with")
    say("  JOURNAL_DEFAULT_RULES_OFF=<rule id>, or the whole pack with JOURNAL_DEFAULT_RULES=off.")
    if any(line.endswith("CLAUDE.md") or line.endswith("AGENTS.md") for line in found):
        say("  To have your own rule files read as rules too, list them in JOURNAL_RULE_FILES (INSTALL.md).")


def say_what() -> None:
    """The whole footprint in plain words: what is added, what runs, what is never touched, how it comes off."""
    hook = f'"{sys.executable}" "{HERE / "quick_hook.py"}"'
    say("What the install adds:")
    say("  1. two keys in the env block of ~/.claude/settings.json (JOURNAL_MCP_DIR, JOURNAL_PYTHON), after a backup")
    say(f"  2. in Claude Code: the MCP server '{MCP_NAME}' (user scope, in ~/.claude.json) and the plugin {PLUGIN}@{MARKETPLACE}")
    say(f"     from {HERE / 'mod'} (Claude Code keeps a copy in ~/.claude/plugins/cache/{MARKETPLACE} and switches it on")
    say("     in enabledPlugins of settings.json)")
    say("  3. ~/.journal, made on first use: the search index of your journals, the mod's session state and its logs")
    say("What it reads as journals: every file named *JOURNAL*.md or journal.md under ~/Desktop and ~/Documents, a")
    say("  personal diary with that name included. Set JOURNAL_ROOTS before the first use to name other folders.")
    say("  A file your AI touches outside those folders counts too: the nearest folder above it (10 at most) with 1 to 5")
    say("  journal files is its project, so a cloned repository's journal reaches your AI, with a note that it is")
    say("  outside your folders and is not your instructions. JOURNAL_OUTSIDE_ROOTS=off stops those briefs.")
    say("Hooks the plugin registers. Each one runs this one local program with the event as JSON, no network (it may")
    say("run git status, git diff, git clean -n or git rev-parse locally when a git rule matches):")
    say("  " + hook)
    say("  --prompt   when you send a message: reads the message and your journals, adds a short map to the turn")
    say("  (no flag)  before a tool call (edit, command, agent brief, other tool, project read): reads the tool's name and")
    say("             input and adds the journal brief or map. It can stop a call: a default rule stops it once or")
    say("             waits for a yes in your latest message (shell commands and file writes only, never another")
    say("             MCP tool); the first touch of a piece your Brain map names whose journal file is missing is")
    say("             denied twice and goes through on the third try")
    say("  (no flag)  after your AI reads a journal: records which journal was read")
    say("  --output   after a shell command: reads what it returned, adds a note when your journals already ruled on it")
    say("  --reply    when a reply is finished: reads the reply, carries a note into the next turn")
    say("  --stop     before the turn ends: reads the reply and the turn's tool calls, sends back once a reply that says")
    say("             done right after a change nothing looked at")
    say("  They write only inside ~/.journal. The plugin also adds one fixed paragraph to your AI's instructions and a")
    say("  status line; INSTALL.md prints the paragraph word for word.")
    say("Tools that reach the network, only when your AI calls them: check_for_update, journal_market, journal_pair,")
    say("  journal_get, journal_library (vibedna.ai), journal_verify and journal_audit(check_urls=True) (the URLs in")
    say("  your journal), journal_backup_to_drive (your own rclone remote). No telemetry.")
    say("Two tools write outside ~/.journal, only when you ask for them and only with confirm=True, after a backup:")
    say("  journal_install_rule (adds one section to a CLAUDE.md) and journal_install_build_check (adds one hook to")
    say("  settings.json). The uninstall takes both back out.")
    say("Never touched by the install: your journals' text, your rule files, your AI's own memory, your code, any other")
    say("  setting, any other plugin or MCP server.")
    say(f"One command removes what was added:  \"{sys.executable}\" install_mod.py --uninstall")
    say("  It leaves ~/.journal (index and logs), this folder with its .venv, and the settings.json.bak_journals_* backups:")
    say("  delete those yourself for no trace. Removing the key JOURNAL_MCP_DIR alone switches the whole mod off.")


def verify_manifest() -> tuple[int, list[str]]:
    """(files checked, files that are missing or differ) against MANIFEST.sha256 in this folder."""
    import hashlib
    listed, wrong = 0, []
    for ln in (HERE / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, rel = ln.strip().partition("  ")
        if not rel:
            continue
        listed += 1
        f = HERE / rel
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            wrong.append(rel)
    return listed, wrong


def install(dry: bool, yes: bool) -> int:
    preflight()
    have_claude = shutil.which("claude") is not None
    data = load_settings()
    env = dict(data.get("env") or {})
    todo = {k: v for k, v in KEYS.items() if env.get(k) != v}
    add_mcp = have_claude and not mcp_registered()
    mcp_cmd = ["mcp", "add", MCP_NAME, "-s", "user", "--", sys.executable, str(HERE / "server.py")]

    say(f"Neural DNA {VERSION}: Memory for your AI.")
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
    say_what()
    say_yours()
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
        say("\nStill to fix from an earlier install (listed above): until then an older copy can keep running. The check")
        say("names each one again:  install_mod.py --check")
    say("\nDone. Restart Claude Code (close it, open a new session) and ask your AI: journal_quick(\"<a word from your project>\").")
    say("Check the mod: ask it to edit a file your Brain map names; the first touch carries that piece's journal")
    say("brief (handoff, state, pending, decisions, rules) with the call.")
    say(f"Check:  \"{sys.executable}\" install_mod.py --check")
    say(f"See your memory grow:  \"{sys.executable}\" growth.py --serve 4747 --open")
    say(f"Undo:  \"{sys.executable}\" install_mod.py --uninstall")
    return 0


def _run_here(*args: str, stdin: str = "", timeout: int = 120) -> tuple[int, str, float]:
    t = time.time()
    try:
        r = subprocess.run([sys.executable, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(HERE), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e), time.time() - t
    return r.returncode, (r.stdout + r.stderr).strip(), time.time() - t


def check() -> int:
    """Is it installed, and does it answer. No setting and no file of yours is changed; the tool's own index
    (~/.journal) is made on first use, here or in your first session."""
    say(f"Neural DNA {VERSION}: check (no setting and no file of yours is changed).")
    bad = 0

    def line(ok, text: str) -> None:
        nonlocal bad
        bad += 0 if ok else 1
        say(("  ok    " if ok else "  FIX   ") + text)

    line(sys.version_info >= (3, 10), "Python %d.%d (3.10 or newer is needed)" % sys.version_info[:2])
    try:
        listed, wrong = verify_manifest()
        line(not wrong, f"the {listed} files of the package match MANIFEST.sha256" if not wrong else
             "these files are missing or differ from MANIFEST.sha256 (unzip the package again): " + ", ".join(wrong[:8]))
    except OSError:
        line(False, "MANIFEST.sha256 is missing: unzip the package again")
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
        line(True, "the mcp package is installed for this Python")
    except ImportError:
        line(False, f"the mcp package is missing: {sys.executable} -m pip install -r requirements.txt")
    env = dict(load_settings().get("env") or {})
    for k, v in KEYS.items():
        line(env.get(k) == v, f"~/.claude/settings.json env {k}" + ("" if env.get(k) == v else
             (" is not set: run install_mod.py" if k not in env else f" points somewhere else ({env[k]}): run install_mod.py")))
    if shutil.which("claude"):
        line(mcp_registered(), f"the MCP server '{MCP_NAME}' is registered in Claude Code")
        code, out = run_claude("plugin", "list")
        line(code == 0 and f"{PLUGIN}@{MARKETPLACE}" in out, f"the journals mod ({PLUGIN}@{MARKETPLACE}) is installed in Claude Code")
    else:
        say("  note  the claude command is not on this PATH: run  claude mcp list  and  claude plugin list  where it works")
    for n in entry_notes(env):
        line(False, n)
    code, out, secs = _run_here("-c", "import server; print(server.VERSION)")
    line(code == 0 and out.strip().endswith(VERSION), f"the journal server loads (version {out.strip()[-12:] if code == 0 else 'error: ' + out[-160:]})")
    code, out, secs = _run_here("quick_hook.py", "--prompt", stdin=json.dumps({"prompt": "check", "session_id": "install-check", "cwd": str(HERE)}))
    line(code == 0, "the mod's hook answers (%.1f s this first time; it is faster once the index exists)" % secs
         if code == 0 else "the mod's hook failed: " + out[-200:])
    code, out, secs = _run_here("-c", "import growth; print(len(growth.find(growth.default_roots())))")
    if code == 0 and out.strip().isdigit():
        say(f"  note  {out.strip()} journal file(s) found in your journal folders (INSTALL.md step 2 says how to add folders)")
    say_yours()
    say("\nAll good." if not bad else f"\n{bad} thing(s) to fix, listed above. Nothing was changed.")
    return 1 if bad else 0


HOOK_FLAG = "--hook-before-build"            # the hook journal_install_build_check adds to settings.json
RULE_HEAD = "# Project Journals: HARD RULE"  # the section journal_install_rule adds to a CLAUDE.md
GLOBAL_RULES = Path.home() / ".claude" / "CLAUDE.md"


def _build_check_blocks(data: dict) -> list:
    """The PreToolUse blocks the tool journal_install_build_check added (their command carries the hook flag)."""
    blocks = (data.get("hooks") or {}).get("PreToolUse") or []
    return [b for b in blocks if isinstance(b, dict)
            and any(HOOK_FLAG in str(h.get("command") or "") for h in b.get("hooks") or [] if isinstance(h, dict))]


def _rule_text() -> str:
    """The exact section journal_install_rule appends, asked from the server so both always agree."""
    code, out, _ = _run_here("-c", "import sys, server; sys.stdout.buffer.write(server._CLAUDE_RULE.encode('utf-8'))")
    return out if code == 0 and out.startswith(RULE_HEAD) else ""


def remove_rule(dry: bool) -> None:
    """Take the section journal_install_rule added back out of ~/.claude/CLAUDE.md, after a backup. Only the exact
    text is removed: a section the person edited is left alone and named."""
    try:
        text = GLOBAL_RULES.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if RULE_HEAD not in text:
        return
    rule = _rule_text().strip()
    at = text.find(rule) if rule else -1
    if at < 0:
        say(f"  {GLOBAL_RULES}: it has the section \"{RULE_HEAD}\" in an edited or older form. Left as it is: delete")
        say("  that section by hand if you do not want it.")
        return
    say(f"  remove the section \"{RULE_HEAD}\" from {GLOBAL_RULES} (added by the tool journal_install_rule)")
    if dry:
        return
    backup = GLOBAL_RULES.with_name(f"CLAUDE.md.bak_journals_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(GLOBAL_RULES, backup)
    say(f"  backup: {backup}")
    kept = text[:at].rstrip("\n") + ("\n" if text[:at].strip() else "") + text[at + len(rule):].lstrip("\n")
    GLOBAL_RULES.write_text(kept, encoding="utf-8")


def uninstall(dry: bool) -> int:
    data = load_settings()
    env = dict(data.get("env") or {})
    has = [k for k in KEYS if k in env]
    say("Changes:")
    for k in has:
        say(f"  remove ~/.claude/settings.json env {k}")
    if not has:
        say("  settings.json: nothing to remove")
    if _build_check_blocks(data):
        say("  remove the before-build hook from ~/.claude/settings.json (added by the tool journal_install_build_check)")
    remove_rule(dry)
    say("  (a project's own CLAUDE.md that got the rule section is not known to this installer: the section starts with")
    say(f"  \"{RULE_HEAD}\")")
    left = []   # a step of the claude command that did not work is named at the end, never passed over
    if shutil.which("claude"):
        steps = [("plugin", "uninstall", f"{PLUGIN}@{MARKETPLACE}"), ("plugin", "marketplace", "remove", MARKETPLACE)]
        if dry or mcp_registered():
            steps.insert(0, ("mcp", "remove", MCP_NAME, "-s", "user"))
        for step in steps:
            code, out = run_claude(*step, dry=dry)
            gone = any(w in out.lower() for w in ("not found", "not installed", "no such", "does not exist", "unknown"))
            if code != 0 and not gone:
                say(f"  \"claude {' '.join(step)}\" said: {out[:200]}")
                left.append("claude " + " ".join(step))
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
    extra = _build_check_blocks(data)
    # the claude command leaves these two blocks behind, empty, and its own copy of the plugin (found by the first
    # real install and uninstall): an empty block means nothing, so it goes; a block with anything in it stays
    empty = [sec for sec in ("enabledPlugins", "extraKnownMarketplaces") if sec in data and not data[sec]]
    cache = Path.home() / ".claude" / "plugins" / "cache" / MARKETPLACE
    if cache.is_dir():
        shutil.rmtree(cache, ignore_errors=True)
        say(f"  removed Claude Code's copy of the plugin: {cache}")
    if has or stale or extra or empty:
        for sec in empty:
            data.pop(sec, None)
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
        if extra:
            pre = [b for b in data["hooks"]["PreToolUse"] if b not in extra]
            if pre:
                data["hooks"]["PreToolUse"] = pre
            else:
                data["hooks"].pop("PreToolUse")
            if not data["hooks"]:
                data.pop("hooks")
        write_settings(data)
    if left:
        say("Not everything was removed. These steps did not work, run them yourself where the claude command works:")
        for c in left:
            say("  " + c)
        say("The settings keys are out. Your journals, your own rules and your AI's own memory are untouched.")
    else:
        say("Removed. Your journals, your own rules, your AI's own memory and the index in ~/.journal are untouched.")
    say("Still on disk, yours to delete: ~/.journal, this folder with its .venv, the settings.json.bak_journals_* backups,")
    say("and the rule section in a project's own CLAUDE.md if you ever had the tool add one there.")
    return 1 if left else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    return uninstall(a.dry_run) if a.uninstall else install(a.dry_run, a.yes)


if __name__ == "__main__":
    sys.exit(main())
