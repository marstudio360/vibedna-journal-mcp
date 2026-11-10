"""The judge reads each owner rule ONCE and, when the rule is about an exact pattern, writes the test for it; the test then
runs on every command or write for free (owner 2026-11-06: "the judge works once per rule, not once per command").

  python rulecompile.py build          compile the rules not compiled yet (new or changed ones only)
  python rulecompile.py stats          how many are mechanical, judgment or info
  python rulecompile.py try "<cmd>"    what the compiled tests say about one command

A test is kept only when it proves itself: it catches every example the judge gave of breaking the rule, passes every
example of doing it right, and stops at most MAX_FALSE of the owner's real commands that passed the full check before
($JOURNAL_HOME/action_check_log.jsonl, written while JOURNAL_AI_CHECKS is on). Anything else stays with the judge.
Stored in $JOURNAL_HOME/compiled_rules.json. The rules are the ones actioncheck reads (your rules journals and
JOURNAL_RULE_FILES). It runs only with the judge on (JOURNAL_JUDGE=on). Model: JOURNAL_COMPILE_MODEL, else the stop
model (JOURNAL_VERDICT_MODEL; unset = the claude command's own model). JOURNAL_COMPILE_CORPUS: your own repos
(separated by the path separator) whose text proves the write tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))
OUT = HOME / "compiled_rules.json"
LOG = HOME / "action_check_log.jsonl"
BATCH = 15
MAX_FALSE = 0.002  # share of the owner's fine commands a command test may stop
MODEL = os.environ.get("JOURNAL_COMPILE_MODEL", "")  # once per rule: quality over price; empty = the stop model (judge.VERDICT)

TASK = """You turn an owner's working rules into exact automatic tests when, and only when, a rule is about an exact
pattern in a shell command an AI runs or in the text it writes into a file. Rules about judgment, timing, decisions,
tone, what to say, or what to do first are "judgment": no test. Facts, history and notes are "info".

For each rule below answer one object:
{"n": <rule number>, "kind": "mechanical" | "judgment" | "info",
 "on": "command" | "write",            (mechanical only: what the test reads)
 "pattern": "<Python regex>",         (mechanical only: matches text that BREAKS the rule; case-insensitive)
 "unless": "<Python regex or empty>", (text that matches this is fine even if pattern matched)
 "paths": "<Python regex of the file paths a write test applies to, or empty for every file>",
                                      (e.g. customer copy only: pages, emails, ads; a product's own code only; never the
                                      owner's personal configs, journals or notes when the rule is about products or copy)
 "say": "<one short line: what is wrong and the right way>",
 "hit": ["3 realistic examples that break it"], "miss": ["3 realistic similar examples that are fine"]}
Be strict: a pattern must be narrow enough that a normal command or file never matches it. If you cannot make it
narrow, answer "judgment". Answer only a JSON array.

Rules:
"""


def _key(text: str) -> str:
    import actioncheck
    return hashlib.sha1(actioncheck._title(text).encode()).hexdigest()[:16]


def _load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fine_commands() -> list[str]:
    out = []
    try:
        for ln in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if not r.get("breaks") and r.get("cmd"):
                out.append(str(r["cmd"]))
    except OSError:
        pass
    return out


def _fine_text() -> list[str]:
    """Lines that already live in the owner's code and pages (JOURNAL_COMPILE_CORPUS: git repos, os.pathsep-separated).
    A write test that catches some of them is shown to the judge, who says whether those are breaks or legit uses."""
    import subprocess
    out = []
    for repo in [p for p in os.environ.get("JOURNAL_COMPILE_CORPUS", "").split(os.pathsep) if p.strip()]:
        try:
            r = subprocess.run(["git", "-C", repo, "grep", "-I", "-e", ".", "--", "*.ts", "*.tsx", "*.js", "*.mjs",
                                "*.html", "*.md", "*.py", "*.json"], capture_output=True, timeout=120)
            for ln in r.stdout.decode("utf-8", "replace").splitlines():
                f, _, t = ln.partition(":")
                if 8 < len(t.strip()) < 400:
                    out.append((f"{repo}/{f}", t.strip()))
        except Exception:
            pass
    return out


class _LazyText(list):
    """The live text corpus, read only if a new write test needs proving (rare): reading repos is the heavy part."""
    _done = False

    def _fill(self):
        if not self._done:
            self._done = True
            self.extend(_fine_text())

    def __iter__(self):
        self._fill()
        return super().__iter__()

    def __bool__(self):
        self._fill()
        return super().__len__() > 0


def _legit_hits(d: dict, rule: str, text: list[str]) -> str:
    """'' when the lines a write test catches in live text are real breaks (or none), else an example of a legit one."""
    try:
        p = re.compile(d["pattern"], re.I)
        u = re.compile(d["unless"], re.I) if d.get("unless") else None
    except re.error:
        return "bad regex"
    scope = d.get("paths") or ""
    inside = lambda f: not scope or bool(re.search(scope, f.replace("\\", "/"), re.I))  # noqa: E731
    hits = [t for f, t in text if inside(f) and p.search(t) and not (u and u.search(t))]
    if not hits:
        return ""
    import judge
    if not judge.available():
        return "could not check against live text"
    step = max(1, len(hits) // 8)
    sample = hits[::step][:8]
    ask = (f"Owner rule: {rule}\n\nEach line below already exists in the owner's live code and pages and is matched by "
           "an automatic test for this rule:\n" + "\n".join(f"{i}. {s[:300]}" for i, s in enumerate(sample, 1)) +
           "\n\nWhich lines really BREAK the rule (text the rule forbids), as opposed to legitimate uses the rule is not "
           "about (code identifiers, domains, other brands or contexts, a product name, quotes of the rule)? "
           "Answer only JSON: {\"breaks\": [line numbers]}")
    try:
        mm = re.search(r"\{.*\}", judge._run(ask, model=MODEL or judge.VERDICT, timeout=120), re.S)
        n = len(json.loads(mm.group(0)).get("breaks") or [])
    except Exception:
        return "could not check against live text"
    return "" if n * 2 >= len(sample) else f"catches legit live text ({len(hits)} lines), e.g. {sample[0][:120]}"


REMIND_TASK = """An owner keeps working rules for an AI that runs shell commands on their computer and servers. For each rule
below decide whether the AI must be REMINDED of it at the moment it runs certain shell commands (which program, where it
runs, which server or service it reaches, how heavy it is). If yes, give a Python regex (case-insensitive) that matches
those commands. A reminder never stops anything, it only shows the rule, but it must stay quiet on ordinary commands
(ls, cat, grep, head, git status, git log, echo, cd, python -c prints, curl GET of a status page).
For each rule answer one object: {"n": <rule number>, "remind": "<regex>" or "", "hit": ["2 commands it must match"],
"miss": ["2 ordinary similar commands it must not match"]}. Answer only a JSON array.

Rules:
"""
MAX_REMIND = 0.35  # a reminder shows once per session per rule, so a broad match is fine; it only must not fire on most commands


def remind(limit: int = 0) -> dict:
    """The judge reads each judgment rule once more and says at which commands to remind it (stored as "remind")."""
    import actioncheck
    import judge
    done = _load()
    if not judge.available():
        return done
    rules = {_key(r["text"]): r for r in actioncheck._rules()}
    todo = [(k, rules[k]) for k, v in done.items() if v.get("kind") == "judgment" and "remind" not in v and k in rules]
    if limit:
        todo = todo[:limit]
    if not todo:
        return done
    fine = _fine_commands()

    def one(batch: list) -> list:
        listing = "\n".join(f"{i}. {actioncheck._title(r['text'])}" for i, (_, r) in enumerate(batch, 1))
        try:
            arr = json.loads(re.search(r"\[.*\]", judge._run(REMIND_TASK + listing, model=MODEL or judge.VERDICT, timeout=240), re.S).group(0))
        except Exception:
            return []
        out = []
        for d in arr:
            try:
                k, _ = batch[int(d.get("n")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            pat, why = str(d.get("remind") or ""), ""
            if pat:
                try:
                    p = re.compile(pat, re.I)
                    if any(not p.search(str(h)) for h in d.get("hit") or [""]):
                        why = "misses its own examples"
                    elif any(p.search(str(m)) for m in d.get("miss") or []):
                        why = "shows on its own ordinary examples"
                    elif fine and sum(1 for c in fine if p.search(c)) > len(fine) * MAX_REMIND:
                        why = "would show on too many real commands"
                except re.error:
                    why = "bad regex"
            out.append((k, "" if why else pat, why))
        return out

    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    with ThreadPoolExecutor(4) as pool:
        for res in pool.map(one, batches):
            for k, pat, why in res:
                done[k]["remind"] = pat
                if why:
                    done[k]["remind_rejected"] = why
    OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


def reminders(cmd: str) -> list[dict]:
    """The judgment rules to remind at this command (no AI)."""
    if "remind" not in _cache:
        out = []
        for d in _load().values():
            if d.get("remind"):
                try:
                    out.append((re.compile(d["remind"], re.I), d))
                except re.error:
                    pass
        _cache["remind"] = out
    return [d for p, d in _cache["remind"] if p.search(cmd)]


def reprove() -> dict:
    """Prove the kept write tests again against live text (after JOURNAL_COMPILE_CORPUS is set or the code grew)."""
    done, text = _load(), _fine_text()
    if not text:
        return done
    for k, v in done.items():
        if v.get("kind") == "mechanical" and v.get("on") == "write":
            why = _legit_hits(v, v["rule"], text)
            if why:
                v.update(kind="judgment", rejected=why)
    OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


def _prove(d: dict, fine: list[str]) -> str:
    """'' when the test proves itself, else why not."""
    try:
        p = re.compile(d["pattern"], re.I)
        u = re.compile(d["unless"], re.I) if d.get("unless") else None
    except (re.error, KeyError, TypeError):
        return "bad regex"
    breaks = lambda s: bool(p.search(s)) and not (u and u.search(s))  # noqa: E731
    if not d.get("hit") or any(not breaks(str(h)) for h in d["hit"]):
        return "misses its own examples"
    if any(breaks(str(m)) for m in d.get("miss") or []):
        return "stops its own fine examples"
    if d.get("on") == "command" and fine:
        n = sum(1 for c in fine if breaks(c))
        if n > max(1, int(len(fine) * MAX_FALSE)):
            return f"would stop {n} of {len(fine)} real fine commands"
    return ""


def build(limit: int = 0) -> dict:
    import actioncheck
    import judge
    done = _load()
    if not judge.available():
        return done   # the judge is off (JOURNAL_JUDGE) or the claude command is missing: nothing compiled, nothing spent
    rules = actioncheck._rules()
    todo = [r for r in rules if _key(r["text"]) not in done]
    if limit:
        todo = todo[:limit]
    if not todo:  # nothing new: no logs read, no repos read, no judge (a no-op run used to read every corpus repo)
        return done
    fine, text = _fine_commands(), _LazyText()
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

    def one(batch: list) -> list:
        listing = "\n".join(f"{i}. {actioncheck._title(r['text'])}" for i, r in enumerate(batch, 1))
        try:
            raw = judge._run(TASK + listing, model=MODEL or judge.VERDICT, timeout=240)
            arr = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        except Exception:
            return []
        res = []
        for d in arr:
            try:
                r = batch[int(d.get("n")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            kind = d.get("kind") if d.get("kind") in ("mechanical", "judgment", "info") else "judgment"
            why = _prove(d, fine) if kind == "mechanical" else ""
            if kind == "mechanical" and not why and d.get("on") == "write" and text:
                why = _legit_hits(d, actioncheck._title(r["text"]), text)
            res.append((_key(r["text"]), {
                "kind": "mechanical" if kind == "mechanical" and not why else ("judgment" if why else kind),
                "rejected": why, "on": d.get("on"), "pattern": d.get("pattern"), "unless": d.get("unless") or "",
                "paths": d.get("paths") or "",
                "say": d.get("say") or "", "where": r["where"], "rule": actioncheck._title(r["text"]),
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        return res

    with ThreadPoolExecutor(4) as pool:
        for res in pool.map(one, batches):
            for k, v in res:
                done[k] = v
    live = {_key(r["text"]) for r in rules}
    done = {k: v for k, v in done.items() if k in live}
    OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


_cache: dict = {}


def tests(on: str) -> list[tuple]:
    """(pattern, unless, entry) of the proven tests for 'command' or 'write', compiled once per process."""
    if on not in _cache:
        out = []
        for d in _load().values():
            if d.get("kind") == "mechanical" and d.get("on") == on:
                try:
                    out.append((re.compile(d["pattern"], re.I), re.compile(d["unless"], re.I) if d["unless"] else None, d))
                except re.error:
                    pass
        _cache[on] = out
    return _cache[on]


# A file path or a URL inside written text is an address, not words people read: write tests never judge them
# (2026-11-06: "D:/Mapleworks/website" in a config was stopped by the brand spelling test).
ADDRESS = re.compile(r"https?://\S+|[A-Za-z]:[\\/][^\s\"']*|(?<![\w.])\.?\.?/[\w.-]+/[^\s\"']*")


def check(text: str, on: str, path: str = "") -> list[dict]:
    if on == "write":
        text = ADDRESS.sub(" ", text)
    out = []
    for p, u, d in tests(on):
        if not p.search(text) or (u and u.search(text)):
            continue
        if path and d.get("paths"):
            try:
                if not re.search(d["paths"], path.replace("\\", "/"), re.I):
                    continue
            except re.error:
                pass
        out.append(d)
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "build":
        try:
            build(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
            remind()  # new judgment rules get their reminder in the same run
        finally:
            (HOME / "rulecompile.lock").unlink(missing_ok=True)
        cmd = "stats"
    if cmd == "remind":
        remind(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
        cmd = "stats"
    if cmd == "reprove":
        reprove()
        cmd = "stats"
    if cmd == "stats":
        d = _load()
        from collections import Counter
        c = Counter(v["kind"] for v in d.values())
        print(f"{len(d)} rules compiled: {c.get('mechanical', 0)} mechanical (free test), {c.get('judgment', 0)} judgment, "
              f"{c.get('info', 0)} info; {sum(1 for v in d.values() if v.get('rejected'))} tests rejected by their proof; "
              f"{sum(1 for v in d.values() if v.get('remind'))} judgment rules reminded at their commands")
    elif cmd == "try":
        for d in check(sys.argv[2], "command"):
            print(f"STOP: {d['say']} ({d['where']})")
