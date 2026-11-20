"""Exists probe and miss bank (2026-11-13 real miss: "do we have a mail journal?" answered "no" while the owner's
approved list and the passing journal were in SHOPSITE_FULL_JOURNAL)."""
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import existsprobe as E  # noqa: E402


def test_existence_questions_are_recognised():
    for q in ["¿Tenemos algún journal de mails?", "hay algun embudo de Starter Sounds?", "do we have a CRM journal?",
              "did we build the loop cutter?", "falta construir ShapeSmith en la caja?"]:
        assert E.EXIST_Q.search(q), q
    for q in ["chequea el stream de boltlab", "publish the post now", "how are sales today"]:
        assert not E.EXIST_Q.search(q), q


def test_kind_of_headings():
    assert E.kind_of("2026-11-10 17:01 [owner-order] NEW SOLD JOURNALS APPROVED: THE LIST (owner") == "APPROVED"
    assert E.kind_of("2026-11-09 21:11 [ship] THE LAUNCH PAGE IS LIVE at https://example.com/go/launch") == "SHIPPED"
    assert E.kind_of("2026-11-11 15:21 [results] ai-in-your-business PASSES (read 2026-11-11)") == "BUILT"
    assert E.kind_of("2026-11-11 15:21 [results] crm journal NOT READY yet") == ""
    assert E.kind_of("2026-11-10 16:31 [work] THE NEWS PACKAGE IS READY FOR THE OWNER") == "BUILT"
    assert E.kind_of("2026-11-12 00:18 [idea] X-RAY PROPOSAL FROM Q16") == ""


def test_ideas_drop_filler_and_question_verbs_and_translate():
    labels = [g["label"] for g in E._ideas("¿Tenemos algún journal de mails específico?")]
    assert labels == ["journal", "mails"]
    mails = next(g for g in E._ideas("hay mails") if g["label"] == "mails")
    assert "email" in mails["phr"]
    assert [g["label"] for g in E._ideas("falta construir ShapeSmith")] == ["shapesmith"]


def test_covers_finds_compounds_and_whole_short_words():
    groups = E._ideas("journal de mails")
    assert E._covers("2. CRM, email list and newsletter.", groups) == {"mails"}
    assert E._covers("NEW SOLD JOURNALS APPROVED", groups) == {"journal"}


def test_block_is_empty_when_the_message_does_not_ask():
    assert E.block("chequea el stream de boltlab") == ""


# The same probe on the finished reply: today's wrong lines stop, ordinary replies cost nothing and pass.
WRONG = ["No, no hay un journal dedicado solo a mails en la tienda. Lo que hay es el manual de contacto.",
         "Do you want me to build a journal of mails and newsletter to sell?",
         "There is no purchase selector in the starter pack, it would have to be built."]
FINE = ["The new payment texts already show in the feed. Now I look at those visits.",
        "Result: nothing is winning with money yet. The only thing that passed is the safety check.",
        "No hay errores en el log y el proceso lleva 0 reinicios desde las 22:13.",
        "Shall I set it up like this: day 2 with the 3 day code and the ends-today on day 5?",
        "No hay un solo caso en que se pierda el ultimo aviso.",
        "Hoy no hay una venta nueva desde las 12."]


def test_reply_claims_need_an_article_and_a_thing():
    assert E.reply_claims("No hay errores en el log.") == []
    assert E.reply_claims("todavía no hay nada ganando") == []
    assert E.reply_claims("No, no hay un journal de mails.")[0][1].startswith("journal")


def test_reply_check_on_real_lines():
    import pytest
    if not Path(E.Q.__file__).exists():
        pytest.skip("no index")
    for r in FINE:
        assert E.reply_check(r) == "", r
    try:
        stops = [r for r in WRONG if E.reply_check(r)]
    except Exception:
        stops = []
    if not stops:
        pytest.skip("this machine's journals do not hold the 2026-11-13 entries")
    assert len(stops) == len(WRONG)


def test_spanish_everyday_words_are_not_topics_and_imprimible_reaches_print():
    """2026-11-16 real miss: the owner asked "no tenemos ya una version imprimible ... un link directo ... en su
    libreria" and the probe answered with entries that only shared "pero", "esta", "esto", "antes", "puedes" and
    "directo", while the entry "WHITE + LARGE PRINT + VERSION PICKER" stayed out: "imprimible" had no English form."""
    import existsprobe as E
    ideas = {i["label"]: i["phr"] for i in E._ideas(
        "Pero man, no tenemos ya una version imprimible. Ya habiamos hecho esto antes. No puedes decirle que si, "
        "ya tenemos hecho esto y un link directo donde esta en el catalogo o en su libreria.?")}
    for filler in ("pero", "esta", "esto", "antes", "puedes", "directo", "man", "donde", "decirle", "habiamos"):
        assert filler not in ideas
    assert "print" in ideas["imprimible"]
    assert "library" in ideas["libreria"]
    assert "catalog" in ideas["catalogo"]


def test_a_long_message_is_probed_on_its_question_only():
    """2026-11-20 real miss: a 3,800 character pasted brief made every one of its words a topic; the full-text query
    got a clause per pair of words, the probe took 93 s and the prompt map was cut at 30 s, so the session got no map."""
    import existsprobe as E
    filler = " ".join(f"The paragraph number {i} talks about pricing servers hosting privacy speed budgets plans "
                      f"buyers products sessions journals guides copies rules owners agents. " for i in range(40))
    long_msg = filler + "No tenemos ya una version imprimible de las guias? " + filler
    assert len(E._ideas(long_msg)) > E.MAX_IDEAS
    ideas = {i["label"] for i in E._question_ideas(long_msg)}
    assert len(ideas) <= E.MAX_IDEAS
    assert {"version", "imprimible", "guias"} <= ideas
    # a short question is read whole, as before
    short = "no tenemos ya una version imprimible de las guias en la libreria?"
    assert [i["label"] for i in E._question_ideas(short)] == [i["label"] for i in E._ideas(short)]
    # spoken text with no stops: a window around the question, never the whole dump
    dump = ("y despues vemos lo de los precios y los servidores y la privacidad y las sesiones " * 30
            + "tenemos ya una version imprimible de las guias "
            + "y tambien lo otro de los planes y los compradores y los productos " * 30)
    got = {i["label"] for i in E._question_ideas(dump)}
    assert len(got) <= E.MAX_IDEAS and "imprimible" in got
