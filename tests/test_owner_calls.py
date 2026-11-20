"""owner_calls.py: the no-AI end-of-turn check (owner 2026-11-11)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owner_calls  # noqa: E402

CARD = {"what": "List mails are approved by the Director, never sent to the owner as a yes/no", "journal": "X.md",
        "date": "2026-11-11"}


def test_ask_line_with_a_delegating_card_is_sent_back(monkeypatch):
    monkeypatch.setattr(owner_calls, "_delegated_cards", lambda line: [CARD])
    why = owner_calls.check("- [ ] Esperan tu sí: el mail de seguimiento a las 24 h y los mails #4 y #14")
    assert "OWNER CALLS CHECK" in why and "Director" in why


def test_lines_that_ask_nothing_pass_without_lookup(monkeypatch):
    def boom(line):
        raise AssertionError("looked up a line that asks nothing")
    monkeypatch.setattr(owner_calls, "_delegated_cards", boom)
    assert owner_calls.check("Ads review of the three campaigns on 11-14 at 15:00 local time.\nThe Director decides mails.") == ""


def test_ask_line_without_a_delegating_card_passes(monkeypatch):
    monkeypatch.setattr(owner_calls, "_delegated_cards", lambda line: [])
    assert owner_calls.check("- [ ] Esperan tu sí: prender el anuncio nuevo en Meta") == ""


def _transcript(tmp_path, tools):
    rows = [{"type": "user", "message": {"role": "user", "content": "do it"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i} for n, i in tools]}}]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


def test_promise_with_nothing_written_is_sent_back(tmp_path):
    t = _transcript(tmp_path, [("Bash", {"command": "ls"})])
    assert "promised" in owner_calls.check("Desde ahora le hago caso al mod por encima de cualquier lista vieja.", t)


def test_promise_kept_by_a_journal_write_passes(tmp_path):
    t = _transcript(tmp_path, [("mcp__journal__journal_decision_add", {})])
    assert owner_calls.check("From now on the Director decides the mails.", t) == ""


def test_promise_kept_by_a_rules_file_edit_passes(tmp_path):
    t = _transcript(tmp_path, [("Edit", {"file_path": "D:/work/x/.claude/CLAUDE.md"})])
    assert owner_calls.check("Desde ahora va en el global.", t) == ""


def test_off_switch(monkeypatch):
    monkeypatch.setenv("JOURNAL_OWNER_CALLS", "off")
    monkeypatch.setattr(owner_calls, "_delegated_cards", lambda line: [CARD])
    assert owner_calls.check("- Esperan tu sí: los mails #4 y #14") == ""


def test_quoted_ask_and_a_mid_line_red_mark_are_not_asks(monkeypatch):
    monkeypatch.setattr(owner_calls, "_delegated_cards", lambda line: [CARD])
    assert owner_calls.check('- Si te pongo "espera tu sí", "con vos" o el 🔴 sobre algo, me devuelve y lo corrijo.') == ""


def test_a_card_that_only_mentions_the_director_does_not_count():
    assert not owner_calls.DELEGATED.search("full owner app with a live Director chat, credit and library")
    assert owner_calls.DELEGATED.search("mails are approved by the Director, never an owner card")


def test_a_quoted_promise_is_not_a_promise(tmp_path):
    t = _transcript(tmp_path, [("Bash", {"command": "ls"})])
    assert owner_calls.check('El control de promesas ("desde ahora…" sin dejarlo escrito) sirve igual para cualquiera.', t) == ""


def test_a_quoted_line_of_product_copy_is_not_a_promise(tmp_path):
    """2026-11-16 real false alarm: the proposed text of a box on a sales page, shown in quotes for the owner's
    verdict, carries "from now on"; it is 104 characters long and the short quote pattern did not cover it."""
    t = _transcript(tmp_path, [("Bash", {"command": "ls"})])
    reply = ('Proposed text of the extra box, for your verdict: "Every project blueprint and job playbook we publish '
             'from now on lands in your library the day it ships". Does it go?')
    assert owner_calls.check(reply, t) == ""
    # the same words said by the session itself are still a promise
    assert "promised" in owner_calls.check("Every blueprint we publish from now on lands in your library.", t)


def _cards(monkeypatch, cards):
    import server
    monkeypatch.setattr(server, "_match_capabilities", lambda *a, **k: cards)


def test_the_decides_field_is_read_before_any_wording(monkeypatch):
    _cards(monkeypatch, [{"what": "Newsletter sends", "decides": "Ana", "journal": "J.md", "date": "2026-03-01"}])
    assert owner_calls._delegated_cards("waits for your yes: the newsletter send on Friday")
    assert "OWNER CALLS CHECK" in owner_calls.check("- [ ] waits for your yes: the newsletter send on Friday")


def test_a_card_that_keeps_it_with_the_owner_does_not_send_back(monkeypatch):
    _cards(monkeypatch, [{"what": "Ads go live only with my yes, approved by the Director first", "decides": "owner"}])
    assert owner_calls._delegated_cards("waits for your yes: turning the ad on") == []


def test_a_buyer_card_with_ai_deciding_counts(monkeypatch):
    _cards(monkeypatch, [{"what": "Reply to support tickets", "decides": "ai"}])
    assert owner_calls._delegated_cards("your call: the reply to the support ticket")
