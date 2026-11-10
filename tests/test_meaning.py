"""Meaning search finds the entry that says the same thing in other words or the other language.

Real cases where every word layer missed:
- 2026-10-30: owner asked for "el embudo de Ambient Foundations"; the entry was titled "SELECTOR DE COMPRA EN LAS 9
  FICHAS DE AMBIENT FOUNDATIONS" (an upsell modal) in a month archive; the map showed drone and pads ships instead.
- 2026-10-29: "apagar Link" never matched the decision "Stripe Link is never turned off".
- 2026-10-28: Shapesmith was named only in entry bodies, the map read titles.
- 2026-10-30: "funnel post compra de eternity" against "ETERNITY POST-PURCHASE FUNNEL LIVE".
Each query must rank its entry in the first two among real near-miss entries (same product words, other topic);
the map shows five. The Eternity query also ranks the 10-30 "pack credit inside funnels" entry high: same topic.
Skipped when fastembed is not installed (the meaning layer is optional).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastembed")
pytest.importorskip("numpy")

_TMP = Path(tempfile.mkdtemp(prefix="journal-meaning-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meaning  # noqa: E402

# meaning reads JOURNAL_HOME and meaning.json once, at import, and another test file may have imported it first
# (2026-11-01: in the full suite every test here ran on that other file's index, "assert 25 == 7"). The module's own
# paths and backend are pointed at this file's temp home instead, and only while these tests run.
_OWN = {"HOME": _TMP, "DB": _TMP / "index.sqlite", "CONF": _TMP / "meaning.json", "_SYNC_LOCK": _TMP / "meaning-sync.lock",
        "URL": "", "MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "OFF": False}


@pytest.fixture(scope="module", autouse=True)
def _own_home():
    old = {k: getattr(meaning, k) for k in _OWN}
    for k, v in _OWN.items():
        setattr(meaning, k, v)
    yield
    for k, v in old.items():
        setattr(meaning, k, v)

ENTRIES = [
    ("AA_2026-09.md", 1968, "2026-09-27 22:01 [ship] SELECTOR DE COMPRA EN LAS 9 FICHAS DE AMBIENT FOUNDATIONS (Owner: \"el modal de",
     "SELECTOR DE COMPRA EN LAS 9 FICHAS DE AMBIENT FOUNDATIONS (Owner: \"el modal de upsell de /pack1 pero con el bundle "
     "de Foundations y Calmline, en todos los Foundations del catalogo, sin romper nada\"). Nuevo FoundationsBuy.tsx: "
     "\"Buy Now\" abre una hoja con dos paneles, Foundations Bundle ($47) y Calmline ($97)."),
    ("AA.md", 1930, "2026-10-09 20:21 [ship] DRONE FOUNDATIONS VOL. 1 DE VUELTA EN VENTA CON EL PACK V4",
     "Drone Foundations Vol 1 back on sale with the v4 pack: names without instrument, D#, F# and G with 3 options each."),
    ("AA.md", 1603, "2026-10-08 20:45 [ship] PACK DE PADS AMBIENT TERMINADO (2026-10-08). 5 disenos",
     "Ambient pads pack finished: 5 designs (Warm, Glass, Evolving, Dark, Choir), 50 pads, Foundations style covers."),
    ("AA.md", 395, "Decided",
     "- **Stripe Link is never turned off and never pushed down in any Tone Garden checkout (it brings most card "
     "sales); the approved checkout change is only its LOOK.**"),
    ("AA.md", 7570, "2026-10-29 03:45 [ship] ETERNITY POST-PURCHASE FUNNEL LIVE 2026-10-29 (PC AA Director with the owner)",
     "/eternity buyers land on /next/eternity-generator instead of the library. Steps: generator $47 one-time -> yes: "
     "Calmline lifetime $97 -> no: Calmline year $49 -> no: Calmline month $20."),
    ("SHOPSITE_FULL.md", 6121, "2026-10-27 18:08 [ship] CRAFT ENGINES CONNECTED",
     "shapesmith-cli release builds OK; the brands' studios call the craft engines (Shapesmith vector mandalas, "
     "Fxmaker) from the box."),
    ("AA.md", 8456, "2026-10-30 13:19 [ship] CALMLINE $149 LIST + ETERNITY PACK CREDIT + NO 40% CODE INSIDE FUNNELS",
     "Calmline list price $149; the Eternity pack is taken off Calmline in the funnel ($82 / $88)."),
]

CASES = [
    ("el embudo de ambient foundations", ("AA_2026-09.md", 1968)),
    ("upsell de Foundations, que paso con eso", ("AA_2026-09.md", 1968)),
    ("apagar Link en el checkout", ("AA.md", 395)),
    ("turn off Stripe Link in checkout", ("AA.md", 395)),
    ("funnel post compra de eternity", ("AA.md", 7570)),
    ("compilar Shapesmith y diseñar el primer mandala vectorial", ("SHOPSITE_FULL.md", 6121)),
]


@pytest.fixture(scope="module")
def index():
    c = sqlite3.connect(str(meaning.DB))
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(path UNINDEXED, line UNINDEXED, heading, body)")
    c.executemany("INSERT INTO entries_fts(path, line, heading, body) VALUES(?,?,?,?)", ENTRIES)
    c.commit()
    c.close()
    r = meaning.sync()
    assert r["embedded"] == len(ENTRIES)
    return meaning._Index()


@pytest.mark.parametrize("q,want", CASES)
def test_meaning_ranks_the_entry_on_top(index, q, want):
    hits = index.search(q, k=3, min_score=-1)
    assert want in [(h["journal"], h["line"]) for h in hits[:2]], (q, hits)


def test_resync_only_changed(index):
    c = sqlite3.connect(str(meaning.DB))
    c.execute("UPDATE entries_fts SET body = body || ' extra' WHERE line = 1930")
    c.commit()
    c.close()
    r = meaning.sync()
    assert r["embedded"] == 1 and r["removed"] == 0


def test_query_never_raises_without_service(monkeypatch):
    monkeypatch.setattr(meaning, "OFF", False)
    monkeypatch.setattr(meaning, "PORT", 1)
    monkeypatch.setattr(meaning, "_start_service", lambda: None)
    assert meaning.query("anything at all") == []


def test_slow_service_never_starts_a_second_copy(monkeypatch):
    """2026-10-30: a slow (loading) service made every owner message start one more copy: 10 copies froze the PC.
    Only a refused connection (nobody holds the port) may start one."""
    monkeypatch.setattr(meaning, "OFF", False)
    started = []
    monkeypatch.setattr(meaning, "_start_service", lambda: started.append(1))

    def slow(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(meaning.urllib.request, "urlopen", slow)
    assert meaning.query("anything") == [] and started == []

    def refused(*a, **k):
        raise meaning.urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    monkeypatch.setattr(meaning.urllib.request, "urlopen", refused)
    assert meaning.query("anything") == [] and started == [1]


def test_second_embedder_waits(index):
    assert meaning._take_sync_lock()
    try:
        assert meaning.sync() == {"busy": True}
    finally:
        meaning._SYNC_LOCK.unlink()


def test_strict_search_says_when_it_did_not_answer(monkeypatch):
    """2026-11-04: a slow answer looked like "nothing found" and a check passed on it. query_strict retries once with
    more time, then raises Down; query() keeps returning [] for maps and notes."""
    monkeypatch.setattr(meaning, "OFF", False)
    monkeypatch.setattr(meaning, "_start_service", lambda: None)
    tries = []

    def slow(url, timeout=0):
        tries.append(timeout)
        raise TimeoutError("timed out")
    monkeypatch.setattr(meaning.urllib.request, "urlopen", slow)
    import pytest
    with pytest.raises(meaning.Down):
        meaning.query_strict("anything", timeout=1.0, retry_timeout=4.0)
    assert tries == [1.0, 4.0]
    assert meaning.query("anything") == []
