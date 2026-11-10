"""Already said? A new owner rule written into a rules journal (OWNER_SAID_JOURNAL.md or any *_RULES_JOURNAL.md)
is checked against the rules already there.

2026-10-28 real case: the owner said, again, that Shopsite must always improve its tools from how the employees use
them ("I have said it a thousand times"). The session added a NEW rule line for it; the same rule had been there since
2026-10-25 ("All employees of all companies use Shopsite tools as much as possible ... Shopsite monitors that use ...").
The mod never looked: writing prose into a journal is not an action for the tools map or the intent map. A duplicate
rule hides the fact that the first one was never applied, and the owner had to ask why.

check(call, seen) -> {"deny": text} once per new rule line that looks like one already there, or None. Light: reads
the OWNER_SAID files listed in the journals index, no server import.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path

TARGET = re.compile(r"(?:OWNER_SAID|RULES)_JOURNAL\.md", re.I)
NEW_RULE = re.compile(r"-\s(20\d\d-\d\d-\d\d):\s([^\"\n]{40,})")
STOP = set("""the and for that this with from into when what which while their there them they then than will would
should must never always every each also only just more most some such have has had been being were was are its it's
your you our ours his her who whom does done do not nor but any all one two own same other others very much many
owner owners company companies rule rules said says say like make makes made keep keeps kept use uses used using
about after before because until since over under once again here where how why can could may might""".split())


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def _rule_files() -> list[str]:
    for name in ("index.sqlite", "index.db"):
        db = _home() / name
        if db.exists():
            try:
                c = sqlite3.connect(str(db))
                try:
                    return [r[0] for r in c.execute("SELECT DISTINCT path FROM journals WHERE name IN (?, ?) OR name LIKE ? ESCAPE '!'",
                                                    ("OWNER_SAID_JOURNAL.md", "RULES_JOURNAL.md", "%!_RULES!_JOURNAL.md"))]
                finally:
                    c.close()
            except sqlite3.Error:
                continue
    return []


def _stem(w: str) -> str:
    for suf in ("ing", "ies", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


# The same idea in other words (2026-10-28 real case: "dogfood ... monitors that use ... better tools" against
# "developing our tools: watch how the employees use them ... improve the tools").
CONCEPTS = {
    "#improve": "improve better develop optimize optimise upgrade fix polish mejorar desarrollar optimizar arreglar",
    "#watch": "watch monitor check review measure audit track inspect mirar revisar medir chequear",
    "#employee": "employee worker role staff agent session empleado",
    "#tool": "tool mcp dogfood herramienta",
    "#sell": "sale sell selling revenue buyer customer venta vender cliente",
    "#traffic": "traffic visitor visit reach promo promotion content warming outreach trafico",
    "#mail": "mail email newsletter drip correo",
    "#post": "post posting reel carousel feed story publicar",
}
# both the word and its plural, since _stem cuts "employees" to "employe" but leaves "employee" whole
_C = {_stem(f): c for c, ws in CONCEPTS.items() for w in ws.split() for f in (w, w + "s")}


def words(text: str) -> set:
    t = re.sub(r"\([^)]*\)$", "", text.lower())   # the trailing "(context)" is not the rule
    out = set()
    for w in re.findall(r"[a-z][a-z0-9']{3,}", t):
        if w in STOP:
            continue
        st = _stem(w.replace("'s", ""))
        out.add(_C.get(st, st))
    return out


def existing_rules(files: list[str] | None = None) -> list[str]:
    out = []
    for f in files if files is not None else _rule_files():
        try:
            out += [ln for ln in Path(f).read_text(encoding="utf-8", errors="replace").splitlines() if ln.startswith("- 20")]
        except OSError:
            continue
    return out


def similar(new: str, rules: list[str], top: int = 3) -> list[tuple[float, int, str]]:
    """[(score, shared words, rule)] for rules that share enough of the new rule's own words."""
    nw = words(new)
    if len(nw) < 5:
        return []
    df: dict = {}
    sets = [(r, words(r)) for r in dict.fromkeys(rules) if r.strip() != new.strip()]   # PC and box copies list a rule twice
    for _, s in sets:
        for w in s:
            df[w] = df.get(w, 0) + 1
    n = max(len(sets), 1)
    hits = []
    for r, s in sets:
        shared = nw & s
        # the share of the SHORTER rule's ideas found in the other: a long rule shares words with anything
        frac = len(shared) / max(min(len(nw), len(s)), 1)
        # 0.38: the real case scores 0.39; over the 232 distinct rules of 2026-10-28 it flags 17 (7%), most of them
        # true near-duplicates (a stop costs one retry)
        if len(shared) >= 6 and frac >= 0.38 and len({w for w in shared if w.startswith("#")}) >= 2:
            hits.append((round(frac, 2), len(shared), r))
    return sorted(hits, reverse=True)[:top]


def new_rule_lines(call: dict) -> list[str]:
    ti = call.get("tool_input") or {}
    tool = call.get("tool_name")
    if tool in ("Write", "Edit", "MultiEdit"):
        if not TARGET.search(str(ti.get("file_path") or "")):
            return []
        text = str(ti.get("content") or ti.get("new_string") or "")
        old = str(ti.get("old_string") or "")
        # an edit that EXTENDS a line already there (same start) is the right move, not a new rule
        return [m.group(0) for m in NEW_RULE.finditer(text) if m.group(0)[:80] not in old]
    if tool in ("Bash", "PowerShell"):
        cmd = str(ti.get("command") or "")
        if not TARGET.search(cmd):
            return []
        return [m.group(0) for m in NEW_RULE.finditer(cmd)]
    return []


def check(call: dict, seen: dict, rules: list[str] | None = None) -> dict | None:
    if os.environ.get("JOURNAL_RULEDUPES") == "0":
        return None
    lines = new_rule_lines(call)
    if not lines:
        return None
    rules = rules if rules is not None else existing_rules()
    done = seen.setdefault("ruledupes", [])
    out = []
    for ln in lines:
        key = hashlib.sha1(ln.encode("utf-8")).hexdigest()[:10]
        if key in done:
            continue
        hits = similar(ln, rules)
        if hits:
            done.append(key)
            out.append(f"- NEW: {ln[:180]}\n" + "\n".join(f"  ALREADY THERE: {r[:300]}" for _, _, r in hits))
    if not out:
        return None
    return {"deny": "ALREADY SAID? (journals mod, owner rules)\n" + "\n".join(out)
            + "\nIf it is the same rule, EXTEND that line (add the date and the new words) instead of adding another; and "
              "ask why the first one was not applied. If it is really new, retry: the same write passes."}
