"""The relevance judge: a language model reads the question and each candidate and says which are really about it.

Word overlap and vector similarity both let noise through (an entry that only shares a word, or is about another
version or project). This module asks a model instead, through the `claude` command (Claude Code) already logged in
on this machine: one short call per question, started light (no hooks, no tools, no settings), with your own plan.

judge(q, candidates) -> list of indexes (0-based) judged relevant, or None when no judge is available (callers keep
their older behavior then). Answers are cached by content, so the same question on the same candidates is free.
Env: JOURNAL_JUDGE=on enables it (off by default); JOURNAL_JUDGE_MODEL (the model for the quick picks; default: the
command's own default model); JOURNAL_JUDGE_STRONG_MODEL (the picks that decide something: which tool already does
the job, which rules a text can break; default: JOURNAL_JUDGE_MODEL); JOURNAL_VERDICT_MODEL (the model that decides
every stop: a reply sent back, and with JOURNAL_AI_CHECKS on a command, tool call or write stopped; it never falls
back to the two models above: unset, stops use the claude command's own default model); JOURNAL_JUDGE_CMD (default
"claude"); JOURNAL_JUDGE_TIMEOUT (default 30 s).
With none of the model settings, every call uses the claude command's own default model.
`python judge.py spend [hours]` prints what the judge calls cost (one line per call in judge_usage.jsonl).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Opt-in (JOURNAL_JUDGE=on): every call starts the claude command and uses your plan's credit.
OFF = os.environ.get("JOURNAL_JUDGE", "").lower() not in ("on", "1", "true", "yes")
MODEL = os.environ.get("JOURNAL_JUDGE_MODEL", "").strip()
# The picks that decide something (which tool already does the job, whether a reply breaks a rule): a small model
# chose a generic browser over the card made for the job in our tests, a mid-size model the card.
STRONG = os.environ.get("JOURNAL_JUDGE_STRONG_MODEL", "").strip()
# The model that decides a STOP (a command, a write, a reply sent back), kept apart from the picks: with a small model
# deciding, the command check stopped 93-97% of what it read in our measurements (1-7% with a mid-size model), almost
# all false. Picks can be cheap; a stop must be right. Unset, it never falls back to MODEL or STRONG: a stop is
# decided by the claude command's own default model (CLI_DEFAULT: no --model is passed).
CLI_DEFAULT = "cli-default"
VERDICT = os.environ.get("JOURNAL_VERDICT_MODEL", "").strip() or CLI_DEFAULT
CMD = os.environ.get("JOURNAL_JUDGE_CMD", "claude")
TIMEOUT = float(os.environ.get("JOURNAL_JUDGE_TIMEOUT") or 30)
CACHE = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "judge_cache.json"
_MAX_CACHE = 4000

INSTRUCTION = ("You decide which journal entries are really about what a message asks or talks about. The message may "
               "be fast, in any language, with typos. An entry that only shares a word, or is about another topic, version or "
               "project, is NOT relevant. A name the message says it does NOT want is not relevant.")


def _key(q: str, texts: list, task: str) -> str:
    return hashlib.sha1(json.dumps([task, q, texts], ensure_ascii=False).encode()).hexdigest()


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        if len(d) > _MAX_CACHE:
            d = dict(sorted(d.items(), key=lambda kv: kv[1].get("t", 0))[-_MAX_CACHE // 2:])
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(CACHE)
    except Exception:
        pass


def available() -> bool:
    return not OFF and bool(shutil.which(CMD))


def _run(prompt: str, timeout: float = TIMEOUT, think: bool = False, model: str = "") -> str:
    # Thinking off for a pick (2026-11-03: a 3-number answer spent 1,800-3,000 thinking tokens, 19-29 s, and changed
    # between runs; with MAX_THINKING_TOKENS=0 the same call is 3 s, 13 tokens, the same answer 3 times out of 3).
    env = dict(os.environ, MAX_THINKING_TOKENS="0") if not think else None
    # A short system prompt and no tools: with the default ones every call carried ~39,000 tokens of the coding
    # agent's own instructions (measured 2026-11-03: "ok" = 39,466 tokens in, 723 with these two flags, cost / 5).
    args = [CMD, "-p", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands", "--output-format", "json",
            "--system-prompt", "You are a precise judge. Answer exactly in the format asked.", "--tools", ""]
    use = "" if model == CLI_DEFAULT else (model or MODEL)
    if use:   # no model set (or the stop model left unset): the command's own default model
        args += ["--model", use]
    r = subprocess.run(args,
                       input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                       shell=os.name == "nt", cwd=str(Path.home()), env=env)
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        return r.stdout or ""
    _log_usage(model or MODEL, d)
    return str(d.get("result") or "")


USAGE_LOG = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "judge_usage.jsonl"


def _log_usage(model: str, d: dict) -> None:
    """One line per judge call (tokens and cost), so what the memory checks spend is measured, not guessed."""
    try:
        u = d.get("usage") or {}
        caller = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else ""
        # which check spent it (module.function of the first frame outside this file): the per-script total could not
        # tell the command check from the tools map or the reply check (2026-11-06)
        fr, where = sys._getframe(1), ""
        while fr is not None:
            if Path(fr.f_code.co_filename).name != "judge.py":
                where = f"{Path(fr.f_code.co_filename).stem}.{fr.f_code.co_name}"
                break
            fr = fr.f_back
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": model,
                                "flags": " ".join(a for a in sys.argv[1:3] if a.startswith("--")) or caller,
                                "in": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                                "cache_new": u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0),
                                "usd": round(float(d.get("total_cost_usd") or 0), 6),
                                "ms": d.get("duration_ms"), "where": where}) + "\n")
    except Exception:
        pass


def usage_summary(hours: float = 24) -> dict:
    """Totals of the judge calls in the last `hours`: calls, tokens, cost, by what ran them."""
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    tot = {"calls": 0, "tokens": 0, "usd": 0.0, "wait_s": 0, "by": {}}
    rows = []
    try:
        # line by line: parallel writers leave a few torn lines, and one of them must not hide the whole log
        for x in USAGE_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(x))
            except ValueError:
                pass
    except OSError:
        pass
    for r in rows:
        if r.get("at", "") < since:
            continue
        t = int(r.get("in", 0)) + int(r.get("cache_read", 0)) + int(r.get("cache_new", 0)) + int(r.get("out", 0))
        tot["calls"] += 1
        tot["tokens"] += t
        tot["usd"] += float(r.get("usd", 0))
        tot["wait_s"] += int((r.get("ms") or 0) / 1000)
        b = tot["by"].setdefault(r.get("where") or r.get("flags") or "?", {"calls": 0, "tokens": 0, "usd": 0.0})
        b["calls"] += 1
        b["tokens"] += t
        b["usd"] += float(r.get("usd", 0))
    tot["usd"] = round(tot["usd"], 4)
    for b in tot["by"].values():
        b["usd"] = round(b["usd"], 4)
    return tot


def complete(prompt: str, timeout: float = 120) -> str | None:
    """One free-text answer from the judge model (the owner brief is written with it); None without a judge."""
    if not available():
        return None
    try:
        return _run(prompt, timeout, think=True).strip() or None
    except Exception:
        return None


def judge(q: str, texts: list, task: str = INSTRUCTION, qmax: int = 1500, tmax: int = 400, model: str = "",
          ordered: bool = False) -> list | None:
    """Indexes of the texts the model judges relevant to q (best first when ordered); None when there is no judge or
    it did not answer."""
    if not q or not texts or not available():
        return None
    texts = [re.sub(r"\s+", " ", str(t))[:tmax] for t in texts][:20]
    k = _key(q[:qmax], texts, task + (model or "") + ("|ordered" if ordered else ""))
    cache = _load()
    if k in cache:
        return cache[k]["r"]
    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    want = "numbers of the relevant entries, best first" if ordered else "numbers of the relevant entries"
    prompt = (f"{task}\n\nMessage: {q[:qmax]}\n\nEntries:\n{lines}\n\n"
              f'Answer only JSON, nothing else: {{"relevant": [{want}]}}')
    try:
        m = re.search(r"\{.*\}", _run(prompt, model=model), re.S)
        got = [int(x) - 1 for x in json.loads(m.group(0)).get("relevant", []) if 1 <= int(x) <= len(texts)]
        rel = list(dict.fromkeys(got)) if ordered else sorted(set(got))
    except Exception:
        return None
    cache[k] = {"r": rel, "t": time.time()}
    _save(cache)
    return rel


if __name__ == "__main__":
    # What the memory checks spent, the easy way:
    #   python judge.py spend [hours]     default 24
    h = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "spend" else 24
    s = usage_summary(h)
    print(f"Journal checks, last {h:g} h: {s['calls']} AI calls, US${s['usd']:.2f} API-equivalent, "
          f"{s['wait_s'] / 60:.0f} min of waiting, {s['tokens'] / 1e6:.1f}M tokens")
    for k, b in sorted(s["by"].items(), key=lambda t: -t[1]["usd"])[:6]:
        print(f"  {k:24s} {b['calls']:6d} calls  US${b['usd']:.2f}")
