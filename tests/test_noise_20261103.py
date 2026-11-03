"""Real cases of 2026-11-03 (owner: "the map works by meaning and context, not word noise")."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quickmap  # noqa: E402


def _fake_meaning(monkeypatch, hits):
    mod = types.SimpleNamespace(query=lambda q, k=8, min_score=0.0: hits)
    monkeypatch.setitem(sys.modules, "meaning", mod)


def test_floor_drops_vague_message_noise(monkeypatch):
    # "por que no me podes hacer guita": Post Pilot / Chipmill entries at 0.55-0.57 were noise
    _fake_meaning(monkeypatch, [
        {"journal": "POST_PILOT_JOURNAL.md", "line": 1461, "heading": "x", "score": 0.57},
        {"journal": "CHIPMILL_JOURNAL.md", "line": 235, "heading": "y", "score": 0.565},
    ])
    hits, js = quickmap._prompt_meaning("Por que no me puede hacer guita ahora")
    assert hits == [] and js == set()


def test_floor_keeps_on_topic(monkeypatch):
    _fake_meaning(monkeypatch, [
        {"journal": "AI_TEAM_JOURNAL.md", "line": 2954, "heading": "Launch Desk", "score": 0.64},
        {"journal": "ADSCOPE_JOURNAL.md", "line": 95, "heading": "radar", "score": 0.50},
    ])
    hits, js = quickmap._prompt_meaning("En Launch Desk tienen que copiar los productos ganadores")
    assert [h["journal"] for h in hits] == ["AI_TEAM_JOURNAL.md"] and js == {"AI_TEAM_JOURNAL.md"}


def test_service_down_is_none_not_silence(monkeypatch):
    _fake_meaning(monkeypatch, [])
    assert quickmap._prompt_meaning("cualquier mensaje largo") == ([], None)


def test_negated_name_left_out_of_meaning_search():
    q = "el mapa muestre cosas con sentido, no que muestre Oddsboard si no estamos hablando de Oddsboard"
    out = quickmap._drop_negated_names(q)
    assert "Oddsboard" not in out and "mapa" in out
    assert "Oddsboard" in quickmap._drop_negated_names("como va Oddsboard hoy")


def test_negation_regex_matches_window_before_name():
    assert quickmap._NEGATED.search("no que muestre ")
    assert quickmap._NEGATED.search("si no estamos hablando de ")
    assert not quickmap._NEGATED.search("chekea como va ")


def test_card_flagged_when_a_later_ship_says_deployed(tmp_path):
    import server
    j = tmp_path / "ADSCOPE_JOURNAL.md"
    j.write_text("# ADSCOPE\n\n## Already exists\n- x\n\n"
                 "## 2026-10-29 02:36 [ship] ADSCOPE 4.0 DEPLOYED on gpubox (PC session)\nbody\n", encoding="utf-8")
    cap = {"what": "Turn ads into ranked winners", "how": "ADSCOPE 4.0 (PC: ADSCOPE/, git f26887a): adscope.py report",
           "status": "partial: built and tested on the PC, NOT deployed on gpubox yet", "since": "2026-10-29",
           "path": str(j)}
    out = server._mark_newer_ship([dict(cap)])[0]
    assert "status_newer" in out and "2026-10-29" in out["status_newer"]
    ok = dict(cap, status="working: deployed")
    assert "status_newer" not in server._mark_newer_ship([ok])[0]


def test_gate_counts_a_recent_read_from_an_earlier_message():
    # peer session ef2c7594, 2026-11-03 ~00:24 UTC: ADSCOPE_JOURNAL read by full path, then a cross-session message
    # bumped the message counter and two Reads of adscope.py were stopped "no read recorded"
    import time
    import quick_hook
    seen = {"n": 21, "rr": 1, "jr": {"adscope": 20}, "jt": {"adscope": time.time() - 120}}
    state, _ = quick_hook.gate(seen, "r:adscope", ["ADSCOPE_JOURNAL.md"], [], 'project "ADSCOPE"')
    assert state == "open"
    old = {"n": 21, "rr": 1, "jr": {"adscope": 5}, "jt": {"adscope": time.time() - 4000}}
    state, _ = quick_hook.gate(old, "r:adscope", ["ADSCOPE_JOURNAL.md"], [], 'project "ADSCOPE"')
    assert state == "deny"


def test_a_guard_named_after_a_piece_is_not_the_piece():
    import quick_hook
    keys = ["oddsboard", "oddsboard-bot", "bulkbot-real"]
    assert not quick_hook._key_hit(keys, "c:/nvc/tool shop/mods/oddsboard-gate/hooks/register.ts")
    assert not quick_hook._key_hit(keys, "c:/nvc/tool shop/mods/oddsboard-gate/tests/oddsboard-gate.test.ts")
    assert quick_hook._key_hit(keys, "/opt/oddsboard-bot/bulkbot.py")
    assert quick_hook._key_hit(keys, "systemctl restart bulkbot-real")


def test_reply_check_reads_only_the_proposal():
    reply = ("El mapa me tiro todo Oddsboard porque escribi Oddsboard como ejemplo.\n"
             "Varias son de crypto: el precio de SOL.\n\n"
             "Propuesta: armo la version limpia de tus reglas\n"
             "- reglas globales en una pagina\n\n"
             "Otra cosa sin propuesta.")
    part = quickmap._proposal_part(reply)
    assert "Oddsboard" not in part and "SOL" not in part and "reglas globales" in part
