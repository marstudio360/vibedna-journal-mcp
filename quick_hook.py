"""Light front door for the journal quick-map hooks (PreToolUse and UserPromptSubmit).

Loading server.py costs about a second, so calls that cannot need a map (a read-only command, an edit to a
journal itself, an empty prompt) exit here at once. Everything else goes to server.py's _quick_hook.

Claude Code settings:
  PreToolUse  (Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|Read|Grep|Glob): python quick_hook.py
  UserPromptSubmit:                                                python quick_hook.py --prompt

Reads (Read, Grep, Glob, read-only commands, data queries) never load server.py: the first read inside a mapped
piece or a project folder with journals, in each user message, gets a short "read its journal first" note
(2026-10-24: an answer about AA mails came from code reading alone and was wrong; reads never triggered anything).

The gate (2026-10-24, owner: "the point of the mod is that you cannot skip it"): the first write of a mapped piece
and the first read of a mapped piece or journal folder in a session stay DENIED until the session really read that
piece's journal (journal_read, journal_read_section, journal_handoff_brief, journal_search, journal_quick, or a Read
of the *_JOURNAL.md), in the current user message or after the stop. The mod reports each journal read after it ran
(record_read, the PostToolUse side). A plain retry is denied again. Escape so it never deadlocks: on the 3rd attempt
it opens with a loud note when the journal file is not on disk or a journal read failed since the stop (logged to
gate_escapes.log). Reading journals is never gated.
"""
import json
import posixpath
import re
import sys

WRITE_CMD = re.compile(r"(?<![\w./~\\-])(ssh|scp|rsync|sed\s+-i|tee|cp|mv|crontab|systemctl|git\s+push)(?![\w./\\-])|(?<![0-9&>])>{1,2}(?!&)\s*(?!/dev/null\b|\$null\b|nul\b)[^\s&|;]")

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
            # gmail tool in TOOL SHOP/servers/gmail-mcp was stopped 6 times for JOURNAL_MCP_JOURNAL.md)
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
    if call.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell", "Agent", "Task") \
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


def main():
    raw = sys.stdin.read() or "{}"
    call = json.loads(raw)
    if "--prompt" in sys.argv and is_notification(call.get("prompt")):
        return
    if "--prompt" in sys.argv or "--reply" in sys.argv or "--output" in sys.argv or "--stop" in sys.argv:
        return _main(call)
    agent = call.get("tool_name") in ("Agent", "Task")
    tm = _tools_first(call)
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
            return
    else:
        ti = call.get("tool_input") or {}
        fp = str(ti.get("file_path") or ti.get("notebook_path") or "")
        if "journal_tool" in ti or "journal_read" in ti:
            return record_read(call)
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
        f, seen = _state(call)
        shown = set(seen.get("out_ids") or [])
        hit = quickmap.output_check(call, shown) | quickmap.git_eol_check(call, shown)
        if hit:
            seen["out_ids"] = sorted(shown | hit)[-300:]
            _save(f, seen)
        return
    quickmap.quick_hook(call, prompt=prompt)


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
