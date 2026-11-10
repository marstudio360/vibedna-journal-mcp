"""Command guards with no AI (exact matches, they cost nothing and run on every call):

  box_flood(call, home)        exact count of ssh/scp/rsync/sftp calls to your shared servers ($JOURNAL_HOME/box_hosts.txt
                               or JOURNAL_BOX_HOSTS) from ALL sessions; past BOX_MAX in BOX_WINDOW seconds the call is
                               stopped once (the same call again passes). No list: nothing is counted.
  money_guard(call, msg, home) a command or MCP tool call that matches $JOURNAL_HOME/paid_patterns.txt (one regex per
                               line) is stopped until the owner's latest message says yes; a plain retry does not pass.
                               No file: nothing is checked.
  reminder_note(call, seen)    the owner's judgment rules about this command (rulecompile reminders: the judge chose
                               once per rule at which commands to remind it), each shown once per session, never a stop
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

BOX_MAX, BOX_WINDOW = 6, 60
OVERRIDE_S = 600


def _box_re(home: str):
    """The shared servers to protect, one host or IP per line in $JOURNAL_HOME/box_hosts.txt (or JOURNAL_BOX_HOSTS,
    comma-separated); none set means no counting. A host may end in * for any suffix (myserver* = myserver-direct)."""
    import os
    hosts = [h.strip() for h in os.environ.get("JOURNAL_BOX_HOSTS", "").split(",") if h.strip()]
    try:
        hosts += [h.strip() for h in (Path(home) / "box_hosts.txt").read_text(encoding="utf-8").splitlines()
                  if h.strip() and not h.startswith("#")]
    except OSError:
        pass
    if not hosts:
        return None
    alts = "|".join(re.escape(h[:-1]) + r"[\w.-]*" if h.endswith("*") else re.escape(h) for h in hosts)
    return re.compile(r"\b(ssh|scp|rsync|sftp)\b[^\n]*\b(" + alts + r")\b", re.I)


def box_flood(cmd: str, home: str) -> str:
    """'' or the stop text. The owner's rule: never swarm a shared server; one session talks to it with few grouped
    calls and no polling loops."""
    box = _box_re(home)
    if not box or not box.search(cmd):
        return ""
    f = Path(home) / "box_calls.json"
    now = time.time()
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    recent = [t for t in d.get("t", []) if now - t < BOX_WINDOW]
    sig = hashlib.sha1(cmd.encode("utf-8", "replace")).hexdigest()[:16]
    ok = d.get("ok") or {}
    over = len(recent) >= BOX_MAX and now - float(ok.get(sig, 0)) > OVERRIDE_S
    if over:
        ok[sig] = now
        d["ok"] = dict(sorted(ok.items(), key=lambda t: -t[1])[:50])
    else:
        recent.append(now)
    d["t"] = recent
    try:
        f.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass
    if not over:
        return ""
    return (f"STOPPED, SERVER FLOOD (exact count, no AI): {len(recent)} ssh calls reached the shared server from all "
            f"sessions in the last {BOX_WINDOW} s. The rule: one session talks to it with few grouped calls and no "
            "polling loops. Group this into one call, or run it again unchanged if it really cannot wait.")


# The owner's yes in their latest message: these words, plus your own (any language) in JOURNAL_APPROVAL_WORDS,
# separated by commas.
APPROVAL_WORDS = ["yes", "go ahead", "do it", "approved"]


def _approval():
    import os
    extra = [w.strip() for w in os.environ.get("JOURNAL_APPROVAL_WORDS", "").split(",") if w.strip()]
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in APPROVAL_WORDS + extra) + r")\b", re.I)


APPROVAL = _approval()


def _paid_re(home: str):
    """What spends money, one Python regex per line in $JOURNAL_HOME/paid_patterns.txt (none = no money guard)."""
    try:
        pats = [p.strip() for p in (Path(home) / "paid_patterns.txt").read_text(encoding="utf-8").splitlines()
                if p.strip() and not p.lstrip().startswith("#")]
    except OSError:
        return None
    good = []
    for p in pats:
        try:
            re.compile(p)
            good.append(f"(?:{p})")
        except re.error:
            pass
    return re.compile("|".join(good), re.I) if good else None


READ_ONLY = re.compile(r"^(grep|egrep|fgrep|rg|sed|awk|cat|head|tail|less|more|wc|find|ls|tree|stat|file|diff|echo|printf|"
                       r"select-string|findstr|type|get-content|npm\s+view|pip\s+show|git\s+(log|show|grep|diff|status|blame)|"
                       r"jq|md5sum|sha256sum|du|df)\b", re.I)


def _running_parts(cmd: str) -> str:
    """The parts of a shell command that RUN something: segments that only read or search (grep for "/generate" in the
    code, cat a README that names a paid API) are dropped, so they never ask for a yes (measured on 5,295 real
    commands: before this, most matches were reads)."""
    keep = []
    prefix = re.compile(r"^\s*(?:ssh\s+(?:-\S+\s+(?:\S+\s+)?)*\S+\s+['\"]?|sudo\s+(?:-\S+\s+)*|timeout\s+\d+\s+|"
                        r"nice\s+(?:-n\s+\d+\s+)?|cd\s+\S+\s*|[A-Za-z_]\w*=\$\(\s*|[A-Za-z_]\w*=\S*\s+|\$\(\s*|\(\s*|['\"])+")
    segs, cur, dq, i = [], "", False, 0
    while i < len(cmd):  # split on && || ; | and newlines outside double quotes (a grep "a\|b" pattern stays whole)
        ch = cmd[i]
        if ch == '"' and (i == 0 or cmd[i - 1] != "\\"):
            dq = not dq
        if not dq and (cmd.startswith("&&", i) or cmd.startswith("||", i)):
            segs.append(cur)
            cur = ""
            i += 2
            continue
        if not dq and ch in ";|\n":
            segs.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    segs.append(cur)
    for seg in [s for s in segs if s]:
        s = prefix.sub("", seg).strip()
        if s and not READ_ONLY.match(s):
            keep.append(seg)
    return "\n".join(keep)


def money_guard(text: str, owner_msg: str, home: str, shell: bool = True) -> str:
    """'' or the stop text. A paid run (a command or tool matching paid_patterns.txt) goes only with the owner's yes in
    their latest message; a plain retry does NOT pass."""
    paid = _paid_re(home)
    if not paid or not paid.search(_running_parts(text) if shell else text):
        return ""
    if APPROVAL.search(owner_msg or ""):
        return ""
    return ("STOPPED, PAID RUN (exact match, no AI): this spends money (it matches $JOURNAL_HOME/paid_patterns.txt). "
            "The rule: no paid run without showing the owner the estimated cost first and getting their yes. Tell "
            "them what it is, how many runs and the estimated cost in one short line, and run it only after they say "
            "yes in their next message. Running it again without that does not pass.")


def reminder_note(cmd: str, seen: dict) -> str:
    """'' or the note; marks the shown rules in `seen` (the caller saves it)."""
    try:
        import rulecompile
        hits = rulecompile.reminders(cmd)
    except Exception:
        return ""
    shown = set(seen.get("rem") or [])
    new = [d for d in hits if d["where"] not in shown][:3]
    if not new:
        return ""
    seen["rem"] = sorted(shown | {d["where"] for d in new})[-300:]
    lines = [f"- {d['rule']} ({d['where']})" for d in new]
    return "OWNER RULES FOR THIS COMMAND (reminder, nothing was stopped; follow them):\n" + "\n".join(lines)
