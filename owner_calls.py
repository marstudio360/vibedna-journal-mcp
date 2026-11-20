"""End-of-turn check with no AI: what the reply puts on the owner, and what it promises (owner 2026-11-11, after a
report listed as "waiting for your yes" mails and audit calls that a Decided card and an owner order give to the
Director: "the mod has to stop you, without spending credit or slowing you down").

Two tests, milliseconds, no model call:
- ASK: a line that hands something to the owner ("waits for your yes", "your call", "con vos", a red blocked mark) is
  matched against the Decided cards of every journal by words. A card on that subject that gives it to someone else
  (the Director, the Owner Proxy, "never an owner card", full delegation) sends the reply back.
- PROMISE: "from now on" / "desde ahora" in the reply while nothing was written to a journal, rule or memory file in
  this turn: a promise in chat does not survive the session, so it goes back to be written or withdrawn.
- LEARN (2026-11-16, the missing link of the learning loop): the owner's own message corrected the session or set a
  direction ("no me gusta", "tiene que ser", "siempre", an angry long message) and no journal was written in that turn.
  His words are kept by the owner voice journal, but a rule exists only when it is written where the project's sessions
  read it; until this test that depended on the session remembering. The reply goes back once to write it.
  JOURNAL_OWNER_LEARN=off turns this test alone off.
JOURNAL_OWNER_CALLS=off turns it off. Never raises."""
from __future__ import annotations

import json
import os
import re

ASK = re.compile(
    r"esper\w*\s+(?:tu|el)\s+s[ií]|\btu\s+s[ií]\b|\bcon\s+vos\b|decid[ií]s\s+vos|\blo\s+decid[ií]s\b|te\s+toca\s+decidir|"
    r"^\s*-\s*\[\s\]\s*🔴|blocked\s+by\s+the\s+owner|waits?\s+(?:for\s+)?(?:your|the\s+owner'?s)\s+(?:yes|go|ok|call|decision)|"
    r"owner\s+(?:decides|needed|must\s+decide)|\byour\s+call\b|needs?\s+(?:your|the\s+owner'?s)\s+(?:yes|go|ok)",
    re.I)
# who decides, not a mention of the Director (2026-11-11: "live Director chat" in a branding card was a false stop)
DELEGATED = re.compile(
    r"(?:approved|decided|reviewed|signed)\s+by\s+the\s+director|director\s+(?:decides|approves|reviews|signs)|"
    r"decided\s+for\s+you|owner\s+proxy|never\s+(?:an?\s+)?owner\s+card|without\s+(?:the\s+)?owner'?s?\s+(?:review|yes|approval)|"
    r"no\s+owner\s+(?:review|approval|card)|full\s+delegation|free\s+rein|no\s+approvals?", re.I)
OWNER_WORDS = {"owner", "the owner", "me", "user", "the user", "you", "yo", "dueño", "el dueño", "owner only"}
# an ask phrase only QUOTED (a reply describing the check, a rule cited) is not an ask (2026-11-11 false stops)
QUOTED = re.compile(r'["“«][^"”»\n]{0,80}["”»]')
# A whole line of product copy shown for the owner's verdict is quoted too, and it is longer than a phrase (2026-11-16
# false alarm: a 104 character quoted line of page text with "from now on" in it was read as the session's promise).
QUOTED_LONG = re.compile(r'["“«][^"”»\n]{0,400}["”»]')
PROMISE =re.compile(r"desde\s+ahora|de\s+ahora\s+en\s+m[aá]s|a\s+partir\s+de\s+ahora|from\s+now\s+on|going\s+forward|"
                     r"nunca\s+m[aá]s|never\s+again", re.I)
# a write in this turn that keeps a promise: journal tools, or an edit of a rules or memory file
KEEPS = re.compile(r"journal_(?:append|decision_add|update_section|capability_add)|log_mistake|mirror__note", re.I)
RULE_FILE = re.compile(r"CLAUDE\.md|AGENTS\.md|MEMORY\.md|OWNER_SAID_JOURNAL\.md|\w*RULES_JOURNAL\.md|/memory/", re.I)
ASK_WORDS = re.compile(ASK.pattern + r"|\b(?:dale|yes|go|sí|si|owner|waits?|esperan?|decide[sn]?|blocked)\b", re.I)


# ---- LEARN: the owner's message carries a correction or a direction ----
# Whole words, in the message as typed (accents folded).
DIRECTION = re.compile(
    r"\b(?:siempre|nunca|jamas|always|never)\b|\bno (?:pongas|digas|uses|hagas|toques|mandes|nombres|repitas|quiero)\b|"
    r"\bya (?:te |se )?(?:lo |la )?dije\b|\bte dije\b|\bi (?:already )?told you\b|"
    r"\bi (?:do not|don'?t) (?:like|want)\b|\b(?:has|have) to be\b|\bmust (?:be|not)\b", re.I)
# He types fast and splits words anywhere ("no megust", "tine qser", "quiero q ese"): the same phrases with every space
# taken out of the message. Kept to stems that are a direction on their own.
DIRECTION_TIGHT = re.compile(r"nomegust|nomeconven|nomecierr|noquier|quieroq|tieneq|tineq|tienenq|tieneser|hayq|"
                             r"paranosotros|noparaelclient|nomedes|dejadedar|idontlike|hastobe")
ANGRY = re.compile(r"pelotud|peltud|bolud|mierd|meird|\bhdp\b|hijo ?de ?put|la ?concha|carajo|idiota", re.I)
# rows that look like a user message and are not the owner typing
NOT_OWNER = re.compile(r"^\s*(?:\[SYSTEM NOTIFICATION|<task-notification|Another \w+ session sent|<cross-session-message|"
                       r"\[Request interrupted|This session is being continued|You are [A-Z][A-Z0-9-]* )")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
JOURNAL_FILE = re.compile(r"_JOURNAL[\w.-]*\.md|JOURNAL\.md", re.I)


def _fold(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def is_direction(msg: str) -> bool:
    """True when the owner's message corrects or sets a direction. Words only, no AI: a miss costs nothing new (the
    session may still write it), a false hit costs one short send-back."""
    t = _fold(msg)
    words = len(t.split())
    if words < 4 or len(t) > 4000:
        return False
    if DIRECTION.search(t) or DIRECTION_TIGHT.search(re.sub(r"[^a-z0-9]+", "", t)):
        return True
    return words >= 8 and bool(ANGRY.search(t))


def _tail_rows(transcript: str, max_bytes: int = 3_000_000, last: int = 600) -> list[dict]:
    """The last rows of the session record without reading the whole file (a long session is tens of MB)."""
    rows = []
    with open(transcript, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        data = fh.read()
    lines = data.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]   # the first line is cut in the middle
    for ln in lines[-last:]:
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln.decode("utf-8", "replace")))
        except Exception:
            continue
    return rows


def _owner_turn(transcript: str) -> tuple[str, float, list[tuple[str, str]]]:
    """(the owner's last typed message, when it was sent as epoch seconds or 0, the tool calls after it)."""
    try:
        rows = _tail_rows(transcript)
    except Exception:
        return "", 0.0, []
    msg, at, tools = "", 0.0, []
    for r in rows:
        m = r.get("message") or {}
        content = m.get("content")
        if r.get("type") == "user":
            if isinstance(content, str):
                texts = [content]
            else:
                texts = [c.get("text", "") for c in (content or []) if isinstance(c, dict) and c.get("type") == "text"]
            text = _REMINDER.sub(" ", "\n".join(texts)).strip()
            if not text or NOT_OWNER.match(text):
                continue
            msg, tools = text[:4000], []
            try:
                from datetime import datetime
                at = datetime.fromisoformat(str(r.get("timestamp") or "").replace("Z", "+00:00")).timestamp()
            except Exception:
                at = 0.0
            continue
        if r.get("type") != "assistant" or not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                inp = c.get("input") or {}
                tools.append((str(c.get("name") or ""), str(inp.get("file_path") or inp.get("command") or "")[:300]))
    return msg, at, tools


SHARED_RULES = re.compile(r"OWNER_SAID_JOURNAL|RULES_JOURNAL", re.I)
# never proof that the session wrote the rule: the owner voice journal changes with every message of his, by itself
NOT_A_WRITE = re.compile(r"OWNER_VOICE|\.bak", re.I)
IN_PLAY_S = 3 * 3600   # a journal this session read or touched in the last hours is one it works on


def _journal_paths(session: str = "") -> list[str]:
    """The journals this session read or touched, plus the shared rule journals. Every journal when the session read
    none (no scope). Another session writing its own journal at the same minute must not count as this one's write."""
    try:
        from quickmap import _project_journals, _quick_seen, _jkey
        every = [(n, str(p)) for n, p in _project_journals()]
        every = [(n, p) for n, p in every if not NOT_A_WRITE.search(n)]
        mine = set()
        if session:
            import time
            now = time.time()
            touched = _quick_seen(session)[1].get("jt") or {}
            mine = {k for k, t in touched.items() if now - float(t or 0) < IN_PLAY_S}
        if not mine:
            return [p for _, p in every]
        return [p for n, p in every if _jkey(n) in mine or SHARED_RULES.search(n)]
    except Exception:
        return []


_ENTRY_HEAD = re.compile(r"^## (\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})\s*\[([^\]]{1,40})\]", re.M)
OWNER_ENTRY_TAGS = {"correction", "decision", "owner-order", "owner-said", "owner", "rule", "verdict", "owner-decision"}
_ABOUT_OWNER = re.compile(r"\bowner\b|\bdue[nñ]o\b", re.I)


def _owner_entry_since(path: str, at: float) -> bool:
    """A dated entry at the end of this journal, written after the owner's message, that is about him: its tag is a
    correction, decision, rule or order, or its first lines name the owner. Entry times are local, to the minute."""
    import time
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 16000))
        tail = fh.read().decode("utf-8", "replace")
    heads = list(_ENTRY_HEAD.finditer(tail))
    for k, m in enumerate(heads):
        y, mo, d, h, mi = (int(m.group(n)) for n in range(1, 6))
        try:
            when = time.mktime((y, mo, d, h, mi, 59, 0, 0, -1))   # the end of that minute
        except Exception:
            continue
        if when < at - 5:
            continue
        end = heads[k + 1].start() if k + 1 < len(heads) else len(tail)
        if m.group(6).strip().lower() in OWNER_ENTRY_TAGS:
            return True
    return False


def _journal_written_since(at: float, session: str = "") -> bool:
    """A journal of this session's projects got a new entry about the owner since his message, however it was written
    (a journal tool, an edit, a script). A file that only changed does not count: another session may have added its
    own entry to the same journal in the same minutes."""
    for p in _journal_paths(session):
        try:
            if os.path.getmtime(p) >= at - 2 and _owner_entry_since(p, at):
                return True
        except OSError:
            continue
    return False


def _learn(transcript: str, session: str = "") -> str:
    """'' or the line that sends the reply back: his message set a direction and nothing reached a journal."""
    if not transcript or os.environ.get("JOURNAL_OWNER_LEARN", "").lower() in ("off", "0", "false", "no"):
        return ""
    msg, at, tools = _owner_turn(transcript)
    if not msg or not at or not is_direction(msg):
        return ""   # no timestamp: never guess, the reply passes
    if any(KEEPS.search(n) or (n in ("Edit", "Write") and (RULE_FILE.search(a) or JOURNAL_FILE.search(a)))
           or (n in ("Bash", "PowerShell") and JOURNAL_FILE.search(a)) for n, a in tools):
        return ""
    if _journal_written_since(at, session):
        return ""
    said = " ".join(msg.split())[:200]
    try:   # every send-back is kept, so right ones and wrong ones can be counted in real use
        import time
        from pathlib import Path
        log = Path(os.environ.get("JOURNAL_HOME") or str(Path.home() / ".journal")) / "owner_learn_log.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "session": session[:80],
                                 "msg": said}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return (f'- the owner\'s message corrected you or set a direction ("{said}") and no journal was written this turn: his '
            'words alone do not reach the next session. Save it now: his words and the rule in one line, as a [correction], '
            '[decision], [rule] or [owner-order] entry (that tag: the owner brief reads those first) in the journal of the '
            'project this talk is about (a rule on how to work '
            'with him goes to your rules journal), then tell him in one line that it is saved. If the message truly carries '
            'nothing to keep, say that in one line instead.')


def _turn_tools(transcript: str) -> list[tuple[str, str]]:
    """(tool name, file or command) of every tool call since the owner's last message. [] when unreadable."""
    try:
        with open(transcript, encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh.readlines()[-400:] if ln.strip()]
    except Exception:
        return []
    out = []
    for r in rows:
        msg = r.get("message") or {}
        content = msg.get("content")
        if r.get("type") == "user" and (isinstance(content, str) or any(
                isinstance(c, dict) and c.get("type") == "text" for c in (content or []))):
            out = []   # a real owner message starts the turn again
            continue
        if r.get("type") != "assistant" or not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                inp = c.get("input") or {}
                out.append((str(c.get("name") or ""), str(inp.get("file_path") or inp.get("command") or "")[:300]))
    return out


def _delegated_cards(line: str) -> list[dict]:
    """Decided cards on the subject of the line that give it to someone other than the owner."""
    try:
        from server import _SEC_DECIDED, _match_capabilities
        q = ASK_WORDS.sub(" ", line)
        cards = _match_capabilities(q, limit=8, min_cover=2, sections=_SEC_DECIDED)
    except Exception:
        return []
    keep = []
    for c in cards:
        if str(c.get("what", "")).upper().startswith("SUPERSEDED"):
            continue
        who = str(c.get("decides") or c.get("decide") or "").strip().lower()
        if who:   # the card says who decides (journal_decision_add decides=): read it, never guess
            if who not in OWNER_WORDS:
                keep.append(c)
            continue
        # older cards without the field: our own wording of a delegation
        if DELEGATED.search(" ".join(str(c.get(k, "")) for k in ("what", "why", "detail"))):
            keep.append(c)
    return keep[:2]


def check(reply: str, transcript: str = "", session: str = "") -> str:
    """'' when the reply is fine; else the send-back text."""
    if os.environ.get("JOURNAL_OWNER_CALLS", "").lower() in ("off", "0", "false", "no"):
        return ""
    try:
        bad = []
        for line in reply.splitlines():
            if not ASK.search(QUOTED.sub(" ", line)) or len(line.strip()) < 15:
                continue
            for c in _delegated_cards(line):
                bad.append(f'- your line: "{line.strip()[:220]}"\n  Decided ({c.get("journal", "")}, {c.get("date", "")}): '
                           f'{str(c.get("what", ""))[:320]}')
        unquoted = QUOTED_LONG.sub(" ", reply)   # a quoted "desde ahora" describes a promise, it does not make one
        m = PROMISE.search(unquoted)
        if m:
            tools = _turn_tools(transcript) if transcript else []
            kept = any(KEEPS.search(n) or (n in ("Edit", "Write") and RULE_FILE.search(arg)) for n, arg in tools)
            if transcript and not kept:
                s = unquoted[max(0, m.start() - 80): m.end() + 120].replace("\n", " ")
                bad.append(f'- you promised "...{s.strip()}..." but wrote no rule this turn: a chat promise does not '
                           f'survive the session. Write it (journal_decision_add, or your rules journal) or take it back.')
        try:
            learn = _learn(transcript, session)
        except Exception:
            learn = ""
        if learn:
            bad.append(learn)
        if not bad:
            return ""
        from quickmap import FIX_ONLY
        cards = "A Decided card gives these to someone else: do not put them on the owner. " if any(
            "Decided (" in b for b in bad) else ""
        return "OWNER CALLS CHECK (no AI) OF THE REPLY YOU JUST GAVE:\n" + "\n".join(bad) + "\n" + cards + FIX_ONLY
    except Exception:
        return ""
