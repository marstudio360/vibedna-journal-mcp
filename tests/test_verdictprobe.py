"""Verdict probe (2026-11-14 real miss: an "open in your browser to pay" button was proposed, built and previewed while
TONE_GARDEN_JOURNAL 2026-11-05 said, inside an entry about PayPal, that the "open in Safari" idea was withdrawn)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quickmap as Q  # noqa: E402
import verdictprobe as V  # noqa: E402

REPLY = """Investigué las dos cosas. Encontré una falla real nuestra.

- **1 fue una falla nuestra.** El servidor contestó mal al pedir el pago y el formulario nunca llegó.

**Lo que cambiaría, en todas las páginas que abren el pago**
1. Si el servidor contesta mal, que el sitio vuelva a pedir el pago solo, una vez.
2. Si el formulario sigue gris a los 5 segundos, que lo reintente y muestre una línea que señale el botón de PayPal.
3. Para quien entra desde la app de Facebook o Instagram: el aviso de "abrir en tu navegador" como botón arriba del pago, y los campos de tarjeta más arriba en la primera pantalla.

¿Hago los tres cambios y te muestro el 3 en una vista previa antes de publicarlo?"""

BULLET = ('- PAYPAL WORKS INSIDE FACEBOOK: Facebook app 3 people opened PayPal, 3 paid; normal browser 17 opened, 15 paid; '
          'Instagram app 1 opened, 0 paid (n=1). Paid purchases since 20/10 by browser: Facebook app 13 card + 3 PayPal, '
          'Instagram app 8 card. People do pay inside the apps; the "open in Safari" idea is NOT backed by our data and '
          'is withdrawn.')


def _index(tmp_path, monkeypatch, rows):
    db = tmp_path / "index.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE journals(path TEXT, name TEXT)")
    c.execute("CREATE VIRTUAL TABLE entries_fts USING fts5(path, line, heading, body)")
    for path, line, heading, body in rows:
        c.execute("INSERT OR IGNORE INTO journals VALUES (?, ?)", (path, Path(path).name))
        c.execute("INSERT INTO entries_fts VALUES (?, ?, ?, ?)", (path, line, heading, body))
    c.commit()
    c.close()
    monkeypatch.setattr(Q, "_conn", lambda: sqlite3.connect(db))


def test_proposal_lines_are_the_proposal_block_only():
    lines = V.proposal_lines(REPLY)
    assert any(ln.startswith("3. Para quien entra") for ln in lines)
    assert any(ln.startswith("1. Si el servidor") for ln in lines)
    assert not any("fue una falla nuestra" in ln for ln in lines)       # a finding, not a proposal
    assert V.proposal_lines("Publicado y verificado en vivo: el pago quedó con dos arreglos.") == []


def test_a_line_that_already_knows_the_verdict_is_skipped():
    r = "**Lo que cambiaría**\n- El botón de abrir en el navegador lo saqué: la idea se había descartado el 5 de noviembre."
    assert V.proposal_lines(r) == []


def test_the_real_miss_is_found_with_the_sentence_itself(tmp_path, monkeypatch):
    aa = str(tmp_path / "TONE GARDEN" / "TONE_GARDEN_JOURNAL.md")
    other = str(tmp_path / "OTHER" / "OTHER_JOURNAL.md")
    _index(tmp_path, monkeypatch, [
        (aa, 11274, "2026-11-05 19:17 [ventas] PAYPAL IN FB/IG MEASURED + EMAIL-STEP LEADS STAGE", BULLET),
        (aa, 900, "2026-10-01 10:00 [fix] Card form", "- The card was rejected by Stripe inside the Facebook app browser, "
                                                       "the pay button opened again and the buyer paid."),
        (other, 5, "2026-09-01 10:00 [work] Install", "- The zip install on the buyer PC with the server form and the pay "
                                                       "page inside the app browser: that approach is discarded."),
    ])
    folders = {Q._fold(str(Path(aa).parent))}
    why = V.reply_check(REPLY, folders)
    assert "RULED OUT BEFORE" in why and "open in Safari" in why and "TONE_GARDEN_JOURNAL.md:11274" in why
    assert "3. Para quien entra" in why and "1. Si el servidor" not in why
    assert "OTHER_JOURNAL" not in why                       # another project never counts
    assert "rejected by Stripe" not in why                  # a machine answer is not a verdict on an idea
    assert V.reply_check(REPLY, set()) == ""                # no project scope: silent
    assert V.reply_check(REPLY, folders, before="2026-11-05") == ""


def test_write_hint_only_for_an_idea_ruled_out():
    assert V.write_hint('People do pay inside the apps; the "open in Safari" idea is NOT backed by our data and is withdrawn.')
    assert V.write_hint("The 1-hour re-loop plan is discarded: the owner wants 10-minute videos for volume.")
    assert V.write_hint("Opción B queda descartada con datos: los foreign son bots.")
    assert not V.write_hint("The card was rejected by Stripe with a test number, as expected.")
    assert not V.write_hint("OK: Stripe proceso el pago (rechazo por tarjeta de prueba).")
    assert not V.write_hint("Shipped the retry and the failure message; 17 of 17 payment runs passed.")
    # a retelling: the verdict sits inside a long quote
    assert not V.write_hint("On the box write_hint fires on the 'open in Safari idea is not backed by our data and is "
                            "withdrawn' sentence and stays silent on the other.")
    assert not V.write_hint("MOD MISS: the idea was withdrawn and then built again.", tag="mod-miss")


def test_switch_off(monkeypatch):
    monkeypatch.setenv("JOURNAL_VERDICT_PROBE", "off")
    assert V.write_hint("the idea is withdrawn and stays withdrawn for good") == ""
    assert V.reply_check(REPLY, {"x"}) == ""


def test_a_line_that_names_a_product_needs_a_verdict_that_names_it_too(tmp_path, monkeypatch):
    """2026-11-20: a plans page line that named a product was matched to a content calendar line of another brand
    on everyday words (day, free, loads, page, ships). A line that names no product is read as before."""
    aa = str(tmp_path / "TONE GARDEN" / "TONE_GARDEN_JOURNAL.md")
    _index(tmp_path, monkeypatch, [
        (aa, 11274, "2026-11-05 19:17 [ventas] PAYPAL IN FB/IG MEASURED + EMAIL-STEP LEADS STAGE", BULLET)])
    folders = {Q._fold(str(Path(aa).parent))}
    monkeypatch.setattr(Q, "_entities_in",
                        lambda text, kinds=(): [{"name": "Shopsite Pro"}] if "Shopsite Pro" in text else [])
    named = REPLY.replace("3. Para quien entra", "3. En Shopsite Pro, para quien entra")
    assert V.reply_check(named, folders) == ""        # the journal, the entry title and the line never name it
    hits = V.reply_hits(REPLY, folders)               # no product named: found as before
    assert len(hits) == 1 and hits[0]["line"].startswith("3. Para quien entra")
    case = V.judge_item(hits[0])                      # and it goes to the alarm judge as its own kind of case
    assert case["kind"] == "ruled_out" and case["reply"].startswith("3. Para quien entra") and case["hit"] is hits[0]
    assert case["entry"].startswith("TONE_GARDEN_JOURNAL.md (2026-11-05 19:17) says:") and "withdrawn" in case["entry"]
    assert V.render(hits) == V.reply_check(REPLY, folders) and V.render([]) == ""
    (tmp_path / "b").mkdir()
    both = BULLET.replace('the "open in Safari" idea', 'for Shopsite Pro the "open in Safari" idea')
    _index(tmp_path / "b", monkeypatch, [(aa, 11274, "2026-11-05 19:17 [ventas] PAYPAL IN FB/IG MEASURED", both)])
    assert "RULED OUT BEFORE" in V.reply_check(named, folders)   # the entry names the product too
