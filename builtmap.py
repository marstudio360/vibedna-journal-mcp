"""Already built: before a NEW script is written (or an agent is briefed to build one), the journal entries that say
the same job was already built, with the scripts they name.

Incident 2026-11-01 (AA Breathwork Rhythms): a session wrote four new loop-window cutters (bf_windows.py ... 4) while
the journal held the [feature] of 2026-10-25 (34 seamless loops cut by cut_loops.py) and the [ship] of 2026-10-26
(64 section loops from cut_sections.py + energy_map.py). The meaning search found both in its top 3 for the new
script's own docstring, but nothing asked it: the tools map only compares against hand-written "Already exists"
cards and tool docs, with concept words for posting, mail and payments. Owner: "we cannot keep adding cards by hand
every time something is missing".

How: what the new code says it does (file name + module docstring or leading comments, or the agent's label + brief)
is asked to the meaning layer; of the hits, only build entries count ([ship], [feature], [build], [tool] ... in the
heading) that NAME a script. Each line of such an entry that names a script the new code does not already use (it
is not editing, testing or running that tool) is compared again, line by line, with what the new code says it does:
"Cut (cut_sections.py): 64 section loops..." against "measure each bar and pick 4- and 8-bar loops". A line close
enough is an existing tool for this job. A new code file or an agent build brief is stopped once per target with
those entries and scripts; anything else gets no output. Never blocks: no meaning service = nothing.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import meaning

CODE_EXT = re.compile(r"\.(py|js|mjs|cjs|ts|tsx|sh|bash|ps1|rb|go|rs|php)$", re.I)
TAG = re.compile(r"\[(?:ship|shipped|feature|build|built|tool|tools|capability|live|release)\]", re.I)
SCRIPT = re.compile(r"(?<![\w.-])([\w-]{3,}\.(?:py|js|mjs|cjs|ts|sh|ps1))(?![\w])", re.I)
HEREDOC = re.compile(r"(?:cat|tee)\s*>{1,2}\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"'<>|;&]+))\s*<<-?\s*[\"']?(\w+)[\"']?[^\n]*\n(.*?)\n\4\b", re.S)
# Measured 2026-11-01 on the 26 scripts of the session (bge-m3, best line): the four loop cutters 0.65-0.72 and
# seam_check 0.67 (the bar grid QA of cut_loops.py) over it; judge/trim/session/hyb/cut_mid under 0.58; two near
# topic misses over it (sync_check 0.66 vs the Pacer sync checkers, demo_build_new 0.74): one stop each, retry passes.
HIT_MIN = float(os.environ.get("JOURNAL_BUILT_HIT_MIN") or 0.55)
LINE_MIN = float(os.environ.get("JOURNAL_BUILT_LINE_MIN") or 0.65)
# A test harness checks a tool, it is not a second copy of one.
TEST_FILE = re.compile(r"(?:^|[\\/])(?:test_[^\\/]*|conftest\.py|[^\\/]*[_.-](?:test|spec)\.\w+)$", re.I)


def _stem(name: str) -> str:
    """bf_windows3.py -> bfwindows; cut_loops_v2.py -> cutloops: versions of one script are one script."""
    s = re.sub(r"\.\w+$", "", Path(name).name.lower())
    s = re.sub(r"(?:[_-]?v?\d+|[_-](?:new|old|copy|fix|tmp))+$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def intro(code: str) -> str:
    """What code says it does: its module docstring, else its leading comment lines, else its first lines."""
    m = re.match(r"\s*(?:#![^\n]*\n)?\s*(?:[rubf]{0,2})(\"\"\"|''')(.*?)\1", code, re.S)
    if m:
        return m.group(2).strip()[:700]
    m = re.match(r"\s*(?:#![^\n]*\n)?\s*/\*(.*?)\*/", code, re.S)
    if m:
        return m.group(1).strip(" *\n")[:700]
    lines = []
    for ln in code.splitlines()[:20]:
        t = ln.strip()
        if t.startswith(("#!", "\"use", "'use")):
            continue
        if t.startswith(("#", "//", "--", "REM ")):
            lines.append(t.lstrip("#/- ").rstrip())
        elif lines or t:
            break
    return "\n".join(x for x in lines if x)[:700]


def parts(call: dict) -> tuple[str, str, str, bool]:
    """(target, query, code, builds): the new file or agent label, what it says it does, the code (to see which
    tools it already uses), and whether it is a new build (a new code file, or an agent briefed to build)."""
    tool = str(call.get("tool_name") or "")
    ti = call.get("tool_input") or {}
    if tool in ("Write", "NotebookEdit"):
        fp = str(ti.get("file_path") or ti.get("notebook_path") or "")
        code = str(ti.get("content") or ti.get("new_source") or "")
        if not CODE_EXT.search(fp) or os.path.exists(fp) or TEST_FILE.search(fp):
            return "", "", "", False   # an existing file rewritten is work on that file, not a new tool
        what = intro(code)
        return fp, (Path(fp).name + ": " + what) if len(what) >= 40 else "", code, True
    if tool in ("Bash", "PowerShell"):
        cmd = str(ti.get("command") or "")
        for m in HEREDOC.finditer(cmd):
            fp, body = m.group(1) or m.group(2) or m.group(3), m.group(5)
            if CODE_EXT.search(fp) and not TEST_FILE.search(fp) and not os.path.exists(os.path.expanduser(fp)):
                what = intro(body)
                if len(what) >= 40:
                    return fp, Path(fp).name + ": " + what, cmd, True
        return "", "", "", False
    if tool in ("Agent", "Task"):
        desc, prompt = str(ti.get("description") or ""), str(ti.get("prompt") or "")
        if not re.search(r"\b(?:build|write|create|make|cut|generate|implement|scaffold|port|construir|armar|hacer)\b",
                         desc + " " + prompt[:300], re.I):
            return "", "", "", False
        return desc, (desc + ": " + prompt[:600]).strip(), prompt, True
    return "", "", "", False


def _body(path: str, line: int) -> str:
    try:
        c = meaning._conn()
        try:
            r = c.execute("SELECT body FROM entries_fts WHERE path=? AND line=?", (path, line)).fetchone()
        finally:
            c.close()
        return r[0] if r else ""
    except Exception:
        return ""


def find(q: str, code: str = "", target: str = "", k: int = 12, timeout: float = 1.5) -> list[dict]:
    """Build entries that already did what q says, best first: {journal, line, heading, score, lines: [(s, text)],
    scripts: [...]}. code/target: what the new work already uses or is (never shown as the existing tool)."""
    if not q.strip():
        return []
    hits = [h for h in meaning.query(q, k=k, timeout=timeout) if TAG.search(h.get("heading") or "")
            and h.get("score", 0) >= HIT_MIN]
    if not hits:
        return []
    used = {_stem(s) for s in SCRIPT.findall(code or "")} | ({_stem(target)} if target else set())
    # A module the new code names without its extension ("import meaning", "meaning.OFF", "toolmap.check") is in use
    # too (2026-11-01: a conftest.py that turns the meaning service off was stopped with meaning.py as the tool).
    words = set(re.findall(r"[a-z][a-z0-9_]{2,}", (code or "").lower()))

    def in_use(script: str) -> bool:
        base = re.sub(r"\.\w+$", "", Path(script).name.lower())
        return _stem(script) in used or base in words

    cands = []   # (hit index, line text, scripts on it)
    for i, h in enumerate(hits):
        for ln in _body(h["path"], h["line"]).splitlines():
            names = list(dict.fromkeys(SCRIPT.findall(ln)))
            # A line about a tool the new code already uses (it routes rhythms.js in, it runs cut_loops.py) is the
            # tool being worked on, not a second one: measured 2026-11-01, test and patch scripts hit 0.67 here.
            if names and not any(in_use(x) for x in names) and len(ln.strip()) >= 30:
                cands.append((i, re.sub(r"\s+", " ", ln.strip())[:600], names))
    cands = cands[:48]
    scores = meaning.score(q, [c[1] for c in cands], timeout=max(timeout, 3.0)) if cands else []
    if len(scores) != len(cands):
        return []
    out: dict = {}
    for (i, text, names), s in zip(cands, scores):
        if s < LINE_MIN:
            continue
        h = hits[i]
        e = out.setdefault(i, {"journal": h["journal"], "path": h["path"], "line": h["line"], "heading": h["heading"],
                               "score": h["score"], "lines": [], "scripts": []})
        e["lines"].append((s, text))
        e["scripts"] += [n for n in names if n not in e["scripts"]]
    res = sorted(out.values(), key=lambda e: -max(s for s, _ in e["lines"]))
    for e in res:
        e["lines"].sort(key=lambda x: -x[0])
    return res


def block(found: list[dict], target: str) -> str:
    lines = [f'ALREADY BUILT: the journals say this job was done before ("{Path(target).name or target}"). '
             "Use or extend what exists; rebuild only for a reason you can name:"]
    for n, e in enumerate(found[:3], 1):
        lines.append(f"{n}. {e['heading'][:150]} ({e['journal']}:{e['line']})")
        lines.append(f"   Scripts: {', '.join(e['scripts'][:6])}")
        for s, t in e["lines"][:2]:
            lines.append(f"   It says: {t[:260]}")
    lines.append("Read that entry (journal_read_section) and find where those scripts live before writing a new one. "
                 "If they do not fit, say in one line why, then improve them or log why a new one is needed.")
    return "\n".join(lines)


def check(call: dict, seen: dict) -> dict | None:
    """{"deny": text} once per target when a new code file or an agent build repeats a built job, else None."""
    if os.environ.get("JOURNAL_BUILT_MAP") == "0":
        return None
    target, q, code, builds = parts(call)
    if not q or not builds:
        return None
    key = "bm:" + hashlib.md5(_stem(target).encode("utf-8") if CODE_EXT.search(target)
                              else target.encode("utf-8")).hexdigest()[:16]
    if key in seen:
        return None
    found = find(q, code, target)
    if not found:
        return None
    seen[key] = 1
    return {"deny": block(found, target)}


if __name__ == "__main__":   # python builtmap.py <new script file> | "<what you are about to build>"
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    a = " ".join(sys.argv[1:])
    if os.path.isfile(a):
        code = Path(a).read_text(encoding="utf-8", errors="replace")
        q, tgt = Path(a).name + ": " + intro(code), a
    else:
        code, q, tgt = "", a, a[:60]
    f = find(q, code, tgt, timeout=60)
    print(block(f, tgt) if f else "(nothing already built for this)")
    if "--scores" in os.environ.get("JOURNAL_BUILT_DEBUG", ""):
        for e in f:
            print(e["score"], [round(s, 3) for s, _ in e["lines"]])
