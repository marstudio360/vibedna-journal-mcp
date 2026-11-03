"""The relevance judge: a language model reads the question and each candidate and says which are really about it.

Word overlap and vector similarity both let noise through (an entry that only shares a word, or is about another
version or project). This module asks a model instead, through the `claude` command (Claude Code) already logged in
on this machine: one short call per question, started light (no hooks, no tools, no settings), with your own plan.

judge(q, candidates) -> list of indexes (0-based) judged relevant, or None when no judge is available (callers keep
their older behavior then). Answers are cached by content, so the same question on the same candidates is free.
Env: JOURNAL_JUDGE=on enables it (off by default); JOURNAL_JUDGE_MODEL (the model for the quick picks; default: the
command's own default model); JOURNAL_JUDGE_STRONG_MODEL (the picks that decide something: which tool already does
the job, whether a reply breaks your rules; default: JOURNAL_JUDGE_MODEL); JOURNAL_JUDGE_CMD (default "claude");
JOURNAL_JUDGE_TIMEOUT (default 30 s).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# Opt-in (JOURNAL_JUDGE=on): every call starts the claude command and uses your plan's credit.
OFF = os.environ.get("JOURNAL_JUDGE", "").lower() not in ("on", "1", "true", "yes")
MODEL = os.environ.get("JOURNAL_JUDGE_MODEL", "").strip()
# The picks that decide something (which tool already does the job, whether a reply breaks a rule): a small model
# chose a generic browser over the card made for the job in our tests, a mid-size model the card.
STRONG = os.environ.get("JOURNAL_JUDGE_STRONG_MODEL", "").strip()
CMD = os.environ.get("JOURNAL_JUDGE_CMD", "claude")
TIMEOUT = float(os.environ.get("JOURNAL_JUDGE_TIMEOUT") or 30)
CACHE = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "judge_cache.json"
_MAX_CACHE = 4000

INSTRUCTION = ("You decide which journal entries are really about what a message asks or talks about. The message may "
               "be fast Spanish with typos. An entry that only shares a word, or is about another topic, version or "
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
    args = [CMD, "-p", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands", "--output-format", "text"]
    if model or MODEL:   # no model set: the command's own default model
        args += ["--model", model or MODEL]
    r = subprocess.run(args,
                       input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                       shell=os.name == "nt", cwd=str(Path.home()), env=env)
    return r.stdout or ""


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
