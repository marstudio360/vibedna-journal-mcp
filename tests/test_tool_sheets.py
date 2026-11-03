"""A message that names one of our tools carries what the tool does today (owner 2026-11-03: the session said
"Social Engine publishes through the browser" from memory; it publishes through the official APIs)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import meaning  # noqa: E402
import quickmap  # noqa: E402


def test_tools_are_named_even_with_typos(monkeypatch):
    monkeypatch.setattr(quickmap, "OUR_TOOLS", {"Mail Robot": "mail robot", "Shop Scanner": "shop scanner",
                                                "Store Connector": "conector|connector"})
    msg = "la app podria usar el conector? mail robto no funcionara no? shop scaner tampoco"
    assert quickmap._named_tools(msg) == ["Mail Robot", "Shop Scanner", "Store Connector"]
    assert quickmap._named_tools("hola como va, armame el resumen del dia") == []


def test_the_sheet_says_how_it_works_and_a_clear_card_rides_along(tmp_path, monkeypatch):
    monkeypatch.setattr(quickmap, "OUR_TOOLS", {"Social Engine": "social engine"})
    monkeypatch.setattr(quickmap, "TOOL_FACTS", {"Social Engine": "Posts through each network's official API."})
    cards = [{"what": "Daily own posts on X for a brand (Social Engine lane)", "how": "Social Engine x_run_due"},
             {"what": "Publish to Instagram now through the official API", "how": "Social Engine MCP publish_instagram"}]
    monkeypatch.setattr(quickmap, "_match_capabilities", lambda q, **k: cards)
    monkeypatch.setattr(meaning, "score", lambda q, texts, **k: [0.40, 0.66])
    out = quickmap._tool_cards_block("does social engine publish through the API?")
    assert "Social Engine: Posts through each network's official API." in out
    assert "ON THIS QUESTION: Publish to Instagram now through the official API" in out
    monkeypatch.setattr(meaning, "score", lambda q, texts, **k: [0.40, 0.50])
    out = quickmap._tool_cards_block("how would I use social engine from my phone?")
    assert "ON THIS QUESTION" not in out and "official API" in out
