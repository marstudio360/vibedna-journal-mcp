"""Wrong copy: a command touches a server folder while the journals say the LIVE copy is a near twin of it.

2026-10-28 real case: Social Engine is installed in /home/deploy/.social-engine (SB_HOME; every lane cron cd's
there) and /home/deploy/social-engine only holds the venv plus an OLD copy of the code. A session imported
server.py from the old copy; its engage_edit wiped a brand's X block, and the session told the owner the box was out
of date. The journals said "deployed to /home/deploy/.social-engine" many times, but the quick map matches
words, and "social-engine" and ".social-engine" are the same words. This module compares PATHS instead.

check(call, seen) -> {"deny": text} once per (touched, live) pair, or None. Light: no server import; the journal list
comes from the journals table of the shared index and each journal's paths are cached by mtime in
$JOURNAL_HOME/live_paths_v2.json.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

ROOTS = r"(?:home|opt|data|srv|var/www|usr/local|etc|root)"
PATH_RE = re.compile(r"(?<![\w.~-])(/" + ROOTS + r"/[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+){0,3})")
_P = r"(/" + ROOTS + r"/[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+){0,3})"
# A journal line that says where something is deployed, installed or runs from, with the path right after the phrase
# ("deployed to gpubox /home/deploy/.social-engine/server.py", "SB_HOME=...", "cd ... &&" in a cron line).
DEPLOY_RE = re.compile(r"(?:\bdeploy(?:ed|s|ing)?\b[^/\n]{0,40}?|\binstall(?:ed|s)?\b[^/\n]{0,20}?|"
                       r"\blive (?:install|copy|code)\b[^/\n]{0,12}?|\b[A-Z_]*HOME=)" + _P)
# "cd <path>" says where something RUNS only on a scheduled line (a cron or timer line); elsewhere it is a session
# moving around (cd /home/appuser/ai-team && git pull is not a deploy of the code in /home/appuser/.ai-team).
CRON_LINE = re.compile(r"\*/\d+|\bcron(?:tab)?\b|\btimer\b|\bExecStart\b|\bWorkingDirectory\b")
CRON_CD_RE = re.compile(r"\bcd\s+" + _P)
# The text RUNS code from a folder: cd into it, puts it on the import path, or runs a .py inside it.
CODE_USE_RE = re.compile(r"(?:\bcd\s+|sys\.path\.(?:insert|append)\(\s*(?:0\s*,\s*)?[\"']|PYTHONPATH=)" + _P)
PY_FILE_RE = re.compile(_P[:-1] + r"\.py)\b")


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def _journal_paths() -> list[str]:
    for name in ("index.sqlite", "index.db"):
        db = _home() / name
        if not db.exists():
            continue
        try:
            c = sqlite3.connect(str(db))
            try:
                return [r[0] for r in c.execute("SELECT path FROM journals")]
            finally:
                c.close()
        except sqlite3.Error:
            continue
    return []


def prefixes(p: str) -> list[str]:
    """/home/deploy/.social-engine/engage/x.json -> the folder prefixes 3 and 4 segments deep."""
    parts = [x for x in p.split("/") if x]
    return ["/" + "/".join(parts[:n]) for n in (3, 4) if len(parts) >= n]


def _clean(p: str) -> str:
    return p.rstrip(".,;:)`'\"")


def scan_text(text: str) -> dict:
    """{prefix: [mentions, deploy / install / runs-from mentions, sample deploy line]}"""
    out: dict = {}
    for line in text.splitlines():
        found = PATH_RE.findall(line)
        if not found:
            continue
        for p in found:
            for pre in prefixes(_clean(p)):
                out.setdefault(pre, [0, 0, ""])[0] += 1
        for p in DEPLOY_RE.findall(line) + (CRON_CD_RE.findall(line) if CRON_LINE.search(line) else []):
            for pre in prefixes(_clean(p)):
                e = out.setdefault(pre, [0, 0, ""])
                e[1] += 1
                if not e[2]:
                    e[2] = line.strip()[:220]
    return out


def path_index(files: list[str] | None = None) -> dict:
    files = files if files is not None else _journal_paths()
    cf = _home() / "live_paths_v3.json"   # v3: deploy phrases, cd only on cron lines
    try:
        cache = json.loads(cf.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    changed, idx, keep = False, {}, {}
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        sig = [int(st.st_mtime), st.st_size]
        ent = cache.get(f)
        if not ent or ent[0] != sig:
            try:
                ent = [sig, scan_text(Path(f).read_text(encoding="utf-8", errors="replace"))]
            except OSError:
                continue
            changed = True
        keep[f] = ent
        for pre, (n, lv, sample) in ent[1].items():
            e = idx.setdefault(pre, [0, 0, ""])
            e[0] += n
            e[1] += lv
            if sample and not e[2]:
                e[2] = sample
    if changed or len(keep) != len(cache):
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(json.dumps(keep), encoding="utf-8")
            os.replace(tmp, cf)
        except OSError:
            pass
    return idx


def twins(pre: str) -> list[str]:
    head, _, last = pre.rpartition("/")
    alts = {last[1:] if last.startswith(".") else "." + last, last.replace("-", "_"), last.replace("_", "-")}
    return [head + "/" + a for a in alts if a and a != last]


def code_folders(text: str) -> set:
    """Folder prefixes the text runs code from: cd into them, puts them on the import path, or runs a .py in them."""
    paths = CODE_USE_RE.findall(text) + PY_FILE_RE.findall(text)
    return {pre for p in paths for pre in prefixes(_clean(p))}


def wrong_copies(text: str, idx: dict) -> list[tuple[str, str, str]]:
    """[(touched, live, sample)]: the text runs code from a folder whose near twin is where the journals say the code
    is deployed, installed or run from (at least 3 times, and twice as often as the folder itself), and the text runs
    nothing from the twin."""
    used = code_folders(text)
    hits, seen = [], set()
    for pre in sorted(used):
        mine = idx.get(pre, [0, 0, ""])
        for t in twins(pre):
            other = idx.get(t)
            if not other or t in used or (pre, t) in seen:
                continue
            # 3+: two loose lines are not a fact (2026-10-28: /home/appuser/ai-team had 2, both asides, while the
            # AI team code really lives in /home/appuser/.ai-team; .social-engine had 7)
            if other[1] >= 3 and other[1] >= 2 * max(mine[1], 1):
                seen.add((pre, t))
                hits.append((pre, t, other[2]))
    return hits


def check(call: dict, seen: dict, idx: dict | None = None) -> dict | None:
    if call.get("tool_name") not in ("Bash", "PowerShell") or os.environ.get("JOURNAL_LIVECOPY") == "0":
        return None
    ti = call.get("tool_input") or {}
    cmd = str(ti.get("command") or "")
    if not PATH_RE.search(cmd) and not re.search(r"\b(?:ssh|scp)\b", cmd):
        return None
    try:
        import toolmap
        files = toolmap._local_files(toolmap.strip_payloads(cmd), str(call.get("cwd") or ""))
    except Exception:
        files = ""
    text = cmd + "\n" + files
    if not PATH_RE.search(text):
        return None
    hits = wrong_copies(text, idx if idx is not None else path_index())
    done = seen.setdefault("livecopy", [])
    new = [h for h in hits if f"{h[0]}|{h[1]}" not in done]
    if not new:
        return None
    done.extend(f"{a}|{b}" for a, b, _ in new)
    lines = [f"- you touch {a}, but the journals call {b} the live copy: \"{s}\"" for a, b, s in new[:3]]
    return {"deny": "WRONG COPY? (journals mod, path check)\n" + "\n".join(lines)
            + "\nCheck which one actually runs (its cron or unit line, md5 against the product) before using it."}
