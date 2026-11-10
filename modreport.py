"""Is the mod earning its cost? One report from the logs it already writes (owner 2026-11-06: "fast, smart, and the
memory still works": measure it in real use, not in tests).

  python modreport.py [hours]      default 24

Reads $JOURNAL_HOME: judge_usage.jsonl (AI calls, cost, waiting), mod_events.jsonl (exact stops, overrides, journal
briefs delivered), action_check_log.jsonl (judge stops on commands), reply_gate_log.jsonl (replies sent back), and the
owner-voice journals for the owner's own corrections in the window (JOURNAL_OWNER_VOICE_GLOB, optional).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HOME = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def _rows(name: str, since: str) -> list[dict]:
    out = []
    try:
        for ln in (HOME / name).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if str(r.get("at", "")) >= since:
                out.append(r)
    except OSError:
        pass
    return out


def _corrections(since: str) -> int:
    pat = os.environ.get("JOURNAL_OWNER_VOICE_GLOB", "")
    n = 0
    for p in glob.glob(pat) if pat else []:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \[owner\].*?(?=^## |\Z)", text, re.S | re.M):
            when = m.group(1).replace(" ", "T")
            if when >= since[:16] and "'correction'" in m.group(0):
                n += 1
    return n


def report(hours: float = 24) -> str:
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    judge = _rows("judge_usage.jsonl", since)
    ev = Counter(r.get("kind") for r in _rows("mod_events.jsonl", since))
    cmd_stops = sum(1 for r in _rows("action_check_log.jsonl", since) if r.get("breaks"))
    sent_back = len(_rows("reply_gate_log.jsonl", since))
    usd = sum(float(r.get("usd") or 0) for r in judge)
    wait = sum(float(r.get("ms") or 0) for r in judge) / 60000
    corr = _corrections(since)
    lines = [
        f"Journals mod, last {hours:g} h (since {since} UTC)",
        f"  AI checks: {len(judge)} calls, US${usd:.2f} API-equivalent, {wait:.0f} min of waiting (all tabs)",
        f"  Memory delivered: {ev.get('brief', 0)} journal briefs handed over with the call (no stop)",
        f"  Exact rule stops (no AI): {ev.get('exact_stop', 0)}, run again on purpose: {ev.get('exact_override', 0)}",
        f"  Judge stops on risky commands: {cmd_stops}",
        f"  Replies sent back before the owner saw them: {sent_back}",
        f"  Owner corrections in this window: {corr if os.environ.get('JOURNAL_OWNER_VOICE_GLOB') else 'n/a (set JOURNAL_OWNER_VOICE_GLOB)'}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(float(sys.argv[1]) if len(sys.argv) > 1 else 24))
