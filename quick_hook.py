"""Light front door for the journal quick-map hooks (PreToolUse and UserPromptSubmit).

Loading server.py costs about a second, so calls that cannot need a map (a read-only command, an edit to a
journal itself, an empty prompt) exit here at once. Everything else goes to server.py's _quick_hook.

Claude Code settings:
  PreToolUse  (Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|Read|Grep|Glob): python quick_hook.py
  UserPromptSubmit:                                                python quick_hook.py --prompt

Reads (Read, Grep, Glob, read-only commands, data queries) never load server.py: the first read inside a mapped
piece or a project folder with journals, in each user message, gets a short "read its journal first" note
(2026-10-24: an answer about AA mails came from code reading alone and was wrong; reads never triggered anything).

The gate: the first write of a mapped piece, and the first read of a mapped piece or journal folder in a session,
carries that piece's JOURNAL BRIEF (its Handoff, Current state, Pending, Decided, Already exists and Rules sections and
the newest entry headings, read straight from the file) and goes through; the brief counts as the session's read of
that journal. Only when no journal file is on disk is the touch denied until the journal was read, with an escape on
the 3rd attempt so it never deadlocks (logged to gate_escapes.log). Reading journals is never gated.
"""
import json
import posixpath
import re
import sys

WRITE_CMD = re.compile(r"(?<![\w./~\\-])(ssh|scp|rsync|sed\s+-i|tee|cp|mv|crontab|systemctl|git\s+push)(?![\w./\\-])|(?<![0-9&>])>{1,2}(?!&)\s*(?!/dev/null\b|\$null\b|nul\b)[^\s&|;]")

# COST GATE (2026-11-06, owner: "the credits went very fast, measure the mod"): the AI command/MCP check ran on every
# call, two strong verdicts each: 15,888 judge calls and ~US$698 API-equivalent on 2026-11-05, 15.7 h of waiting, all on
# the owner's own account. The judge still decides what is right; this only decides when asking it is worth it: servers,
# deletes, deploys, money, credentials, outward actions, a bare `python` (the Store alias that froze the PC). Everything
# else keeps the free journal map. JOURNAL_ACTION_CHECK_ALL=on brings back the check on every call.
RISKY_CMD = re.compile(
    r"\b(ssh|scp|sftp|rsync|shred|taskkill|systemctl|crontab|schtasks|docker|kubectl|vercel|netlify|wrangler|stripe|"
    r"solana|spl-token|shutdown|vault)\b|\bgit\s+(push|reset\s+--hard|clean|branch\s+-D|worktree\s+remove|filter-|rebase)"
    r"|\brm\s|\brmdir\b|Remove-Item|Stop-Process|Restart-Computer|\bdel\s|\bmv\s|Move-Item|\bdeploy|npm\s+run\s+ship"
    r"|curl[^|;\n]*(-X\s*(POST|PUT|PATCH|DELETE)|\s-d\s|--data|-F\s)|\bgh\s+(pr|release|repo|api|secret)"
    r"|DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|reg\s+(add|delete)|Set-ItemProperty"
    r"|(^|[\s;&|(])(python3?|py)(\.exe)?\s"
    r"|\b(sk|pk|rk)_(live|test)_|vcp_|ghp_|github_pat_|AKIA|xox[bp]-|eyJhbGci"
    r"|(?<![0-9&>])>{1,2}\s*[^\s&|;]*(\.env|settings\.json|CLAUDE\.md)", re.I)
RISKY_MCP = re.compile(
    r"publish|post_|_post|send|reply|forward|delete|trash|wipe|share|upload|deploy|campaign|budget|click|fill|key_|"
    r"navigate|eval_js|submit|tweet|tiktok|pinterest|engage|unfollow|dm_|apply|credential|rotated|update_file|create_file|"
    r"spam|label|drip_(schedule|add|delete|edit|resume)|install|replay|swarm|worker|schedule|claim|set_|create_youtube|"
    r"intercept|stealth|captcha|totp|import_profile", re.I)


# Writes (same cost gate, 2026-11-06): every edit sent all the owner's rules (~5,600 tokens, never cached between
# processes) to the judge, 7.8 s per edit measured. Text people read (docs, pages, copy, configs) keeps the full check;
# code goes to the judge only when it carries what a rule is about: a long dash, a secret, a config or rules file.
CODE_FILE = re.compile(r"\.(py|pyw|ts|tsx|js|jsx|mjs|cjs|go|rs|java|kt|swift|c|cc|cpp|h|cs|rb|php|sh|bash|ps1|sql|"
                       r"css|scss|gd|lua|toml|ini|cfg|lock|test\.ts)$", re.I)
RISKY_TEXT = re.compile(r"[\u2013\u2014]|\b(sk|pk|rk)_(live|test)_|vcp_|ghp_|github_pat_|AKIA|xox[bp]-|eyJhbGci|"
                        r"-----BEGIN|password\s*=\s*['\"][^'\"]{6,}|(api|secret|token)_?key\s*=\s*['\"][^'\"]{12,}", re.I)
RULES_FILE = re.compile(r"(^|[\\/])(CLAUDE\.md|AGENTS\.md|MEMORY\.md)$|settings(\.local)?\.json$|\.env|\.mcp\.json$", re.I)


def _write_needs_judge(fp: str, text: str) -> bool:
    if _check_all() or RULES_FILE.search(fp) or not CODE_FILE.search(fp):
        return True
    return bool(RISKY_TEXT.search(text))


OVERRIDE = "<override>"


def _compiled_stop(call: dict, text: str, on: str) -> str:
    """The owner's mechanical rules as tests the judge wrote once (rulecompile.py): free, run on every command or
    write. The same text again within 30 min passes (a test can be wrong; never a deadlock)."""
    try:
        sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0])
        import rulecompile
        hits = rulecompile.check(text, on, str((call.get("tool_input") or {}).get("file_path") or ""))
    except Exception:
        return ""
    if not hits:
        return ""
    import hashlib
    import time
    f, seen = _state(call)
    sig = hashlib.sha1((on + text).encode("utf-8", "replace")).hexdigest()[:16]
    den = dict(seen.get("ctest_denied") or {})
    if time.time() - float(den.get(sig, 0)) < 1800:
        event("exact_override", on=on, rules=[d["where"] for d in hits[:3]])
        return OVERRIDE  # the AI ran it again on purpose: the judge must not stop it a second time (2026-11-06)
    den[sig] = time.time()
    event("exact_stop", on=on, rules=[d["where"] for d in hits[:3]], text=text[:200])
    seen["ctest_denied"] = dict(sorted(den.items(), key=lambda t: -t[1])[:100])
    _save(f, seen)
    what = "command" if on == "command" else "text"
    return (f"STOPPED BY THE OWNER'S RULES (exact test, no AI): this {what} breaks:\n" +
            "\n".join(f"- {d['say']} ({d['where']})" for d in hits[:3]) +
            "\nDo it the right way above. (If the test is wrong, the same call passes if run again unchanged.)")


def event(kind: str, **kw) -> None:
    """One line per thing the mod did for the owner to measure (stops, overrides, briefs): mod_events.jsonl."""
    try:
        import time
        from pathlib import Path
        try:
            from default_rules import redact
            kw = {k: redact(v) if isinstance(v, str) else v for k, v in kw.items()}
        except Exception:
            pass
        with (Path(_home()) / "mod_events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind, **kw},
                                ensure_ascii=False) + chr(10))
    except Exception:
        pass


def _ai_mode() -> str:
    """JOURNAL_AI_CHECKS: "off" (default), "risky" or "all": whether an AI judge reads each command, MCP call and
    written text before it runs. Off since 2026-11-06 (owner: "the cheapest possible"): measured, the per-call judge
    cost ~US$20/h with five tabs and most of its stops were false, each one costing the tab a whole extra turn. What
    stays on with no AI: the journal briefs, the owner's exact rule tests; with AI, once per turn, the reply check."""
    import os
    if os.environ.get("JOURNAL_ACTION_CHECK_ALL", "").lower() in ("on", "1", "true", "yes"):
        return "all"
    m = os.environ.get("JOURNAL_AI_CHECKS", "off").lower()
    return m if m in ("off", "risky", "all") else "off"


def _check_all() -> bool:
    import os
    return os.environ.get("JOURNAL_ACTION_CHECK_ALL", "").lower() in ("on", "1", "true", "yes")


READ_TOOLS = {"Read", "Grep", "Glob"}
JOURNAL_MD = re.compile(r"journal[^\\/]*\.md$", re.I)
JOURNAL_NAME = re.compile(r"[\w.-]*journal[\w.-]*\.md", re.I)
DB_CMD = re.compile(r"\b(psql|sqlite3|mysql|duckdb|neonctl|d1\s+execute|supabase)\b|\bselect\s.+\sfrom\b", re.I | re.S)
TOKENS = re.compile(r'"([^"]+)"|\'([^\']+)\'|(\S+)')
# Drafts and dated reports are not a project's journal even when "journal" is in their name (Director 2026-10-25:
# desks/quality held localmodel_firstpass_journal-synonym-groups.md and the gate asked to read that draft).
# A tool's capability doc ("journal_JUICE.md", about the journal tool) is not a project journal either (2026-10-26:
# reading TOOL SHOP/JUICE was gated as project "JUICE").
SCRATCH_MD = re.compile(r"^(draft|scratch)|[-_]draft\.md$|^\d{4}-\d{2}-\d{2}[-_]|_juice\.md$", re.I)
MAX_FOLDER_JOURNALS = 5  # a folder with more journals than this at its top is a workspace, not one project
# Paths that never count as touching a piece (Director 2026-10-25): company rules and role manuals, and the
# session's own scratch and saved tool output (a sed of an enter() reply stopped a Director).
EXEMPT_PATH = re.compile(
    r"(^|/)(AGENTS|CLAUDE)\.md$|(^|/)STARTUP_[^/]*\.md$|/manuals/[^/]*\.md$"
    r"|^(/private)?/tmp/claude-[^/]+/|/\.claude/projects/[^/]+/(tool-results|memory)/")
# 2026-11-03: the AI's own memory folder (an index plus notes, some with "journal" in their name) was gated as project
# "memory" asking to read reference_boltlab_infra_validator_journal.md before editing MEMORY.md.
GATE_ESCAPE_AT = 3  # attempts: the 3rd opens the gate when a read is impossible (no journal file, or reads fail)
READ_FRESH_S = 1800  # a journal read this recent opens its gate, whatever message it happened in
MAP_AGAIN_S = 1800  # a file's map shown and passed this recently is not run again on the next edit of that file


def _fold(w: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", w.lower()) if unicodedata.category(ch) != "Mn")


def _home() -> str:
    import os
    from pathlib import Path
    return os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))


def _state(call: dict):
    from pathlib import Path
    d = Path(_home()) / "quick_seen"
    d.mkdir(parents=True, exist_ok=True)
    f = d / (re.sub(r"[^\w-]", "", call.get("session_id") or "nosession")[:80] + ".json")
    try:
        seen = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        seen = {}
    if call.get("reports_reads"):
        seen["rr"] = 1  # this session's mod reports journal reads (0.3.0+): the gate can wait for one
    return f, seen


def _save(f, seen: dict):
    try:
        f.write_text(json.dumps(seen), encoding="utf-8")
    except Exception:
        pass


def jkey(name: str) -> str:
    """One key per journal from a file name, a path or a short name: "TONE_GARDEN_JOURNAL.md", "TONE GARDEN"
    and "C:/x/TONE_GARDEN_JOURNAL.md" all give "tonegarden"."""
    base = re.split(r"[\\/]", str(name).strip())[-1]
    base = re.sub(r"\.md$", "", base, flags=re.I)
    return "".join(w for w in re.split(r"[^a-z0-9]+", _fold(base)) if w and w != "journal")


def _names_in(text: str) -> list:
    return list(dict.fromkeys(JOURNAL_NAME.findall(text or "")))


def _unwrap(text: str):
    """Journal tool results arrive as JSON text, sometimes wrapped once more; give back the inner object."""
    obj = text
    for _ in range(3):
        if not isinstance(obj, str):
            break
        try:
            obj = json.loads(obj)
        except Exception:
            return None
        if isinstance(obj, dict) and isinstance(obj.get("content"), list):
            obj = "".join(str(b.get("text", "")) for b in obj["content"] if isinstance(b, dict))
    return obj if isinstance(obj, dict) else None


def record_read(call: dict):
    """After a journal read ran (the mod reports it): remember which journals this session read, when, and in
    which user message. A failed read is remembered too: it is what lets the gate's escape open."""
    import time
    ti = call.get("tool_input") or {}
    f, seen = _state(call)
    n = int(seen.get("n", 0))
    ok = ti.get("ok", True) is not False
    keys = set()
    if "journal_tool" not in ti:
        v = str(ti.get("journal_read") or "")
        names = _names_in(v)
        if len(v) < 600 and names:
            keys.add(jkey(names[-1]))  # a Read of the journal file: its path
        else:
            keys |= {jkey(x) for x in names}  # an older mod sent the whole tool result text
    else:
        tool = str(ti.get("journal_tool") or "").rsplit("__", 1)[-1]
        args = ti.get("args") or {}
        text = str(ti.get("text") or "")
        if tool in ("journal_read", "journal_read_section", "journal_handoff_brief"):
            # Every argument name the tools accept (server.py aliases since 2026-10-25): name_or_path, name, path,
            # journal, project. Only name_or_path was read here, so journal_handoff_brief(name="AI_TEAM_JOURNAL.md")
            # or (project="WEBWEAVE") never counted (2026-10-27).
            target = next((str(args[k]) for k in ("name_or_path", "name", "path", "journal", "project")
                           if args.get(k)), "")
            if target and ok and not re.match(r"\s*(journal not found|error|read error|several)", text, re.I):
                keys.add(jkey(target))
                keys |= {jkey(x) for x in _names_in(text[:1500])}
        elif tool in ("journal_search", "journal_quick"):
            obj = _unwrap(text)
            if obj is not None:
                # Only the journals the result is about; "latest" and "pending" lines of other journals do not count.
                for m in obj.get("matches") or []:
                    keys.add(jkey(m.get("name") or m.get("path") or ""))
                for j in obj.get("journals") or []:
                    keys.add(jkey(j.get("journal") or j.get("path") or ""))
                for o in obj.get("pieces") or []:
                    keys |= {jkey(x) for x in _names_in(str(o.get("path") or ""))}
            else:
                keys |= {jkey(x) for x in _names_in(text[:20000])}
    keys.discard("")
    if not ok or not keys:
        seen["jf"] = time.time()
    now = time.time()
    for k in keys:
        seen.setdefault("jr", {})[k] = n
        seen.setdefault("jt", {})[k] = now
    # Direct reads only (not every journal a search result happened to list) say which project the session is on:
    # the owner brief follows them (2026-11-03: a code_sync search listed AI_TEAM and DIRECTOR journals and their
    # briefs replaced Oddsboard's on "bueno como va").
    direct = "journal_tool" not in ti or str(ti.get("journal_tool") or "").rsplit("__", 1)[-1] in (
        "journal_read", "journal_read_section", "journal_handoff_brief")
    if direct and ok:
        jc = seen.setdefault("jc", {})
        for k in keys:
            jc[k] = [int((jc.get(k) or [0, 0])[0]) + 1, now]
    _save(f, seen)


BRIEF_SECTIONS = re.compile(r"handoff|current state|pending|decided|already exists|rules|qu[eé] falta", re.I)
BRIEF_MAX = 6000


def brief(path: str) -> str:
    """The parts of a journal a session must know before touching its piece (Handoff, current state, pending,
    decided, already exists, rules) plus the newest entry headings, read straight from the file (no server, ~20 ms)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ""
    keep, latest, on = [], [], False
    for ln in lines:
        if ln.startswith("## "):
            on = bool(BRIEF_SECTIONS.search(ln))
            if re.match(r"## \d{4}-\d{2}-\d{2}", ln):
                latest.append(ln[3:140])
        if on and ln.strip():
            keep.append(ln[:400])
    text = "\n".join(keep)[:BRIEF_MAX]
    tail = "\n".join(f"- {h}" for h in latest[-6:])
    return text + (f"\n\nLATEST ENTRIES (newest last):\n{tail}" if tail else "")


def gate(seen: dict, gkey: str, journals: list, files: list, what: str) -> tuple:
    """The journals gate for one piece or project: ("open", ""), ("deny", why) or ("escape", loud note).
    journals: its journal file names; files: their paths on disk (empty when unknown)."""
    import os
    import time
    g = seen.setdefault("g", {})
    st = g.get(gkey)
    if st == "open":
        return "open", ""
    keys = {jkey(j) for j in journals} - {""}
    n = int(seen.get("n", 0))
    jr, jt = seen.get("jr", {}), seen.get("jt", {})
    since = st["at"] if isinstance(st, dict) else None
    # A read in the last 30 minutes counts too (2026-11-03: a session read ADSCOPE_JOURNAL by full path, then a
    # message from another session bumped the message counter and the next two Reads were stopped "no read
    # recorded"; the PC cleanup session was stopped 3 times the same way after reading the journal minutes before).
    now = time.time()
    if any(jr.get(k) == n or (since is not None and jt.get(k, 0) >= since) or now - float(jt.get(k, 0)) < READ_FRESH_S
           for k in keys):
        g[gkey] = "open"
        return "open", ""
    j0 = journals[0] if journals else ""
    on_disk = [p for p in files if p and os.path.isfile(p)]
    # MEMORY DELIVERED, NOT A ROUND TRIP (owner 2026-11-06: the stop cost a whole extra turn every time, "the memory
    # stays the same but it cannot weigh"): the journal's brief comes with the call and counts as its read.
    b = brief(on_disk[0]) if on_disk else ""
    if b:
        for k in keys:
            jr[k], jt[k] = n, now
        seen["jr"], seen["jt"] = jr, jt
        g[gkey] = "open"
        event("brief", piece=what, journal=os.path.basename(on_disk[0]))
        return "deliver", (f"JOURNAL BRIEF for {what} ({os.path.basename(on_disk[0])}), read it before acting; "
                           f"open the full journal with journal_read_section if you need more:\n{b}")
    if not isinstance(st, dict):
        st = g[gkey] = {"at": time.time(), "tries": 0}
    st["tries"] += 1
    failed = seen.get("jf", 0) >= st["at"]
    blind = not seen.get("rr")  # an older mod never reports reads: waiting for one would never end
    if st["tries"] >= GATE_ESCAPE_AT and (not on_disk or not keys or failed or blind):
        g[gkey] = "open"
        why = ("its journal file is not on this machine" if not on_disk or not keys else "a journal read failed"
               if failed else "this session runs an older journals mod that does not report journal reads "
               "(a new session loads the new one)")
        try:
            from datetime import datetime, timezone
            from pathlib import Path
            with (Path(_home()) / "gate_escapes.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {gkey} {why} "
                         f"journals={','.join(journals)}\n")
        except Exception:
            pass
        return "escape", (f"JOURNALS GATE OPENED WITHOUT A JOURNAL READ ({what}): {why}, so after "
                          f"{GATE_ESCAPE_AT} attempts the call goes through. This is logged. Read "
                          f"{j0 or 'its journal'} as soon as you can, and say in your answer that you have not yet.")
    calls = []
    if j0:
        calls += [f'journal_handoff_brief("{j0}")', f'journal_read_section("{j0}", "<section>")',
                  f'journal_search("<topic>") with {j0} among the results']
    if on_disk:
        calls.append(f"Read {on_disk[0]} (offset/limit on a long file)")
    head = "STOPPED" if st["tries"] == 1 else (f"STILL STOPPED (attempt {st['tries']}): no read of "
                                               f"{j0 or 'its journal'} was recorded, a plain retry does not open it")
    return "deny", (f"JOURNALS GATE, {head}. Before touching {what}, read its journal. Make one of these calls "
                    "now, then retry: " + "; ".join(calls or ['journal_quick("<topic>")']) + ".")


def _journal_folder(path: str, cwd: str):
    """Nearest folder above a path that holds 1 to MAX_FOLDER_JOURNALS journals at its top (the project)."""
    import os
    p = path.replace("\\", "/")
    if not re.match(r"^([A-Za-z]:)?/", p) and not p.startswith("~"):
        if not cwd:
            return None
        p = cwd.replace("\\", "/").rstrip("/") + "/" + p
    d = os.path.expanduser(re.split(r"[*?\[{]", p)[0]).rstrip("/") or "/"
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    for _ in range(10):
        try:
            js = sorted(n for n in os.listdir(d) if JOURNAL_MD.search(n) and not SCRATCH_MD.search(n)
                         and os.path.isfile(os.path.join(d, n)))
        except Exception:
            js = []
        if len(js) > MAX_FOLDER_JOURNALS:
            return None
        if js:
            name = os.path.basename(d.rstrip("/")) or d
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            js.sort(key=lambda x: (not x.lower().endswith("_journal.md"),
                                   not re.sub(r"[^a-z0-9]", "", x.lower()).startswith(key), len(x)))
            return name, js, d
        up = os.path.dirname(d.rstrip("/"))
        if not up or up == d:
            return None
        d = up
    return None


_CONTAINER_WORDS = set("servers server mods mod tools tool plugins plugin packages package apps app src lib libs hooks "
                       "scripts mcp dna studio journal journals".split())


def _sub_parts(hit, path: str, cwd: str) -> list:
    import os
    p = path.replace("\\", "/")
    if not re.match(r"^([A-Za-z]:)?/", p) and not p.startswith("~") and cwd:
        p = cwd.replace("\\", "/").rstrip("/") + "/" + p
    p = re.sub(r"^/([a-z])/", r"\1:/", p)
    try:
        rel = os.path.relpath(os.path.expanduser(p), hit[2]).replace("\\", "/")
    except ValueError:
        return []
    return [] if rel.startswith("..") else rel.split("/")[:-1]


def _sub_key(hit, path: str, cwd: str) -> str:
    return "/".join(_sub_parts(hit, path, cwd)[:2]).lower()


def _folder_owns(hit, path: str, cwd: str) -> bool:
    """Does the folder's journal speak for this path? Yes for files at its top or one folder down; deeper (a tool
    inside servers/), only when a word of those subfolders is a word of one of its journals' names."""
    subs = _sub_parts(hit, path, cwd)
    if len(subs) < 2:
        return True
    jw = {w for j in hit[1] for w in re.split(r"[^a-z0-9]+", _fold(j)) if len(w) >= 3} - _CONTAINER_WORDS
    sw = {w for s in subs[:3] for w in re.split(r"[^a-z0-9]+", _fold(s)) if len(w) >= 3} - _CONTAINER_WORDS
    return bool(jw & sw) or not sw


GUARD_SUFFIX = re.compile(r"[-_](gate|guard|guards|mod|mods|hook|hooks)(?![a-z0-9])")
HOME_PREFIX = re.compile(r"(?<![a-z0-9])(?:/home|/users)/[^/\s]+(?=/)")
FILE_EXT = re.compile(r"(?<=[\w*-])\.[a-z][a-z0-9]{0,5}(?=$|[\s\"'/\\,;:)|])", re.I)


def _key_hit(keys: list, text: str) -> bool:
    # The user's home folder name ("/home/appuser/...") is where the files live, not a piece: a key equal to the user
    # name matched every path (System Supervisor, 2026-10-25: a Launch Desk script was gated as System code).
    text = HOME_PREFIX.sub("", text)
    # A file extension is a type, not a piece: "/src/pages/index.astro" is not the ASTRO project (2026-10-27).
    bare = FILE_EXT.sub("", text)
    # A guard named after a piece ("oddsboard-gate") is not the piece (2026-11-03: reading the gate's own code was
    # stopped as the Real Oddsboard bot).
    def hit(k: str, t: str) -> bool:
        return any(not GUARD_SUFFIX.match(t, mo.end())
                   for mo in re.finditer(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t))
    return any(len(k) >= 3 and hit(k, text if "." in k else bare) for k in keys)


def read_turn(call: dict):
    """A read of a mapped piece or a journal folder: the first one in the session is gated until its journal is
    read; after that, the first read in each user message gets a short note (silent once its journal was read)."""
    import os
    ti = call.get("tool_input") or {}
    cwd = str(call.get("cwd") or "")
    f, seen = _state(call)
    n = int(seen.get("n", 0))
    read_now = seen.setdefault("jr", {})
    paths = [str(x) for x in (ti.get("paths") or []) if x]
    if ti.get("file_path"):
        paths.append(str(ti["file_path"]))
    text = str(ti.get("command") or ti.get("query") or "")
    # A command that reads a journal file (sed -n 3550,3566p WEBWEAVE_JOURNAL.md, cat, grep, head) is a journal
    # read: it opens the gate and the intent-map stops of that journal like journal_read does (2026-10-27: a
    # session read WEBWEAVE_JOURNAL with sed between every step and was still stopped every step).
    if ti.get("command") and not WRITE_CMD.search(text):
        import time
        for nm in _names_in(text[:4000]):
            k = jkey(nm)
            if k and not SCRATCH_MD.search(nm):
                seen.setdefault("jr", {})[k] = n
                seen.setdefault("jt", {})[k] = time.time()
        _save(f, seen)
    for m in TOKENS.finditer(text[:4000]):
        tok = next(g for g in m.groups() if g is not None)
        if re.search(r"[\\/]", tok) and not tok.startswith(("-", "http")):
            paths.append(tok)
    paths = list(dict.fromkeys(paths))[:6]
    had_paths = bool(paths)
    paths = [p for p in paths if not EXEMPT_PATH.search(posixpath.normpath(p.replace("\\", "/")))]
    if had_paths and not paths and not (ti.get("query") or DB_CMD.search(text)):
        return  # only exempt paths (rules, manuals, scratch, saved tool output): nothing to gate
    if paths and all(JOURNAL_MD.search(p) for p in paths) and not (ti.get("query") or DB_CMD.search(text)):
        return  # reading journals themselves is never gated
    try:
        from pathlib import Path
        rows = json.loads((Path(_home()) / "quick_rows.json").read_text(encoding="utf-8"))
    except Exception:
        rows = []
    db_text = _fold(text) if (ti.get("query") or DB_CMD.search(text)) else ""
    folded = [_fold(p.replace("\\", "/")) for p in paths if not JOURNAL_MD.search(p)] + ([db_text] if db_text else [])
    notes, denies, escapes = [], [], []

    def fresh(key: str, journals: list) -> bool:
        if seen.get(key) == n or any(read_now.get(jkey(j)) == n for j in journals):
            return False
        seen[key] = n
        return True

    def check(key: str, journals: list, files: list, what: str, note: str):
        state, msg = gate(seen, key, journals, files, what)
        if state == "deny":
            denies.append(f"- {what}: {msg}")
        elif state == "escape":
            escapes.append(msg)
            seen[key] = n
        elif state == "deliver":
            notes.append(msg)
            seen[key] = n
        elif fresh(key, journals):
            notes.append(note)

    for row in rows:
        if any(_key_hit(row.get("keys", []), t) for t in folded):
            js = re.findall(r"[\w.-]+_JOURNAL[\w.-]*\.md", row.get("read", ""))
            check("r:" + row["piece"], js, row.get("files") or [], f'piece "{row["piece"]}"',
                  f'- piece "{row["piece"]}": read first {row["read"]}')
    for p in paths:
        if JOURNAL_MD.search(p):
            continue
        hit = _journal_folder(p, cwd)
        if hit and not _folder_owns(hit, p, cwd):
            # a container folder (TOOL SHOP holds dozens of tools) whose journal is about one of them: a file of
            # another tool is not that journal's piece; a note at most, never a gate (2026-10-27: running the
            # gmail tool in TOOL SHOP/servers/mail-tool was stopped 6 times for JOURNAL_MCP_JOURNAL.md)
            key = "r:" + hit[0].lower() + ":" + _sub_key(hit, p, cwd)
            if fresh(key, hit[1]):
                notes.append(f'- project "{hit[0]}": journals {", ".join(hit[1][:3])}')
            continue
        if hit:
            check("r:" + hit[0].lower(), hit[1], [os.path.normpath(os.path.join(hit[2], j)) for j in hit[1]], f'project "{hit[0]}"',
                  f'- project "{hit[0]}": journals {", ".join(hit[1][:3])}')
    _save(f, seen)
    if denies:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
              "permissionDecisionReason": "JOURNALS: you are reading code or data of\n" + "\n".join(denies[:3])
              + "\nCode says what runs; the journal says what was decided and why."}}, ensure_ascii=False))
        return
    if notes or escapes:
        ctx = "\n\n".join(escapes)
        if notes:
            ctx += ("\n\n" if ctx else "") + ("JOURNALS: you are reading code or data of\n" + "\n".join(notes[:3])
                   + "\nBefore answering or concluding anything about it from code or data alone, read its journal on "
                   'THIS topic (journal_quick "<topic>" or journal_search). Code says what runs; the journal says '
                   "what was decided and why.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ctx}},
                         ensure_ascii=False))


def _stub_fastmcp():
    """server.py only needs FastMCP to decorate its tools; the hook calls none of them. Importing the real MCP
    library costs ~0.7 s of the ~1.2 s every edit paid (Memory, 2026-10-25), so the hook (and only the hook: this runs
    from main(), never when server.py is the MCP server) gives server.py an inert stand-in."""
    if "mcp" in sys.modules:
        return
    import types

    class _FastMCP:
        def __init__(self, *a, **k):
            self.settings = types.SimpleNamespace()

        def tool(self, *a, **k):
            return lambda fn: fn

        resource = prompt = tool

        def run(self, *a, **k):
            raise RuntimeError("journal server is not running as an MCP server here")

    for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["mcp.server.fastmcp"].FastMCP = _FastMCP


def _tools_first(call: dict):
    """The tools map (toolmap.py, light, no server import): {"deny": text} or {"note": text} or None. Runs before
    everything else on a call that writes code, runs a script or a remote command, or briefs an agent (2026-10-26:
    an Instagram carousel was posted by a loose Playwright script while the posting tool sat unused)."""
    import os
    # An edit to a file that exists is improving what is there, which is what this map asks for; a new file, a command
    # or an agent brief is where a side way gets built (2026-11-06: the map's judge cost 1-4 s on every edit).
    if call.get("tool_name") not in ("Write", "Bash", "PowerShell", "Agent", "Task") \
            or os.environ.get("JOURNAL_TOOLS_MAP") == "0":   # off switch
        return None
    try:
        here = __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0]
        sys.path.insert(0, here)
        import toolmap
        f, seen = _state(call)
        r = toolmap.check(call, seen)
        try:
            # Wrong copy (2026-10-28): code run from a folder whose near twin is where the journals say it is deployed.
            import livecopy
            lc = livecopy.check(call, seen)
        except Exception:
            lc = None
        try:
            # Already said (2026-10-28): a new owner rule line that repeats one already in OWNER_SAID_JOURNAL.md.
            import ruledupes
            rd = ruledupes.check(call, seen)
        except Exception:
            rd = None
        if rd:
            lc = {"deny": rd["deny"] + ("\n\n" + lc["deny"] if lc else "")}
        try:
            # Already built (2026-11-01): a new script whose job a [ship]/[feature] entry already did, by meaning
            # (four loop cutters were written while cut_loops.py and cut_sections.py sat in the AA journal).
            import builtmap
            bm = builtmap.check(call, seen)
        except Exception:
            bm = None
        if bm:
            lc = {"deny": bm["deny"] + ("\n\n" + lc["deny"] if lc else "")}
        _save(f, seen)
        if lc:
            r = {"deny": lc["deny"] + ("\n\n" + (r.get("deny") or r.get("note") or "") if r else "")}
        return r
    except Exception:
        return None


def _merge(out: str, tm: dict) -> str:
    """One hook answer from the tools map and the journal map: a deny wins; notes are joined, tools first."""
    try:
        o = json.loads(out) if out.strip() else {}
    except Exception:
        o = {}
    h = o.get("hookSpecificOutput") or {"hookEventName": "PreToolUse"}
    if tm.get("deny"):
        reason = tm["deny"]
        if h.get("permissionDecision") == "deny":
            reason += "\n\n" + h.get("permissionDecisionReason", "")
        elif h.get("additionalContext"):
            reason += "\n\n" + h["additionalContext"]
        h = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason
             + "\n\n(Stopped once: the same action passes on retry, once you have looked at the tools above.)"}
    elif h.get("permissionDecision") == "deny":
        h["permissionDecisionReason"] = tm["note"] + "\n\n" + h.get("permissionDecisionReason", "")
    else:
        h["additionalContext"] = tm["note"] + ("\n\n" + h["additionalContext"] if h.get("additionalContext") else "")
    return json.dumps({"hookSpecificOutput": h}, ensure_ascii=False)


def is_notification(text: str) -> bool:
    """A background task's finished notice arrives as a user prompt but is not the owner speaking (2026-10-30: three
    agent reports were mapped as owner messages: Pigment, Starpair, HTMS, imagen, spring25 maps on words of the report)."""
    t = str(text or "")
    # a peer session's message is not the owner either (2026-10-30: a peer reply mapped business game, mapleworks)
    return "<task-notification>" in t or "[SYSTEM NOTIFICATION" in t or "<cross-session-message" in t


def _soft_for_agents(out: str) -> str:
    """An agent launch is never stopped: the subagent meets the gate on its own calls, and a stop only made the main
    session re-read unrelated journals and relaunch (2026-10-30: 4 agent launches stopped in one turn, each on owner
    rules and cards that had nothing to do with the brief). The map still rides along as context for the brief."""
    try:
        o = json.loads(out) if out.strip() else {}
    except Exception:
        return out
    h = o.get("hookSpecificOutput")
    if not h or h.get("permissionDecision") != "deny":
        return out
    reason = h.get("permissionDecisionReason", "")
    reason = re.sub(r"\n*\(?Stopped once:[^\n]*\)?", "", reason).strip()
    return json.dumps({"hookSpecificOutput": {"hookEventName": h.get("hookEventName", "PreToolUse"),
                                              "additionalContext": reason}}, ensure_ascii=False)


HAND_READ = re.compile(r"\b(grep|rg|cat|sed|head|tail|less|awk|wc|egrep)\b[^|;&]*_JOURNAL[\w.-]*\.md")


def hand_read_hint(call: dict):
    """A raw Read / cat / sed / grep of a *_JOURNAL.md is allowed, but the journal tools do it in one call and the
    dogfood report counts it as the top outside-tool move (2026-11-03: 8 of the top 10, 7 roles). Print a note that
    names the exact call with the file filled in; once per journal per user message; never blocks."""
    ti = call.get("tool_input") or {}
    fp = str(ti.get("file_path") or "")
    cmd = str(ti.get("command") or "")
    if call.get("tool_name") == "Read" and JOURNAL_MD.search(fp):
        names = [fp.replace("\\", "/").rsplit("/", 1)[-1]]
    elif cmd and not WRITE_CMD.search(cmd) and HAND_READ.search(cmd[:4000]):
        names = [x.rsplit("/", 1)[-1] for x in _names_in(cmd[:4000])]
    else:
        return
    names = [x for x in names if x and not SCRATCH_MD.search(x)][:1]
    if not names:
        return
    f, seen = _state(call)
    n = int(seen.get("n", 0))
    hh = seen.setdefault("hh", {})
    k = jkey(names[0])
    if not k or hh.get(k) == n:
        return
    hh[k] = n
    _save(f, seen)
    j = names[0]
    ctx = (f"JOURNALS: you are reading {j} by hand. The journal tools return the same text in one call and the read "
           f"counts as done: journal_read(name=\"{j}\", offset=<first line>, limit=<lines>) for a line range, "
           f"journal_read_section(\"{j}\", \"<section name>\") for one section, journal_handoff_brief(\"{j}\") "
           f"for the Handoff and rules, journal_search(\"<topic>\") to find the entry. This is a note, nothing is blocked.")
    return ctx


def _with_hint(call: dict):
    """read_turn plus the hand-read note as ONE json document: a deny is kept as is (no note), a context gets the
    note appended, no output gets the note alone (QC 2026-11-03: two documents broke json.loads, the deny could drop)."""
    import io
    from contextlib import redirect_stdout
    hint = hand_read_hint(call)
    buf = io.StringIO()
    with redirect_stdout(buf):
        read_turn(call)
    out = buf.getvalue().strip()
    if not hint:
        if out:
            print(out)
        return
    if not out:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": hint}},
                         ensure_ascii=False))
        return
    try:
        doc = json.loads(out)
        h = doc["hookSpecificOutput"]
        if "permissionDecision" not in h:
            h["additionalContext"] = (h.get("additionalContext", "") + "\n\n" + hint).strip()
        print(json.dumps(doc, ensure_ascii=False))
    except Exception:
        print(out)


def _compile_later() -> None:
    """A rules journal newer than the compiled tests: compile the new rules in the background (one file-date check per
    owner message, nothing waits on it; a lock keeps it to one run)."""
    import os
    import subprocess
    from pathlib import Path
    home = Path(_home())
    out, lock = home / "compiled_rules.json", home / "rulecompile.lock"
    try:
        if lock.exists() and time_now() - lock.stat().st_mtime < 900:
            return
        sys.path.insert(0, str(Path(__file__).parent))
        import actioncheck
        srcs = actioncheck._rule_files()
        if not srcs:
            return   # no rules journal and no JOURNAL_RULE_FILES: nothing to compile
        import judge
        if not judge.available():
            return   # compiling is the judge's work: with the judge off nothing starts and nothing is spent
        newest = max((p.stat().st_mtime for p in srcs if p.exists()), default=0)
        if out.exists() and out.stat().st_mtime >= newest:
            return
        # The rules journals change all the time (new dated entries); only a change in the RULE LINES needs a compile.
        # Hash the rule lines (a few ms) and start nothing when they are the same as last time (a compile on every
        # journal touch froze the editor of a busy 16 GB computer).
        import hashlib
        h = hashlib.sha1("\n".join(sorted(r["text"] for r in actioncheck._rules())).encode("utf-8", "replace")).hexdigest()
        hf = home / "rules_hash.txt"
        if hf.exists() and hf.read_text(encoding="utf-8").strip() == h:
            try:
                os.utime(out)  # same rules: mark the compiled tests current so the date check above stays quiet
            except OSError:
                pass
            return
        hf.write_text(h, encoding="utf-8")
        lock.write_text(str(time_now()))
        here = Path(__file__).parent
        # hidden console the children inherit (DETACHED_PROCESS opened a visible terminal per child) and the lowest
        # priority, so the machine gives it only spare time
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
            getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
        subprocess.Popen(([] if os.name == "nt" else ["nice", "-n", "19"]) + [sys.executable, str(here / "rulecompile.py"), "build"],
                         cwd=str(here), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         creationflags=flags)
    except Exception:
        pass


def time_now() -> float:
    import time
    return time.time()


def main():
    raw = sys.stdin.read() or "{}"
    call = json.loads(raw)
    # Light by design, so it can run on your own computer: it starts only when a rule LINE changed, at idle priority,
    # and a compile with nothing new reads no repo and asks no judge.
    # JOURNAL_AUTOCOMPILE=off turns it off.
    import os
    if "--prompt" in sys.argv and os.environ.get("JOURNAL_AUTOCOMPILE", "on").lower() not in ("off", "0", "false", "no"):
        _compile_later()
    if "--prompt" in sys.argv and is_notification(call.get("prompt")):
        return
    if "--prompt" in sys.argv or "--reply" in sys.argv or "--output" in sys.argv or "--stop" in sys.argv:
        return _main(call)
    agent = call.get("tool_name") in ("Agent", "Task")
    shell = call.get("tool_name") in ("Bash", "PowerShell")
    cmd = str((call.get("tool_input") or {}).get("command") or "")
    try:
        sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0])
        import cmdguard
    except ImportError:  # a copy that has not received cmdguard.py yet (code_sync installs new files late) keeps working
        cmdguard, shell = None, False
    ti_m = call.get("tool_input") or {}
    paid_text = cmd if shell else (f'{ti_m.get("mcp_tool", "")} {ti_m.get("args", "")}' if "mcp_tool" in ti_m else "")
    if cmdguard and paid_text.strip():
        paid = cmdguard._paid_re(_home())
        if paid and paid.search(paid_text):
            try:  # the owner's latest message, read only when a paid pattern matched
                import quickmap
                owner_msg = str((quickmap._quick_seen(call.get("session_id", ""))[1] or {}).get("last_msg") or "")
            except Exception:
                owner_msg = ""
            why = cmdguard.money_guard(paid_text, owner_msg, _home())
            if why:
                event("money_stop", text=paid_text[:200])
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
                return
    if shell:
        why = cmdguard.box_flood(cmd, _home())
        if why:
            event("box_flood_stop")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": why}}, ensure_ascii=False))
            return
    tm = _tools_first(call)
    if tm and tm.get("deny") and _ai_mode() == "off":
        # decided by the cheap pick model: with AI checks off it is a note, never a stop (2026-11-06)
        tm = {"note": tm["deny"]}
    if shell:
        f_r, seen_r = _state(call)
        rem = cmdguard.reminder_note(cmd, seen_r)
        if rem:
            _save(f_r, seen_r)
            event("reminder")
            if not (tm and tm.get("deny")):
                tm = {"note": rem + ("\n\n" + tm["note"] if tm and tm.get("note") else "")}
        try:  # a unit named in the command: its newest incident/pause entry (unitmap.py, 2026-11-10)
            import unitmap
            un = unitmap.command_note(call, _state, _save)
        except Exception:
            un = ""
        if un and not (tm and tm.get("deny")):
            tm = {"note": un + ("\n\n" + tm["note"] if tm and tm.get("note") else "")}
    if not tm and not agent:
        return _main(call)
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        _main(call)
    sys.stdout.reconfigure(encoding="utf-8")
    out = _merge(buf.getvalue(), tm) if tm else buf.getvalue()
    print(_soft_for_agents(out) if agent else out)


def _main(call: dict):
    prompt = "--prompt" in sys.argv
    reply = "--reply" in sys.argv
    output = "--output" in sys.argv
    stop = "--stop" in sys.argv
    if reply or output or stop:
        pass  # the AI's finished reply, or what a command returned: checked against the owner's verdicts below
    elif prompt:
        if len(str(call.get("prompt") or "").strip()) < 3:
            f, seen = _state(call)
            seen["n"] = int(seen.get("n", 0)) + 1  # a short "ok" is still a new user message
            _save(f, seen)
            try:  # an older "yes" must not outlive a newer short message (money guard, yes-gated default rules)
                import quickmap
                f_q, seen_q = quickmap._quick_seen(call.get("session_id", ""))
                short = str(call.get("prompt") or "").strip()
                seen_q["last_msg"] = short
                try:
                    import newest
                    newest.remember_msg(seen_q, short)
                except Exception:
                    pass
                f_q.write_text(json.dumps(seen_q), encoding="utf-8")
            except Exception:
                pass
            return
    else:
        ti = call.get("tool_input") or {}
        fp = str(ti.get("file_path") or ti.get("notebook_path") or "")
        if "journal_tool" in ti or "journal_read" in ti:
            return record_read(call)
        if call.get("tool_name") in ("Bash", "PowerShell") and ti.get("command"):
            why = _compiled_stop(call, str(ti.get("command")), "command")
            if why == OVERRIDE:
                return
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
                return
        if call.get("tool_name") in ("Write", "Edit", "MultiEdit", "NotebookEdit") and fp:
            wtext = str(ti.get("content") or ti.get("new_string") or ti.get("new_source") or
                        "\n".join(str(e.get("new_string") or "") for e in ti.get("edits") or []))
            why = _compiled_stop(call, wtext, "write") if not JOURNAL_MD.search(fp) else ""
            if why == OVERRIDE:
                return
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
                return
        # Every command, before it runs, against how the journals say it is done (owner 2026-11-04: a bare GitHub fetch
        # went down the read path below and the memory was never asked). actioncheck learns which commands no rule is about.
        if call.get("tool_name") in ("Bash", "PowerShell") and ti.get("command") \
                and (_ai_mode() == "all" or (_ai_mode() == "risky" and RISKY_CMD.search(str(ti.get("command"))))):
            sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0])
            import actioncheck
            try:
                import quickmap
                _, seen_c = quickmap._quick_seen(call.get("session_id", ""))
                last_c = str(seen_c.get("last_msg") or "")
                msgs_c = seen_c.get("msgs") or None
            except Exception:
                last_c, msgs_c = "", None
            why = actioncheck.check(str(ti.get("command")), str(ti.get("description") or ""), context=last_c, msgs=msgs_c)
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
                return
        # every MCP tool call (browser, posting, mail...), with the owner's latest message as its context (2026-11-04:
        # a browser launch to look for a mail the journals already had read ran with no check at all)
        if "mcp_tool" in ti:
            if not (_ai_mode() == "all" or (_ai_mode() == "risky" and RISKY_MCP.search(str(ti.get("mcp_tool"))))):
                return
            sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0])
            import actioncheck
            try:
                import quickmap
                _, seen_q = quickmap._quick_seen(call.get("session_id", ""))
                last = str(seen_q.get("last_msg") or "")
                msgs_q = seen_q.get("msgs") or None
            except Exception:
                last, msgs_q = "", None
            why = actioncheck.check_mcp(str(ti.get("mcp_tool")), str(ti.get("args") or ""), last, msgs=msgs_q)
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
            return
        # and every text written into a file (it replaced the loose secret_guard hook, owner 2026-11-04)
        if call.get("tool_name") in ("Write", "Edit", "MultiEdit", "NotebookEdit") and fp:
            sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0])
            import actioncheck
            text = ti.get("content") or ti.get("new_string") or ti.get("new_source") or \
                "\n".join(str(e.get("new_string") or "") for e in ti.get("edits") or [])
            why = actioncheck.check_write(fp, str(text))                 if _ai_mode() == "all" or (_ai_mode() == "risky" and _write_needs_judge(fp, str(text))) else ""
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}, ensure_ascii=False))
                return
        if call.get("tool_name") in READ_TOOLS or "paths" in ti or "query" in ti:
            if call.get("tool_name") == "Read" and JOURNAL_MD.search(fp):
                h = hand_read_hint(call)  # reading a journal is never gated (the mod records it after it ran)
                if h:
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": h}},
                                     ensure_ascii=False))
                return
            return _with_hint(call)
        if fp:
            if JOURNAL_MD.search(fp):
                return
            # The map of a file was already shown and passed in this session: the next edits of it go straight
            # (2026-11-06: the same 2.6-3.3 s map ran on every edit of one file). It comes back after MAP_AGAIN_S.
            import time
            f_m, seen_m = _state(call)
            if time.time() - float((seen_m.get("mapped_files") or {}).get(fp, 0)) < MAP_AGAIN_S:
                return
        elif call.get("tool_name") in ("Agent", "Task"):
            pass   # an agent brief gets the intent map (it went to read_turn before 2026-10-26 and never got one)
        elif not WRITE_CMD.search(str(ti.get("command") or "")):
            return _with_hint(call)
    here = __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0]
    sys.path.insert(0, here)
    # The MCP library reads a .env from the working folder on import; a project's .env can be locked
    # (PermissionError on gpubox 2026-10-24), and the quick map needs nothing from it.
    import os
    os.chdir(here)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _stub_fastmcp()
    import quickmap
    if reply:
        return quickmap.reply_check(call)
    if stop:
        return quickmap.stop_check(call)
    if output:
        try:  # unit states (unitmap.py, 2026-11-10) and ONE json for every output note; a copy without it keeps the old
            import unitmap
            return unitmap.output_hook(call, quickmap, _state, _save)
        except Exception:
            pass
        f, seen = _state(call)
        shown = set(seen.get("out_ids") or [])
        hit = quickmap.output_check(call, shown) | quickmap.git_eol_check(call, shown)
        if hit:
            seen["out_ids"] = sorted(shown | hit)[-300:]
            _save(f, seen)
        return
    fp = str((call.get("tool_input") or {}).get("file_path") or "") if not prompt else ""
    if not fp:
        return quickmap.quick_hook(call, prompt=prompt)
    import io
    import time
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        quickmap.quick_hook(call, prompt=prompt)
    out = buf.getvalue()
    sys.stdout.write(out)
    if '"deny"' not in out:   # only a map that let the edit through counts as shown; a stop must stay a stop
        f_m, seen_m = _state(call)
        m = dict(seen_m.get("mapped_files") or {})
        m[fp] = time.time()
        seen_m["mapped_files"] = dict(sorted(m.items(), key=lambda t: -t[1])[:200])
        _save(f_m, seen_m)


if __name__ == "__main__" and "--app" in sys.argv:
    # Other AI apps (Codex, GitHub Copilot, Cursor): adapters/ turns their hook JSON into this hook's input and runs main().
    try:
        from adapters.run import main as _app_main
        sys.exit(_app_main(sys.argv))
    except Exception:
        print("{}")
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never block the AI on a bug here, but leave a trace: a silent failure looks like "nothing recorded".
        try:
            import os
            import traceback
            from datetime import datetime, timezone
            from pathlib import Path
            log = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "quick_errors.log"
            with log.open("a", encoding="utf-8") as f:
                f.write(datetime.now(timezone.utc).isoformat(timespec="seconds") + " " + traceback.format_exc() + "\n")
        except Exception:
            pass
