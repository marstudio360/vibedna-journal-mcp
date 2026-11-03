"""Two real misses of 2026-11-03: a manual hint by similarity alone (a mod status-line fix pointed at the Meta Ads
manual), and a reply that described a tool against its own sheet ("Social Engine publishes through the browser")."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import judge  # noqa: E402
import quickmap  # noqa: E402


def test_a_reply_that_contradicts_a_tool_sheet_is_sent_back(tmp_path, monkeypatch):
    monkeypatch.setattr(quickmap, "OUR_TOOLS", {"Social Engine": "social engine"})
    monkeypatch.setattr(quickmap, "TOOL_FACTS", {"Social Engine": "It publishes through each network's official API."})
    monkeypatch.setattr(judge, "available", lambda: True)
    reply = "Desde el celular funciona. Pero Social Engine publica usando el navegador de la PC, no ves lo que hace."
    monkeypatch.setattr(judge, "_run", lambda prompt, **k: json.dumps({"wrong": [
        {"tool": "Social Engine", "quote": "publica usando el navegador de la PC", "sheet_says": "official API"}]}))
    out = quickmap.tool_claims_check(reply)
    assert "TOOL CHECK" in out and "publica usando el navegador de la PC" in out
    # a quote the judge invents (not in the reply) never blocks
    monkeypatch.setattr(judge, "_run", lambda prompt, **k: json.dumps({"wrong": [
        {"tool": "Social Engine", "quote": "posts only through a hidden browser", "sheet_says": "official API"}]}))
    assert quickmap.tool_claims_check(reply) == ""


def test_no_tool_named_means_no_judge_call(monkeypatch):
    calls = []
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", lambda prompt, **k: calls.append(1) or "{}")
    assert quickmap.tool_claims_check("Todo listo, el sitio quedo publicado y pasaron las pruebas.") == ""
    assert not calls


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
