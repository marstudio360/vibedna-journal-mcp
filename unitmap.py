"""Units: a systemd service or timer, or a cron script, named in a command or in what it returned, gets its newest
state entry from the journals (incident, pause, kill switch, resume) and the line that a running timer proves nothing.

Why (a real case): `systemctl list-timers | grep warmer` showed pw-warmer@shop.timer firing and the AI told the
owner "comments running"; the unit's own log said "kill switch: STOP exists" since an incident a week before. The
output check mapped identifiers to owner verdicts only, nothing from a unit name to the piece's incident or STOP state.

No AI and no server import: one literal FTS search per unit name in the shared index, once per session per unit.
"""
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

UNIT = re.compile(r"(?<![\w@.-])([A-Za-z0-9][\w.-]*?(?:@[\w.-]*?)?)\.(service|timer|socket|path)(?![\w-])")
# `systemctl status pw-warmer@shop`, `journalctl -u pw-warmer@shop -n 20`: a unit named without its suffix
UNIT_ARG = re.compile(r"\b(?:systemctl(?:\s+--\S+)*\s+(?:status|start|stop|restart|reload|enable|disable|is-active|"
                      r"is-enabled|cat|show|kill|mask|unmask)(?:\s+--\S+)*|journalctl\b[^|;&\n]*?(?:-u|--unit=?))\s*"
                      r"([A-Za-z0-9][\w.@-]+)")
CRON_LINE = re.compile(r"^\s*(?:@(?:reboot|hourly|daily|weekly|monthly|yearly|annually)|(?:[\d*/,-]+\s+){4}[\d*/,-]+)"
                       r"\s+(.+)$", re.M)
SCRIPT = re.compile(r"([A-Za-z0-9][\w-]{2,})\.(?:sh|py|js|mjs|ts)\b")
STATE_FTS = ('(incident OR pause OR paused OR pausing OR "kill switch" OR killswitch OR stop OR stopped OR disabled '
             'OR halted OR banned OR suspended OR resumed OR resume OR unpaused OR reenabled OR "re enabled")')
STATE_RE = re.compile(r"\[(?:incident|pause|paused|stop|kill|resume|resumed|outage)\]|kill[ -]?switch|\bSTOP\b|"
                      r"\b(?:paused|pausing|stopped|disabled|halted|banned|suspended|resumed|unpaused|re-?enabled)\b",
                      re.I)
# notes about the mod itself retell incidents second hand; they are never the piece's state (as in newest.py)
META_TAGS = {"mod-miss", "check", "test"}
HEAD_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?")
MAX_UNITS = 4


def _fold(w: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", str(w).lower()) if unicodedata.category(ch) != "Mn")


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def units_in(text: str, command: bool = False) -> list:
    """[(shown name, kind, stem, instance)] for each unit or cron script named in the text, first seen first."""
    out, seen = [], set()

    def add(shown: str, kind: str, base: str):
        stem, _, inst = base.lower().partition("@")
        if not any(len(p) >= 4 and not p.isdigit() for p in re.split(r"[-_.]", stem)) or base.lower() in seen:
            return
        seen.add(base.lower())
        out.append((shown, kind, stem, inst))

    t = str(text or "")[-60000:]
    for m in UNIT.finditer(t):
        add(m.group(0), m.group(2), m.group(1))
    if command:
        for m in UNIT_ARG.finditer(t):
            base = re.sub(r"\.(service|timer|socket|path)$", "", m.group(1))
            add(m.group(1), "timer" if m.group(1).endswith(".timer") else "service", base)
    for line in CRON_LINE.finditer(t):
        for s in SCRIPT.finditer(line.group(1)):
            add(s.group(0), "cron", s.group(1))
    return out


def _rows() -> list:
    try:
        return json.loads((_home() / "quick_rows.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def _piece(stem: str, rows: list):
    """The Brain map row whose key names the unit's stem ("warmer" in "pw-warmer"), or None."""
    s = _fold(stem)
    for r in rows:
        for k in r.get("keys") or []:
            if len(k) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", s):
                return r
    return None


def _connect():
    return sqlite3.connect(str(_home() / "index.sqlite"), timeout=5)


def newest_state(stem: str, inst: str = "", conn=None):
    """The newest dated entry that names the unit literally and says incident / pause / kill switch / resume:
    {when, journal, line, heading, said} or None. With an instance (pw-warmer@shop), entries naming it win."""
    words = [w for w in re.split(r"[-_.]", stem) if w]
    if not words:
        return None
    phrase = '"' + " ".join(words) + '"'
    lit = re.compile(r"(?<![\w-])" + r"[-_ ]".join(re.escape(w) for w in words) + r"(?![\w-])")
    try:
        c = (conn or _connect)()
        try:
            names = dict(c.execute("SELECT path, name FROM journals").fetchall())
            rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 400",
                             (f"{phrase} AND {STATE_FTS}",)).fetchall()
        finally:
            c.close()
    except Exception:
        return None
    best = []
    for path, line, heading, body in rows:
        m = HEAD_DATE.match(heading or "")
        text = f"{heading or ''}\n{body or ''}"
        if not m or not lit.search(_fold(text)) or not STATE_RE.search(text):
            continue
        tag = re.match(r"^\S+(?:\s+\d{2}:\d{2})?\s*\[([^\]]+)\]", heading or "")
        if tag and tag.group(1).strip().lower() in META_TAGS:
            continue
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body or "") if s.strip()]
        named = next((s for s in sents if STATE_RE.search(s) and lit.search(_fold(s))), "")
        # A state entry: its heading says the state ([incident], paused, kill switch...), or one sentence names the
        # unit AND a state. A long entry that names the unit in one place and "disabled" about something else in
        # another is not (a smoke test: logrotate.timer got an unrelated [fix] entry).
        if not (STATE_RE.search(heading or "") or named):
            continue
        said = named or next((s for s in sents if STATE_RE.search(s)), "")
        has_inst = bool(inst) and inst in _fold(text)
        best.append((has_inst, m.group(1) + " " + (m.group(2) or "00:00"), names.get(path, Path(path).name),
                     int(line), (heading or "")[:160], said[:260]))
    if not best:
        return None
    best.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, when, j, ln, head, said = best[0]
    return {"when": when, "journal": j, "line": ln, "heading": head, "said": said}


def _log_line(shown: str, kind: str, stem: str, inst: str) -> str:
    if kind == "cron":
        return (f"A cron line is not proof the job works: check its log (the output or log file of {shown}) before "
                "saying it runs.")
    unit = (stem + ("@" + inst if inst else "")) + ".service"
    return (f"A running timer is not proof the job works: check its log (journalctl -u {unit} -n 20) before saying "
            "it runs.")


def note(text: str, shown_ids: set, command: bool = False, conn=None) -> tuple:
    """(note text or "", ids to remember) for a command or its output. Once per session per unit (ids "unit:<name>")."""
    found = [u for u in units_in(text, command) if f"unit:{u[2]}@{u[3]}" not in shown_ids][:12]
    if not found:
        return "", set()
    rows = _rows()
    lines, ids = [], set()
    for shown, kind, stem, inst in found:
        st = newest_state(stem, inst, conn)
        row = _piece(stem, rows)
        if not st and not row:
            continue
        who = f' (piece "{row["piece"]}", read first {row.get("read", "")[:120]})' if row else ""
        if st:
            body = (f"newest state entry {st['when']}, {st['journal']}:{st['line']}: {st['heading']}"
                    + (f' | "{st["said"]}"' if st["said"] and st["said"] not in st["heading"] else ""))
        else:
            body = "no incident, pause or kill switch entry names it in the journals"
        lines.append(f"- {shown}{who}: {body}\n  {_log_line(shown, kind, stem, inst)}")
        ids.add(f"unit:{stem}@{inst}")
        if len(lines) >= MAX_UNITS:
            break
    if not lines:
        return "", set()
    return ("UNITS NAMED HERE (a service, timer or cron job of a piece): the newest state entry in the journals wins "
            "over a timer that fires. Check it live before you report it as running:\n" + "\n".join(lines)), ids


def command_note(call: dict, state, save) -> str:
    """PreToolUse side: a shell command that names a unit (systemctl status x.timer, journalctl -u x)."""
    cmd = str((call.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return ""
    f, seen = state(call)
    shown = set(seen.get("out_ids") or [])
    text, ids = note(cmd, shown, command=True)
    if ids:
        seen["out_ids"] = sorted(shown | ids)[-300:]
        save(f, seen)
    return text


def output_hook(call: dict, quickmap, state, save) -> None:
    """--output side: the owner's verdicts on names in the output (quickmap.output_check), the line-ending check
    (git_eol_check) and the unit states, printed as ONE json document (two documents, or a JSON plus a plain line,
    made the mod's JSON.parse fail and the whole note was lost)."""
    import io
    from contextlib import redirect_stdout
    f, seen = state(call)
    shown = set(seen.get("out_ids") or [])
    buf = io.StringIO()
    with redirect_stdout(buf):
        hit = quickmap.output_check(call, shown) | quickmap.git_eol_check(call, shown)
    try:
        u_text, u_ids = note(str(call.get("output") or ""), shown | hit, conn=quickmap._conn)
    except Exception:
        u_text, u_ids = "", set()
    hit |= u_ids
    parts = []
    for ln in buf.getvalue().splitlines():
        if not ln.strip():
            continue
        try:
            doc = json.loads(ln)
            parts.append(str((doc.get("hookSpecificOutput") or {}).get("additionalContext") or ""))
        except Exception:
            parts.append(ln)
    if u_text:
        parts.append(u_text)
    parts = [p for p in parts if p.strip()]
    if hit:
        seen["out_ids"] = sorted(shown | hit)[-300:]
        save(f, seen)
    if parts:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": "\n\n".join(parts)}}, ensure_ascii=False))
