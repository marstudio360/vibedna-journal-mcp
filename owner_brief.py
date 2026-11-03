"""The owner brief: what the owner corrected, decided and already saw fail in one project, kept by the judge model.

Why (owner 2026-11-03, PC chat, after a session re-proposed a lever the lab had lost the day before and answered
"we are going in circles" as if it were news): "the mod is supposed to be intelligent, it has to keep the context
always; I am tired of correcting it by hand". The per-message map picked the newest owner lines by word rules, so
the 02/11 correction ("you always give me the same loop") never showed; an angry vague message fell under the
meaning floor and got nothing at all.

So each project journal gets a short brief written by the judge model from its Decided cards, its owner
corrections / decisions / verdicts of the last weeks and its open Handoff items. It is rebuilt in the background
whenever those sources change (a hash of them), and the hooks read the cached text:
  - prompt: the brief of every project in play (journals read in this session, or the message's journals) is shown
    the first time in a session and every BRIEF_EVERY messages; in between, the judge picks the brief lines that
    apply to the message (an owner saying "I already told you" gets the lines about what he told).
  - stop: the assistant's finished reply is judged against the brief; a reply that re-proposes what the owner
    rejected or already saw lose is sent back for a rewrite before the turn ends (stop_check).
Without a judge (JOURNAL_JUDGE off) the brief is the Decided one-liners plus the last correction headings.
CLI: python owner_brief.py --build <journal path>   (rebuild one brief now, used for the background rebuild)
     python owner_brief.py --show <journal path>    (print the cached brief, building it when missing)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))
DIR = HOME / "owner_briefs"
DAYS = int(os.environ.get("JOURNAL_BRIEF_DAYS") or 21)
VERSION = "3"  # bump when PROMPT changes: every brief is written again
BRIEF_EVERY = 8  # messages: the whole brief comes back this often for a project in play
_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?\s*(?:\[([\w-]+)\])?(.*)$")
_OWNER_TAGS = {"correction", "decision", "verdict", "rule", "owner", "lesson"}
_OWNER_QUOTE = re.compile(r"\b(?:owner|due[nñ]o)\b[^\n]{0,60}?[\"“]", re.I)


def _key(path: str) -> str:
    base = re.sub(r"\.md$", "", Path(path).name, flags=re.I).lower()
    return "".join(w for w in re.split(r"[^a-z0-9]+", base) if w and w != "journal")


def _section(text: str, name_rx: str) -> str:
    m = re.search(r"^## [^\n]*" + name_rx + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S | re.I)
    return m.group(1) if m else ""


def collect(path: str) -> tuple[str, list[str], list[str]]:
    """(source text for the model, decided one-liners, correction headings) of one journal."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", [], []
    decided = []
    for ln in _section(text, r"Decided").splitlines():
        if ln.startswith("- "):
            m = re.match(r"- \*\*(.+?)\*\*(.*)", ln)
            what = m.group(1) if m else ln[2:]
            date = re.search(r"· date: ([\d-]+)", ln)
            decided.append((f"[{date.group(1)}] " if date else "") + what[:700])
    handoff = [ln.strip() for ln in _section(text, r"Handoff").splitlines() if ln.strip().startswith("- [ ]")][:8]
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - DAYS * 86400))
    entries, heads = [], []
    parts = re.split(r"(?m)^(?=## \d{4}-\d{2}-\d{2})", text)
    for p in parts:
        m = _HEAD.match(p.split("\n", 1)[0])
        if not m or m.group(1) < cutoff:
            continue
        tag = (m.group(3) or "").lower()
        body = p.split("\n", 1)[1] if "\n" in p else ""
        body = body.split("\n---", 1)[0].strip()
        if tag in _OWNER_TAGS or _OWNER_QUOTE.search(body[:1500]):
            when = f"{m.group(1)} {m.group(2) or ''}".strip()
            entries.append(f"### {when} [{tag}] {m.group(4).strip()[:160]}\n{body[:1100]}")
            if tag in ("correction", "decision", "verdict", "rule"):
                heads.append(f"[{when}] [{tag}] {m.group(4).strip()[:200]}")
    entries = entries[-30:]
    src = ("DECIDED (owner decisions, standing):\n" + "\n".join(f"- {d}" for d in decided)
           + "\n\nOPEN HANDOFF ITEMS:\n" + "\n".join(handoff)
           + f"\n\nOWNER CORRECTIONS, DECISIONS, VERDICTS AND OWNER QUOTES OF THE LAST {DAYS} DAYS (oldest first):\n"
           + "\n\n".join(entries))
    return src, decided, heads[-6:]


PROMPT = """You keep the memory of a solo founder's project for the AI sessions that work on it.
From the journal excerpts below, write the OWNER BRIEF of the project "{name}": what every session must have in
mind before it answers the owner or proposes anything. The owner hates repeating himself and hates sessions that
propose again what was already tried, or that keep measuring and reporting instead of changing something.

Write at most 16 lines, English, at most 240 characters each, each with its date (dd/mm), each starting with its kind:
- RULE [dd/mm] the owner's standing corrections and rules, in his own words where you have them (short quote). A
  newer correction wins over an older one; drop what a newer entry reversed. Keep the newest Decided wording whole.
- LOST [dd/mm] what was already tried and lost or rejected: say the IDEA in plain words (what it tried to change and
  why, e.g. "bigger orders to earn more premium") and then its name and the number that killed it, so the same idea
  with another number or name is recognized too. One idea per line.
- OPEN [dd/mm] the thread that is open right now: what is running, what result is awaited and when, what the owner
  already approved. At most 3 OPEN lines.
No infrastructure trivia, no file paths, no md5s, no state that changes by the hour. Plain words. Output only the
lines, each starting with "- RULE", "- LOST" or "- OPEN".

EXCERPTS:
{src}"""


def _paths(key: str) -> tuple[Path, Path]:
    return DIR / f"{key}.json", DIR / f"{key}.lock"


def load(path: str) -> dict:
    try:
        return json.loads(_paths(_key(path))[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(path: str) -> dict:
    """Write the brief of one journal now (slow: one model call); returns the cached record."""
    src, decided, heads = collect(path)
    if not src:
        return {}
    h = hashlib.sha1((VERSION + src).encode("utf-8")).hexdigest()
    old = load(path)
    if old.get("hash") == h and old.get("by") == "judge":
        return old
    import judge
    name = re.sub(r"_JOURNAL.*$", "", Path(path).stem, flags=re.I).replace("_", " ")
    text = judge.complete(PROMPT.format(name=name, src=src[-60000:]), timeout=180)
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("- ")][:16]
    rec = {"hash": h, "t": time.time(), "path": str(path)}
    if lines:
        rec.update(by="judge", lines=[ln.replace("\u2014", "; ").replace("\u2013", "-") for ln in lines])
    else:
        rec.update(by="rules", lines=[f"- RULE {d[:240]}" for d in decided[:6]] + [f"- RULE {x}" for x in heads])
    DIR.mkdir(parents=True, exist_ok=True)
    f, _ = _paths(_key(path))
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return rec


def _rebuild_later(path: str) -> None:
    """Start a background rebuild once (a lock younger than 10 minutes means one is running)."""
    _, lock = _paths(_key(path))
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < 600:
            return
        DIR.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(time.time()), encoding="utf-8")
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "cwd": str(Path(__file__).parent)}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, str(Path(__file__)), "--build", str(path)], **kw)
    except Exception:
        pass


def lines_for(path: str) -> list[str]:
    """The brief lines to show now: the cached ones (rebuilt in the background when the sources changed), or the
    rule-made lines while the first build runs."""
    rec = load(path)
    src, decided, heads = collect(path)
    if not src:
        return []
    h = hashlib.sha1((VERSION + src).encode("utf-8")).hexdigest()
    if rec.get("hash") != h or rec.get("by") != "judge":
        import judge
        if judge.available():
            _rebuild_later(path)
        elif rec.get("hash") != h:
            rec = {}
    if rec.get("lines"):
        return rec["lines"]
    return [f"- RULE {d[:240]}" for d in decided[:6]] + [f"- RULE {x}" for x in heads]


def brief_text(path: str, lines: list[str] = None, partial: bool = False) -> str:
    lines = lines if lines is not None else lines_for(path)
    if not lines:
        return ""
    name = Path(path).name
    head = (f"OWNER BRIEF, {name} (the lines of it that apply to this message)" if partial else
            f"OWNER BRIEF, {name}: what the owner corrected, decided and already saw fail. Follow it; never propose "
            "again what it lists as tried or rejected; when the owner says he already said something, it is here")
    return head + ":\n" + "\n".join(lines)


PROMPT_TASK = ("You decide which lines of a project's owner brief apply to the owner's new message, so the AI answering "
               "him has them in mind. The message may be fast Spanish with typos, angry, or vague. A line applies when "
               "the message is about its topic, OR when the owner complains that something repeats, that he already "
               "said it, that the AI goes in circles or does not listen: then every correction about repeating, looping, "
               "or what was already tried applies. When the owner asks how things are going, what is new or where we are, the OPEN lines apply.")

STOP_TASK = """You check an AI assistant's reply to a project owner against the owner's rules (RULE) and the list of
what was already tried and lost (LOST). A line is broken only when the reply itself PROPOSES or ASKS TO DO again
something a LOST line names (the same idea counts with another number, size or name: "orders of 100" is the idea
"bigger orders" that lost at 40), or does what a RULE forbids (for example: it reports a gap and proposes one more paper
variant or one more measurement when the owner banned that loop). Reporting results, describing what was fixed,
sharing the topic, or naming a lost idea to say it lost is NOT a break. Following the open thread below is NOT a break
(growing what it says to grow is not "bigger orders"). A proposal the reply calls new but that uses the mechanism of a
LOST line IS a break. When in doubt, it is not a break.

THE OPEN THREAD THE OWNER ALREADY APPROVED:
{open}

REPLY:
{reply}

LINES:
{lines}

Answer only JSON, nothing else: {{"breaks": [{{"line": <number>, "quote": "<the exact words of the reply that break it, copied verbatim, 5 to 25 words>"}}]}}
An empty list when nothing is broken."""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü]+", " ", s.lower()).strip()


def stop_check(reply: str, paths: list[str]) -> str:
    """'' when the reply is fine; else the text that sends it back for a rewrite. Only RULE and LOST lines count,
    and a break counts only with a quote that really is in the reply."""
    import judge
    rows, opened = [], []
    for p in paths:
        for ln in load(p).get("lines") or []:
            if re.match(r"-\s*(RULE|LOST)\b", ln):
                rows.append((Path(p).name, ln))
            elif re.match(r"-\s*OPEN\b", ln):
                opened.append(ln)
    if not rows or not judge.available():
        return ""
    lines = "\n".join(f"{i + 1}. {ln}" for i, (_, ln) in enumerate(rows))
    try:
        out = judge._run(STOP_TASK.format(reply=reply[:8000], lines=lines, open="\n".join(opened) or "(nothing)"),
                         model=judge.STRONG)
        m = re.search(r"\{.*\}", out, re.S)
        breaks = json.loads(m.group(0)).get("breaks") or [] if m else []
    except Exception:
        return ""
    body, bad = _norm(reply), []
    for b in breaks:
        try:
            i = int(b.get("line")) - 1
        except Exception:
            continue
        q = _norm(str(b.get("quote") or ""))
        if 0 <= i < len(rows) and len(q) >= 12 and q in body:
            bad.append(f'{rows[i][0]}: {rows[i][1]}\n  your words: "{b.get("quote")}"')
    if not bad:
        return ""
    return ("OWNER BRIEF CHECK, BEFORE THE OWNER READS YOUR REPLY: it breaks what the owner already said:\n"
            + "\n".join(bad) + "\nRewrite the answer now so it follows these lines: do not propose again what was "
            "tried or rejected, and say plainly what you will do instead (or that nothing new is proposed). Do not "
            "mention this check.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in ("--build", "--show"):
        sys.path.insert(0, str(Path(__file__).parent))
        p = sys.argv[2]
        try:
            rec = build(p) if sys.argv[1] == "--build" or not load(p).get("lines") else load(p)
        finally:
            if sys.argv[1] == "--build":
                try:
                    _paths(_key(p))[1].unlink(missing_ok=True)
                except Exception:
                    pass
        if sys.argv[1] == "--show":
            sys.stdout.reconfigure(encoding="utf-8")
            print(json.dumps(rec, ensure_ascii=False, indent=1))
