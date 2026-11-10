"""Newest word wins, for every check that stops the assistant (owner 2026-11-05).

Two real misses of the same day, one root: a check stopped on an OLD line while a NEWER owner line on the same piece
said otherwise, because nothing ever looked for the newer line.
  - The command check stopped resumed demo builds citing a 2026-11-04 handoff ("the owner paused the demo work"); the
    2026-11-05 entry "DEMO VIDEO REDO, in progress (owner: let's go, finish the demos)" never reached the judge, and
    the owner's latest message ("perdon scerre sin qeure segui", sorry, closed it by accident, go on) was read alone,
    with no earlier message, and taken as "without wanting to continue".
  - The reply check called "Sound Demo: recording again" wrong citing a 2026-10-31 "shipped" entry of the OLD demo;
    the 2026-11-05 redo entry reopened it.
The evidence a check gets is found by similarity to the action or the reply, so the newest line about the piece is
not there unless it happens to look alike. Here, only when a check is about to stop: the date of the line each stop
rests on is read, the lines written AFTER it about the same piece are searched by meaning (journal entries and the
owner's own chat words), and one strong verdict says which stops still stand when the newest word wins, with the
owner's messages of this session in order. No newer line found: no call, the stop stands. No answer: the stop stands.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

HOME = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)(?:[ T](\d\d:\d\d))?")
HEAD = re.compile(r"^#{2,3} ")
# notes about the checks themselves (a mod miss, a live test) talk about the stop; they are not the owner's word on
# the piece (the same filter the quick map's NEWER WORD uses)
META = re.compile(r"\[(mod-miss|check)\]", re.I)
MSGS_KEPT = 8   # owner messages of a session kept for the checks (oldest first)

_rows: dict = {}


def _lines(path: str) -> list:
    """A journal's lines, read once per process (the big journals hold 11,000-25,000 lines)."""
    try:
        m = Path(path).stat().st_mtime
        if path not in _rows or _rows[path][0] != m:
            _rows[path] = (m, Path(path).read_text(encoding="utf-8", errors="replace").splitlines())
        return _rows[path][1]
    except Exception:
        return []


def stamp(text: str) -> str:
    """The newest 'YYYY-MM-DD HH:MM' a text names, never later than now ('' when none): a later date is a deadline or
    a plan the text names, not when it was written."""
    now = time.strftime("%Y-%m-%d %H:%M")
    found = [x for x in (d + " " + (t or "00:00") for d, t in DATE.findall(text or "")) if x <= now]
    return max(found) if found else ""


def date_at(path: str, line: int) -> str:
    """When the line was written: the newest date of its entry (its heading and the lines under it up to the next
    heading). A handoff carries it in its "written" or "Updated" line, a rule in its "(first said ..., newer ...)"."""
    rows = _lines(path)
    i = int(line or 0) - 1
    if not rows or not 0 <= i < len(rows):
        return ""
    block = [rows[i]]
    j = i
    while j > 0 and not HEAD.match(rows[j]):
        j -= 1
    if j != i:
        block.append(rows[j])
    for k in range(i + 1, min(len(rows), i + 16)):
        if HEAD.match(rows[k]):
            break
        block.append(rows[k])
    return stamp("\n".join(block))


def entry_text(path: str, line: int, n: int = 8, cap: int = 500) -> str:
    """The entry's first lines, never past the next heading (that is another entry)."""
    rows = _lines(path)
    i = max(0, int(line or 0) - 1)
    out = []
    for k, ln in enumerate(rows[i:i + n]):
        if k and HEAD.match(ln):
            break
        out.append(ln)
    return re.sub(r"\s+", " ", " ".join(out))[:cap]


def resolve(ref: str) -> tuple[str, int]:
    """'VISUAL_REVIEW_JOURNAL.md:128' (or 'journal:VISUAL_REVIEW_JOURNAL.md:128') -> (canonical path, 128); ('', 0) when not a
    journal line this machine indexes."""
    m = re.search(r"([\w.()-]+\.md):(\d+)", str(ref or ""))
    if not m:
        return "", 0
    name = m.group(1)
    try:
        c = sqlite3.connect(str(HOME / "index.sqlite"))
        rows = [r[0] for r in c.execute("select path from journals")]
        c.close()
    except Exception:
        return "", 0
    hits = sorted((p for p in rows if re.split(r"[\\/]", p)[-1] == name and Path(p).exists()), key=len)
    return (hits[0], int(m.group(2))) if hits else ("", 0)


def _after(since: str) -> list:
    """Every indexed entry written after `since` (its heading's date, else the first date of its body), with its
    meaning vector: (path, line, heading, when, vec). The newer lines are few (266 for the 21 hours after the
    2026-11-04 pause), so they are ranked among themselves; ranked among all 30,000 entries, the 2026-11-05 redo entry
    never made the top 40 for the stop's words."""
    import numpy as np
    import meaning
    c = meaning._conn()
    try:
        out = []
        for p, ln, h, b in c.execute("SELECT path, line, heading, substr(body, 1, 300) FROM entries_fts"):
            # a date later than now is a deadline or a plan named in the text, not when it was written
            when = stamp((h or "")[:20]) or stamp(b or "")
            if not when > since or META.search((h or "")[:60]):
                continue
            r = c.execute("SELECT vec FROM entries_vec WHERE path=? AND line=?", (p, int(ln))).fetchone()
            if r:
                out.append((p, int(ln), h or "", when, np.frombuffer(r[0], dtype=np.float16).astype(np.float32)))
        return out
    finally:
        c.close()


def newer_lines(path: str, line: int, about: list, k: int = 10) -> list[str]:
    """Lines written after (path, line) that are about the same piece, by meaning: journal entries and the owner's
    own chat words. about: short texts that each say what the piece is (its neutral name, what is being done or said,
    the cited line, why the check stops). Each is ranked on its own and a line keeps its best rank: short texts find
    the newer line (the reply's own words ranked the 11-05 Evo redo 2nd of 2,035 newer entries), a long stop
    explanation buries it (38th). Never raises."""
    since = date_at(path, line)
    if not since:
        return []
    try:
        import numpy as np
        import meaning
        pool = [x for x in _after(since) if not (Path(x[0]).name == Path(path).name and x[1] == line)]
        qs = [str(a)[:600] for a in about if str(a or "").strip()]
        if not pool or not qs:
            return []
        s = np.stack([x[4] for x in pool]) @ meaning.embed(qs).T          # entries x queries
        rank = np.argsort(np.argsort(-s, axis=0), axis=0).min(axis=1)    # each entry's best rank in any query
        order = sorted(range(len(pool)), key=lambda i: (int(rank[i]), -float(s[i].max())))
    except Exception:
        return []
    out = []
    for i in order[:k]:
        p, ln, _, when, _ = pool[int(i)]
        voice = meaning.VOICE in p
        txt = entry_text(p, ln, n=4 if voice else 8, cap=300 if voice else 500)
        out.append(f"[{Path(p).name}:{ln}, {when}{', owner said' if voice else ''}] {txt}")
    return out


def owner_messages(msgs) -> str:
    """The owner's messages of this session, oldest first, the latest marked."""
    msgs = [m for m in (msgs or []) if isinstance(m, (list, tuple)) and len(m) >= 2 and str(m[1]).strip()]
    return "\n".join(f"- {m[0]}{' (LATEST)' if i == len(msgs) - 1 else ''}: {str(m[1])[:400]}"
                     for i, m in enumerate(msgs))


def remember_msg(seen: dict, text: str) -> None:
    """Keep the owner's message in the session's state (local time, like the journals' headings)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return
    msgs = [m for m in seen.get("msgs") or [] if isinstance(m, list) and len(m) == 2]
    msgs.append([time.strftime("%Y-%m-%d %H:%M"), t[:600]])
    seen["msgs"] = msgs[-MSGS_KEPT:]


TASK = """A check is about to stop an AI assistant that works for a project owner. Each Stop below rests on a journal
line written at a date. Under each Stop are the lines written AFTER that one about the same piece of work: journal
entries and the owner's own chat words, each with its date. The owner's messages of this session come last, oldest
first (they may be fast and short, in any language, with typos: read the latest in the light of the earlier ones).

What the assistant is doing: {what}

{stops}

The owner's messages of this session:
{msgs}

The newest word wins. A Stop FALLS when a newer line lifts, reverses, reopens or replaces what it rests on (a pause
lifted by a later order to go on or finish it, a thing marked shipped reopened by a newer redo of it, a rule changed
later), or when the owner's messages clearly ask for this very thing. A Stop STANDS when no newer line changes what
it rests on: a newer line that only talks about the same topic, or about a different piece (another version, another
fix, another project), changes nothing.
Answer only JSON: {{"stands": [stop numbers], "fell": [{{"stop": <number>, "newer": "<journal:line or owner message>", "why": "<plain>"}}]}}"""


def recheck(stops: list, what: str, msgs=None) -> list:
    """stops: [{"text": why the check stops, "ref": the journal:line it rests on, "piece": the piece of work in
    neutral words, "subject": what the assistant does or says, short}]. Returns the indexes (0-based) of the stops that still stand. Never raises; when in doubt every
    stop stands."""
    every = list(range(len(stops)))
    try:
        blocks, newer_any = [], False
        for n, s in enumerate(stops, 1):
            path, line = resolve(s.get("ref"))
            since = date_at(path, line) if path else ""
            cited = entry_text(path, line, n=6, cap=400) if path else ""
            # short texts, each ranked on its own: the piece's neutral name, what is being done or said, the cited
            # line and the stop's reason (alone, the reason's words, "paused", find the pause again)
            about = [s.get("piece"), s.get("subject"), cited[:200], str(s.get("text") or "")[:400]]
            newer = newer_lines(path, line, about) if since else []
            newer_any = newer_any or bool(newer)
            blocks.append(f"Stop {n} (rests on {s.get('ref') or 'no journal line'}{', written ' + since if since else ''}): "
                          f"{str(s.get('text') or '')[:600]}\n  The line it rests on: {cited or '(not found)'}\n"
                          f"  Newer lines on the same piece:\n" + ("\n".join(f"  {x}" for x in newer) or "  (none)"))
        if not newer_any:
            return every
        import judge
        if not judge.available():
            return every
        prompt = TASK.format(what=str(what)[:700], stops="\n\n".join(blocks), msgs=owner_messages(msgs) or "(none)")
        mm = re.search(r"\{.*\}", judge._run(prompt, model=judge.STRONG), re.S)
        ans = json.loads(mm.group(0)) if mm else None
        if not isinstance(ans, dict) or "stands" not in ans:
            return every
        fell = {int(f.get("stop")) - 1 for f in ans.get("fell") or [] if str(f.get("stop", "")).isdigit()}
        stands = {int(x) - 1 for x in ans.get("stands") or [] if str(x).isdigit()}
        _log(stops, ans)
        return [i for i in every if i in stands or i not in fell]
    except Exception:
        return every


def _log(stops, ans) -> None:
    try:
        with (HOME / "newest_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "stops": [str(s.get("ref")) for s in stops], "ans": ans}, ensure_ascii=False) + "\n")
    except Exception:
        pass
