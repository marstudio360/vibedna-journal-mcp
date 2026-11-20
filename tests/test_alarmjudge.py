"""The judge reads an alarm of the reply check before it is said and cancels the wrong ones (2.1.0)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import alarmjudge as A  # noqa: E402
import judge  # noqa: E402

SHIPPED = ('- key: you listed it as still to do ("Signing key (blocked)"), but SHOP_JOURNAL.md:936 (2026-09-20 10:00) '
           'says it shipped: [incident] A SECRET KEY OF THE PAYMENT SERVICE WAS TYPED IN A COMMAND')
DOWN = "- oldbox: your reply says something uses or runs on it, but OPS_JOURNAL.md:12 (2026-10-29 01:10) says: oldbox was shut down today"
REPLY = "Pending:\n- Signing key (blocked)\n- The nightly report still runs on oldbox and shares its disk."


def _judge(monkeypatch, tmp_path, answer):
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path))
    monkeypatch.delenv("JOURNAL_ALARM_JUDGE", raising=False)
    monkeypatch.setattr(judge, "available", lambda: True)
    seen = []

    def run(prompt, **k):
        seen.append(prompt)
        return answer(prompt)
    monkeypatch.setattr(judge, "_run", run)
    return seen


def test_a_line_becomes_a_case_with_the_reply_sentence_and_the_entry():
    it = A.item_of(SHIPPED, "shipped", REPLY)
    assert it["reply"] == "Signing key (blocked)"
    assert it["entry"].startswith("SHOP_JOURNAL.md:936") and "SECRET KEY" in it["entry"]
    assert it["alarm"].startswith("key: You listed it as still to do")
    dn = A.item_of(DOWN, "shutdown", REPLY)
    assert "oldbox" in dn["reply"] and dn["entry"].startswith("OPS_JOURNAL.md:12")


def test_the_prompt_carries_the_rule_of_its_kind():
    assert "listed as still to do, but already done" in A.prompt_for(A.item_of(SHIPPED, "shipped", REPLY))
    assert "runs on something that was turned off" in A.prompt_for(A.item_of(DOWN, "shutdown", REPLY))


def test_the_wrong_alarm_is_cancelled_and_the_right_one_stays(monkeypatch, tmp_path):
    seen = _judge(monkeypatch, tmp_path, lambda p: '{"alarm": "wrong", "why": "only the word key is shared"}'
                  if "SECRET KEY" in p else '{"alarm": "right", "why": "the box was shut down"}')
    out = A.keep_right({"shipped": [SHIPPED], "shutdown": [DOWN]}, REPLY, "s1")
    assert out == {"shipped": [], "shutdown": [DOWN]}
    assert len(seen) == 2 and all("Reply sentence:" in p and "Memory entry:" in p for p in seen)
    rows = [json.loads(x) for x in (tmp_path / "alarm_judge_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(r["verdict"] for r in rows) == ["right", "wrong"] and all(r["session"] == "s1" for r in rows)


def test_no_verdict_keeps_the_alarm(monkeypatch, tmp_path):
    _judge(monkeypatch, tmp_path, lambda p: "")
    assert A.keep_right({"shipped": [SHIPPED]}, REPLY) == {"shipped": [SHIPPED]}
    _judge(monkeypatch, tmp_path, lambda p: "I think it is probably fine")
    assert A.keep_right({"shipped": [SHIPPED]}, REPLY) == {"shipped": [SHIPPED]}


def test_without_a_judge_or_without_time_nothing_changes(monkeypatch, tmp_path):
    calls = _judge(monkeypatch, tmp_path, lambda p: '{"alarm": "wrong", "why": "x"}')
    assert A.keep_right({"shipped": [SHIPPED]}, REPLY, budget=2) == {"shipped": [SHIPPED]}   # the check is out of time
    monkeypatch.setenv("JOURNAL_ALARM_JUDGE", "off")
    assert A.keep_right({"shipped": [SHIPPED]}, REPLY) == {"shipped": [SHIPPED]}
    monkeypatch.delenv("JOURNAL_ALARM_JUDGE")
    monkeypatch.setattr(judge, "available", lambda: False)
    assert A.keep_right({"shipped": [SHIPPED]}, REPLY) == {"shipped": [SHIPPED]}
    assert calls == []


def test_a_line_past_the_cap_is_kept_unasked(monkeypatch, tmp_path):
    seen = _judge(monkeypatch, tmp_path, lambda p: '{"alarm": "wrong", "why": "x"}')
    lines = [SHIPPED.replace("- key", f"- key{i}") for i in range(5)]
    out = A.keep_right({"shipped": lines}, REPLY)
    assert out["shipped"] == lines[A.MAX_AT_ONCE:] and len(seen) == A.MAX_AT_ONCE
