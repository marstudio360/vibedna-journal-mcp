"""Alarm judge: before a no-AI check tells a session that its finished reply was wrong, a judge reads the reply
sentence, the alarm and the journal entry it cites, and cancels the alarm when the two are not about the same thing.

Why: the checks of the finished reply match words, so now and then they raise an alarm about an entry that only
shares a word with the reply (a quoted line of page copy read as a pending item, a common word such as "key" matched
to an incident of another product, a test in flight read as "the product is still to do"). Each false alarm costs a
correcting line nobody needed and teaches the session to walk past the check.

Where it runs: only in the reply check that the mod starts AFTER the reply is shown and never waits for
(turn.complete), so the person waits 0 s for it; and only when a check is about to say something, which is rare.
One call per alarm, at most three at once. No judge, no answer or a time-out: every alarm is kept as before.

It needs the judge (JOURNAL_JUDGE=on); without one nothing changes. JOURNAL_ALARM_JUDGE=off turns it off;
JOURNAL_ALARM_JUDGE_MODEL picks the model (default: the verdict model). Every verdict is kept in
~/.journal/alarm_judge_log.jsonl, so right and wrong ones can be counted.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TASK = (
    "A memory system wants to interrupt an AI assistant's finished reply with an alarm. Decide if the alarm is RIGHT "
    "or WRONG.\n"
    "- The alarm is RIGHT only if the memory entry is about the SAME thing the reply sentence talks about (the same "
    "piece, version, account or decision) and really contradicts it, or shows that what the reply proposes to build "
    "already exists.\n"
    "- The alarm is WRONG if the two only share a common word, a brand or a product line; if the sentence is quoted "
    "copy shown for approval and not the assistant's own statement; if the entry is about an older version or another "
    "thing of the same product; or if the pending thing is a decision or a test, not the product itself.\n"
    'Answer only JSON, nothing else: {"alarm": "right" or "wrong", "why": "at most 12 words"}'
)
# Each word check means something different by "wrong in your reply": the judge is told which one it is reading.
# With one general text the judge cancelled a right alarm of the "moved away from" kind, because the reply's
# sentence could be literally true; that alarm is not about a contradiction, it says the session may not know
# the work left that service.
KIND_RULES = {
    "moved": ("This alarm is of the kind \"a name the work moved away from\". It is RIGHT when the reply treats that "
              "service, vendor or product as one still in use or still to be worked on, and the entry says the work "
              "moved away from it or it was replaced, even if the reply's sentence could be literally true: the point "
              "is that the assistant may not know about the move. It is WRONG when the entry's words are a quoted "
              "line, a figure of speech or another thing that only shares the word, or when the reply itself talks "
              "about the move or about the past."),
    "shutdown": ("This alarm is of the kind \"it runs on something that was turned off\". It is RIGHT when the reply "
                 "says something uses or runs on the thing as of now and the entry says that thing was shut down or "
                 "turned off. It is WRONG when the entry is about another thing, or the reply talks about the past or "
                 "about the shutdown itself."),
    "shipped": ("This alarm is of the kind \"listed as still to do, but already done\". It is RIGHT only when the entry "
                "records as done the SAME piece the reply lists as pending (the same thing and the same version)."),
}
MAX_AT_ONCE = 3
TIMEOUT = float(os.environ.get("JOURNAL_ALARM_JUDGE_TIMEOUT") or 9)


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def on() -> bool:
    if os.environ.get("JOURNAL_ALARM_JUDGE", "").lower() in ("off", "0", "false", "no"):
        return False
    try:
        import judge
        return judge.available()
    except Exception:
        return False


def prompt_for(item: dict) -> str:
    kind = KIND_RULES.get(str(item.get("kind") or ""), "")
    return (f"{TASK}{chr(10) + kind if kind else ''}\n\nReply sentence: {str(item.get('reply') or '')[:600]}\n\n"
            f"Alarm: {str(item.get('alarm') or '')[:400]}\n\nMemory entry: {str(item.get('entry') or '')[:700]}")


def _one(item: dict, model: str, timeout: float) -> dict:
    import judge
    t0 = time.time()
    try:
        # The verdict model by default: a wrong verdict here hides a right alarm. The default answer is "the alarm
        # stays", so a cheaper model can be tried: JOURNAL_ALARM_JUDGE_MODEL.
        text = judge._run(prompt_for(item), timeout=timeout,
                          model=model or os.environ.get("JOURNAL_ALARM_JUDGE_MODEL") or judge.VERDICT)
        ans = json.loads(text[text.index("{"): text.rindex("}") + 1])
        said = str(ans.get("alarm", "")).strip().lower()
        why = str(ans.get("why", ""))[:160]
    except Exception as e:   # no answer in time, or not the format asked: the alarm stays
        said, why = "", f"no verdict: {type(e).__name__}"
    return {"alarm": said if said in ("right", "wrong") else "", "why": why, "s": round(time.time() - t0, 2)}


def verdicts(items: list, model: str = "", timeout: float = TIMEOUT, session: str = "") -> list:
    """One dict per item: {"alarm": "right" | "wrong" | "" (no verdict), "why", "s"}. Never raises."""
    if not items:
        return []
    try:
        with ThreadPoolExecutor(max_workers=MAX_AT_ONCE) as ex:
            got = list(ex.map(lambda it: _one(it, model, timeout), items[:MAX_AT_ONCE]))
    except Exception:
        got = []
    got += [{"alarm": "", "why": "not asked", "s": 0.0} for _ in items[len(got):]]
    try:
        with (_home() / "alarm_judge_log.jsonl").open("a", encoding="utf-8") as f:
            for it, g in zip(items, got):
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "session": session,
                                    "kind": it.get("kind", ""), "verdict": g["alarm"] or "none", "why": g["why"],
                                    "s": g["s"], "reply": str(it.get("reply") or "")[:300],
                                    "entry": str(it.get("entry") or "")[:300]}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return got


_WHAT = {"shipped": "You listed it as still to do, but the journals say it shipped.",
         "moved": "Your reply names it as where a thing lives, is sold or is charged, but an entry says it moved.",
         "shutdown": "Your reply says something uses or runs on it, but an entry says it was shut down or turned off."}


def _sentence_with(reply: str, name: str) -> str:
    """The sentence of the reply that names the thing (the line the alarm is about)."""
    fn = name.lower()
    for s in re.split(r"(?<=[.!?])\s+|\n+", reply or ""):
        if fn and fn in s.lower():
            return s.strip()[:600]
    return (reply or "").strip()[:600]


def item_of(line: str, kind: str, reply: str) -> dict:
    """One alarm line of the reply check ("- <name>: <what it says>, but <the entry>") as a case for the judge."""
    m = re.match(r"-\s*([^:]{1,80}):\s*(.*)", line, re.S)
    name, rest = (m.group(1).strip(), m.group(2)) if m else ("", line)
    said = re.search(r'still to do \("(.+?)"\)', rest, re.S)
    entry = rest.split(", but ", 1)[1] if ", but " in rest else rest
    return {"kind": kind, "reply": said.group(1) if said else _sentence_with(reply, name),
            "alarm": f"{name}: {_WHAT.get(kind, 'The journals contradict the reply.')}", "entry": entry}


def keep_right(checks: dict, reply: str, session: str = "", budget: float = TIMEOUT) -> dict:
    """checks: {kind: [alarm lines]} of one reply check. Returns the same shape with the lines the judge calls wrong
    taken out. All kinds go in ONE round (at most MAX_AT_ONCE calls, side by side), because the whole reply check has a
    fixed time and a second round would not fit. No judge, no time left, no verdict, or a line past the cap: it stays."""
    flat = [(k, ln) for k, lines in checks.items() for ln in (lines or [])]
    if not flat or budget < 4 or not on():
        return checks
    got = verdicts([item_of(ln, k, reply) for k, ln in flat], timeout=min(TIMEOUT, budget), session=session)
    out: dict = {k: [] for k in checks}
    for (k, ln), g in zip(flat, got):
        if g["alarm"] != "wrong":
            out[k].append(ln)
    return out
