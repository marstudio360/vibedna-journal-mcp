"""A Decided card overtaken by a later decision entry is served with a CHANGED LATER warning, never as current.

Real case 2026-10-30 (owner: "why did the mod not show you, we changed everything, the business review is gone"):
MAPLEWORKS_JOURNAL's Decided card of 2026-10-27 said "(1) Business Review 97 USD"; the 2026-10-28 19:28 entry said
the Business Review becomes FREE and "Supersedes the 2026-10-27 card item (1)". The map, the before-build hook and
journal_search kept showing the old card as what the owner decided, and the session repeated it to the owner.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-decided-changed-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s  # noqa: E402

# The real card and entries, shortened only where nothing depends on the words.
CARD = ('- **Mapleworks sells exactly three things (replaces the four tiers, the build prices by kind and the 990 '
        'template): (1) Business Review 97 USD: a pro review of the business, credited in full to the setup; (2) the '
        'AI team, ONE price for everyone: setup 2,500 USD; (3) Partner: US$300/month + 20% of sales.** · date: '
        '2026-10-27 · why: Owner 2026-10-27 (PC chat) · aliases: offers, ofertas, pricing, precios, Business Review, '
        '97, AI team, 2500, 300, 1000, partner, socio, Business Upgrade, Business Plan, template, plantilla, 990, '
        '/start, /partner · see: PC chat 2026-10-27')
ORIGIN = ('## 2026-10-27 01:00 [decision] Offers cut to three\n\nOwner: only business review, the company and partners; '
          'this replaces Business Upgrade and Business Plan.\n\n---\n\n')
CHANGE = ('## 2026-10-28 19:28 [decision] Owner decision 2026-10-28 (PC chat): the Business Review becomes FREE (replaces \n\n'
          'Owner decision 2026-10-28 (PC chat): the Business Review becomes FREE (replaces the 97 USD paid review). '
          'Flow, owner\'s words simplified: (1) in the mapleworks.dev chat the visitor gives business, website, socials. '
          'Supersedes the 2026-10-27 card item (1) "Business Review 97 USD" and the earlier free-diagnosis sketch.\n\n---\n\n')
NOISE = ('## 2026-10-29 10:00 [ship] Partner page copy\n\nThe /partner page now shows the 20% split; the Business Review '
         'link in the footer was checked live.\n\n---\n\n## 2026-10-29 11:00 [fix] Logo\n\nThe old logo file was replaced '
         'by the gold sphere.\n\n---\n\n')


def _journal(*entries: str) -> str:
    return "# MAPLEWORKS\n\n## Decided\n\n" + CARD + "\n\n" + "".join(entries)


def _card(text: str) -> dict:
    caps = s._parse_capabilities(text, s._SEC_DECIDED)
    assert len(caps) == 1
    return caps[0]


def test_real_case_card_is_marked_changed():
    text = _journal(ORIGIN, CHANGE)
    ch = s.newer_change(_card(text), text)
    assert ch and ch["date"] == "2026-10-28"
    assert "Business Review becomes FREE" in ch["sentence"] or "Supersedes the 2026-10-27 card" in ch["sentence"]


def test_served_with_warning_in_front(tmp_path):
    f = tmp_path / "MAPLEWORKS_JOURNAL.md"
    f.write_text(_journal(ORIGIN, CHANGE), encoding="utf-8")
    card = {**_card(f.read_text(encoding="utf-8")), "path": str(f), "journal": f.name}
    out = s._mark_changed([card])[0]
    assert out["what"].startswith("[CHANGED LATER 2026-10-28: ")
    assert "Follow the newer entry and fix this card]" in out["what"][:240]
    assert out["changed_later"]["date"] == "2026-10-28"


def test_every_decided_consumer_gets_the_warning(tmp_path, monkeypatch):
    # journal_search, journal_before_build, the before-build hook and the quick map all read decisions here.
    f = tmp_path / "MAPLEWORKS_JOURNAL.md"
    f.write_text(_journal(ORIGIN, CHANGE), encoding="utf-8")
    card = {**_card(f.read_text(encoding="utf-8")), "path": str(f), "journal": f.name, "project": "Mapleworks"}
    monkeypatch.setattr(s, "_all_capabilities", lambda sections=s._SEC_EXISTS: [dict(card)] if sections == s._SEC_DECIDED else [])
    got = s._match_capabilities("what does Mapleworks sell, the Business Review and the AI team", sections=s._SEC_DECIDED)
    assert got and got[0]["what"].startswith("[CHANGED LATER 2026-10-28: ")
    assert not s._match_capabilities("Business Review AI team", sections=s._SEC_EXISTS)


def test_card_updated_after_the_change_is_current_again():
    text = _journal(ORIGIN, CHANGE).replace("· date: 2026-10-27 ·", "· date: 2026-10-27 · updated: 2026-10-30 ·")
    assert s.newer_change(_card(text), text) is None


def test_own_origin_and_unrelated_later_entries_do_not_fire():
    text = _journal(ORIGIN, NOISE)
    assert s.newer_change(_card(text), text) is None


def test_one_alias_without_date_is_not_enough():
    text = _journal("## 2026-10-29 09:00 [fix] Footer\n\nThe pricing table no longer scrolls sideways on phones.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_ship_log_naming_the_card_words_is_not_a_change():
    # Real false alarm of the first version: a ship line about a mail worker matched the Emails decision.
    text = _journal("## 2026-10-29 12:00 [ship] Offers page\n\nThe Business Review button no longer opens the old "
                    "AI team form; it was replaced by the chat.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_decision_naming_the_card_without_a_change_word_is_not_a_change():
    text = _journal("## 2026-10-29 09:00 [decision] Headlines\n\nThe Business Review and the AI team pages get a "
                    "new headline.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_decision_with_one_matching_word_is_not_a_change():
    text = _journal("## 2026-10-29 09:00 [decision] Logo\n\nThe gold sphere replaces the old crescent on the partner "
                    "page.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_supersedes_naming_other_dates_leaves_this_card_alone():
    # Real false alarm: "Supersedes the 2026-10-27 card item (1)" also marked every other 2026-10-27 card, and an
    # OWNER RULE superseding the 2026-10-22 and 2026-10-23 lines marked a 2026-10-27 card.
    text = _journal("## 2026-10-29 02:29 [decision] OWNER RULE\n\nSUPERSEDES the 2026-10-22 pricing model and the "
                    "2026-10-23 AI team offers line.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None
    other = text.replace("· date: 2026-10-27 ·", "· date: 2026-10-23 ·")
    assert s.newer_change(_card(other), other)


def test_two_loose_words_are_not_enough():
    # Real false alarms: "owner" + "cards" marked the product name card; "studios" + "mcp" marked the API card.
    text = _journal("## 2026-10-29 09:00 [decision] Pages\n\nThe partner template is replaced by a shorter one.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_one_specific_word_without_a_date_is_not_enough():
    text = _journal("## 2026-10-29 09:00 [decision] Ebook\n\nThe ebook price becomes 97 USD.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


def test_ship_log_superseding_without_a_date_is_not_a_change():
    text = _journal("## 2026-10-29 02:23 [fix] Board\n\nCleared stale cards: the Business Review and 97 USD cards "
                    "superseded by the week plan were set to done.\n\n---\n\n")
    assert s.newer_change(_card(text), text) is None


LIVE_OLD = ('- **mapleworks.dev shows one of our AI companies working LIVE (a public live stream of its office, captions), '
            'as the main proof for the AI Team offer.** · date: 2026-10-24 · why: Owner plan 2026-10-23/24 · aliases: '
            'live, en vivo, streaming, stream, live demo, mapleworks.dev/live, captions, showcase, proof · see: AI_TEAM_JOURNAL')
LIVE_NEW = ('- **mapleworks.dev/live is a looping DEMO company (scripted, always busy), marked "demo"; no real company data is '
            'streamed for now. Replaces the earlier plan of streaming Launch Desk captions.** · date: 2026-10-25 · why: '
            'Owner 2026-10-26: "only the loop, but honest" · aliases: live, en vivo, streaming, demo, loop, '
            'mapleworks.dev/live, showcase · see: PC chat 2026-10-26; previous card (2026-10-24 plan) in this Decided section')
SOURCES_ONLY = ('- **Social posts never name our companies; this supersedes the rotation of brands.** · date: 2026-10-29 · '
                'why: owner rule · aliases: live, streaming, showcase, proof · see: 2026-10-24 18:00 [decision]; '
                '2026-10-22 19:26 [decision]')


def test_later_card_replacing_an_earlier_card_marks_it():
    # Real case: the 2026-10-24 "stream one of our companies LIVE" card stayed next to the 2026-10-25 demo card
    # that replaced it, and the map served the old one first.
    text = "# M\n\n## Decided\n\n" + LIVE_OLD + "\n" + LIVE_NEW + "\n"
    old = next(c for c in s._parse_capabilities(text, s._SEC_DECIDED) if c["date"] == "2026-10-24")
    ch = s.newer_change(old, text)
    assert ch and ch["date"] == "2026-10-25" and ch["heading"] == "a later Decided card"


def test_later_card_citing_the_date_only_as_a_source_does_not_mark_it():
    text = "# M\n\n## Decided\n\n" + LIVE_OLD + "\n" + SOURCES_ONLY + "\n"
    old = next(c for c in s._parse_capabilities(text, s._SEC_DECIDED) if c["date"] == "2026-10-24")
    assert s.newer_change(old, text) is None


def test_card_already_marked_superseded_is_not_flagged_again():
    text = "# M\n\n## Decided\n\n" + LIVE_OLD.replace("- **mapleworks.dev shows", "- **SUPERSEDED 2026-10-25 by the demo card. mapleworks.dev shows") + "\n" + LIVE_NEW + "\n"
    old = next(c for c in s._parse_capabilities(text, s._SEC_DECIDED) if c["date"] == "2026-10-24")
    assert s.newer_change(old, text) is None


def test_card_without_date_is_left_alone():
    text = _journal(CHANGE).replace(" · date: 2026-10-27", "")
    assert s.newer_change(_card(text), text) is None
