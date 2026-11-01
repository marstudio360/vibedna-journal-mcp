"""A Decided card whose value a later entry restates differently is served with a NEWER VALUE warning.

Real case 2026-11-01 (owner: "if the journal says the journals went down to 27 after we said 99, the mod has to tell
you"): SHOPSITE_FULL_JOURNAL's Decided card of 2026-08-04 said "Sold journal prices stay high ($99 ...)"; from
2026-08-20 every journal sold at $27, and the 2026-10-01 ship entry said "Precio: $27 como todos los journals en la
tienda". No change word, no [decision] tag, so newer_change() missed it and the session quoted $99 to the owner.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-newer-value-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meaning  # noqa: E402
import server as s  # noqa: E402

CARD = ('- **Sold journal prices stay high ($99 for the flagship journals); never lower or discount them to chase first '
        'sales.** · date: 2026-08-04 · why: Owner 2026-08-04, overruling a lower-price recommendation · aliases: journal '
        'price, precio journals, pricing, $99, discount, descuento, bajar precio, first sales, journal marketplace, '
        '/journals · see: SHOPSITE_FULL_JOURNAL 2026-08-04 23:24 [decision] PRICING DECISION Journal Marketplace')
SHIP = ('## 2026-10-01 18:19 [ship] JOURNAL VENDIDO EN VIVO: "Make Your Site Agent-Readable" ($27)\n\n'
        '- Pipeline: seed en lib/journals-catalog.ts (priceCents 2700, wordCount 2967).\n'
        '- Precio: $27 como todos los journals en la tienda (los 9900 de la tabla vieja del script son metadata, '
        'no el precio cobrado).\n\n---\n\n')
TABLE = ('## 2026-09-01 10:00 [ship] Store table\n\n| Social Engine MCP | $47 | journals bundle |\n\n---\n\n')
OTHER = ('## 2026-09-02 10:00 [ship] Logo\n\nThe Webweave Pro plan costs $19 a month for the browser.\n\n---\n\n')


def _journal(*entries: str) -> str:
    return "# SHOPSITE\n\n## Decided\n\n" + CARD + "\n\n## Recent entries\n\n" + "".join(entries)


def _card(text: str) -> dict:
    caps = s._parse_capabilities(text, s._SEC_DECIDED)
    assert len(caps) == 1
    return caps[0]


def _fake_score(table: dict):
    def score(q, texts, timeout=3.0):
        return [next((v for k, v in table.items() if k in t), 0.3) for t in texts]
    return score


def test_real_case_newer_value_found(monkeypatch):
    monkeypatch.setattr(meaning, "score", _fake_score({"Precio: $27": 0.63}))
    text = _journal(SHIP)
    nv = s.newer_value(_card(text), text)
    assert nv and nv["date"] == "2026-10-01"
    assert "$27 como todos los journals" in nv["sentence"]


def test_served_with_warning_in_front(tmp_path, monkeypatch):
    monkeypatch.setattr(meaning, "score", _fake_score({"Precio: $27": 0.63}))
    f = tmp_path / "SHOPSITE_FULL_JOURNAL.md"
    f.write_text(_journal(SHIP), encoding="utf-8")
    card = {**_card(f.read_text(encoding="utf-8")), "path": str(f), "journal": f.name}
    out = s._mark_changed([card])[0]
    assert out["what"].startswith("[NEWER VALUE 2026-10-01: ")
    assert "mark this card SUPERSEDED now" in out["what"][:400]


def test_below_floor_or_no_service_says_nothing(monkeypatch):
    text = _journal(SHIP)
    monkeypatch.setattr(meaning, "score", _fake_score({"Precio: $27": 0.60}))
    assert s.newer_value(_card(text), text) is None
    monkeypatch.setattr(meaning, "score", lambda q, texts, timeout=3.0: [])
    assert s.newer_value(_card(text), text) is None


def test_table_rows_and_other_things_never_flag(monkeypatch):
    # a price table row, and a price of another thing (no shared word next to the number)
    monkeypatch.setattr(meaning, "score", _fake_score({"$47": 0.9, "$19": 0.9}))
    text = _journal(TABLE, OTHER)
    assert s.newer_value(_card(text), text) is None


def test_superseded_card_is_left_alone(monkeypatch):
    monkeypatch.setattr(meaning, "score", _fake_score({"Precio: $27": 0.9}))
    text = _journal(SHIP).replace("- **Sold journal", "- **SUPERSEDED (checked 2026-11-01). Old card: Sold journal")
    assert s.newer_value(_card(text), text) is None
