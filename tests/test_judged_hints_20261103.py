"""Two real misses of 2026-11-03: a manual hint by similarity alone (a mod status-line fix pointed at the Meta Ads
manual), and a reply that described a tool against its own sheet ("Social Engine publishes through the browser")."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import judge  # noqa: E402
import quickmap  # noqa: E402


def _said_world(monkeypatch, verdict):
    calls = []

    def fake_run(prompt, **k):
        calls.append(k.get("model"))
        if "From the Reply" in prompt:
            return json.dumps({"items": [{"quote": "primero reviso los ganadores en Adscope", "kind": "proposal",
                                          "query": "review Adscope winners first"}]})
        return json.dumps({"wrong": verdict()})
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", fake_run)
    import meaning
    hit = lambda q, **k: [  # noqa: E731
        {"journal": "FAST_SALES_JOURNAL.md", "line": 311, "heading": "2026-11-01 [research] AI infoproduct research", "path": ""}]
    monkeypatch.setattr(meaning, "query", hit)
    monkeypatch.setattr(meaning, "query_strict", hit)
    monkeypatch.setattr(meaning, "query_many_strict", lambda asks, **k: [hit("") for _ in asks])
    return calls


REPLY = "La oferta pasa a Journals DNA + 9 diarios + el conector Pro, y primero reviso los ganadores en Adscope."


def test_a_proposal_the_journals_show_done_is_sent_back(monkeypatch):
    # owner 2026-11-03: the memory offer had been built FROM Adscope winners on 11-01; the reply offered to check them
    _said_world(monkeypatch, lambda: [{"item": 1, "why": "already done on 11-01", "evidence": "FAST_SALES_JOURNAL.md:311"}])
    out = quickmap.said_check(REPLY, "la idea es ofrecer un ad que incluya todo el conector")
    assert "primero reviso los ganadores en Adscope" in out and "FAST_SALES_JOURNAL.md:311" in out


def test_either_of_two_verdicts_counts(monkeypatch):
    runs = iter([[], [{"item": 1, "why": "already done", "evidence": "X:1"}]])
    _said_world(monkeypatch, lambda: next(runs))
    assert quickmap.said_check(REPLY, "") != ""


def test_a_quote_not_in_the_reply_never_blocks(monkeypatch):
    calls = _said_world(monkeypatch, lambda: [])
    assert quickmap.said_check(REPLY, "") == ""
    assert calls.count(judge.VERDICT) == 2    # the verdict (the stop decision) is asked twice, at once


def test_a_memory_that_does_not_answer_never_passes_the_reply(monkeypatch):
    # 2026-11-04: every search timed out at 2.5 s and came back empty; the judge saw "(no evidence)" and a false claim
    # ("the mod searches words, not meaning") passed. A search that did not answer is not "nothing found".
    _said_world(monkeypatch, lambda: [])
    import meaning

    def down(q, **k):
        raise meaning.Down("timed out")
    monkeypatch.setattr(meaning, "query_many_strict", down)
    out = quickmap.said_check(REPLY, "")
    assert out.startswith("NOT CHECKED")


def test_manual_hint_follows_the_judge(monkeypatch):
    import meaning
    import server
    refined = r"C:\x\journals-drafts\run-meta-ads-with-ai.md"
    monkeypatch.setattr(server, "_conn", lambda: _FakeConn([(refined, "run-meta-ads-with-ai")]))
    monkeypatch.setattr(server, "_classify_kind", lambda p, d: "raw")
    monkeypatch.setattr(meaning, "query", lambda q, **k: [
        {"path": refined, "journal": "run-meta-ads-with-ai.md", "heading": "Your running log", "score": 0.69}])
    entry = "journals mod 0.7.1: the status line is for the person. " * 10
    monkeypatch.setattr(server, "_judge", lambda q, texts, **k: [])
    assert server.manual_hint(r"C:\x\JOURNAL_MCP_JOURNAL.md", entry, "ship") is None
    monkeypatch.setattr(server, "_judge", lambda q, texts, **k: [0])
    assert server.manual_hint(r"C:\x\JOURNAL_MCP_JOURNAL.md", entry, "ship")["journal"] == "run-meta-ads-with-ai.md"


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *a):
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        pass
