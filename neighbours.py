"""Neighbours of a journal: the journals it names and that name it, that share decisions with it, or that talk
about the same things.

growth.py writes the list (neighbours.json next to the memory map) every time it rebuilds the map; the quick map
reads it here and adds one line, so whoever touches a project also sees the projects around it.
Standard library only; a missing or broken file simply means no line.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_MONTH = re.compile(r"_\d{4}-\d{2}$")
_cache: dict = {"path": None, "mtime": None, "data": {}}


def default_path() -> Path:
    env = os.environ.get("JOURNAL_NEIGHBOURS")
    if env:
        return Path(env)
    home = os.environ.get("JOURNAL_HOME") or str(Path(os.path.expanduser("~")) / ".journal")
    return Path(home) / "growth" / "neighbours.json"


def _key(name: str) -> str:
    stem = Path(str(name).replace("\\", "/")).name
    stem = stem[:-3] if stem.lower().endswith(".md") else stem
    return _MONTH.sub("", stem).upper()


def load(path: Path | None = None) -> dict:
    p = Path(path) if path else default_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    if _cache["path"] != str(p) or _cache["mtime"] != mtime:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _cache.update(path=str(p), mtime=mtime, data=data if isinstance(data, dict) else {})
    return _cache["data"]


def of(journal: str, path: Path | None = None) -> list:
    """[[other journal stem, mentions both ways, day of its last entry, decisions they share, meaning 0..100,
    title of its last entry], ...], strongest first. A list written by an older growth.py has the first three only."""
    return list((load(path).get("journals") or {}).get(_key(journal)) or [])


def why(n: list) -> str:
    """Why a journal is a neighbour, in plain words: 'names it 27 times, shares 3 decisions, same topics'."""
    mentions, shared, meaning = n[1] if len(n) > 1 else 0, n[3] if len(n) > 3 else 0, n[4] if len(n) > 4 else 0
    bits = []
    if mentions:
        bits.append("names it %d time%s" % (mentions, "" if mentions == 1 else "s"))
    if shared:
        bits.append("shares %d decision%s" % (shared, "" if shared == 1 else "s"))
    if meaning:
        bits.append("same topics")
    return ", ".join(bits)


def _one(n: list) -> str:
    newest = ""
    if len(n) > 2 and n[2]:
        title = str(n[5]).strip() if len(n) > 5 and n[5] else ""
        newest = "; newest %s%s" % (str(n[2])[5:], ' "%s"' % title[:48] if title else "")
    return "%s (%s%s)" % (n[0], why(n) or "near", newest)


def line_for(journals: list[str], limit: int = 4, path: Path | None = None) -> str:
    """One quick map line for the first journals of a topic that have neighbours; '' when there is nothing to say."""
    own = {_key(j) for j in journals}
    parts, done = [], set()
    for j in journals:
        if _key(j) in done:  # month files of one journal are the same journal
            continue
        done.add(_key(j))
        near = [n for n in of(j, path) if _key(n[0]) not in own][:limit]
        if near:
            parts.append("%s: %s" % (_key(j), ", ".join(_one(n) for n in near)))
        if len(parts) == 2:
            break
    if not parts:
        return ""
    made = load(path).get("made_ts") or 0
    old = " (list from %d days ago)" % ((time.time() - made) // 86400) if made and time.time() - made > 7 * 86400 else ""
    return ("- NEIGHBOURS (the journals around this one, why, and their newest entry)%s: %s. If the change reaches one of "
            "them, read its Current state and Handoff first." % (old, " | ".join(parts)))
