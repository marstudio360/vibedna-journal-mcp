"""Real cases of 2026-11-03 (owner: "the mod is supposed to be intelligent, it has to keep the context always").

1. A session re-proposed "bigger orders to buy premium" (ACCIONES 40 lost on 02/11) and reported a gap: the reply
   gate must send it back. A reply that reports a fix, and one that follows the open thread, must pass.
2. An angry "ya te dije ... DANDO VUELTAS" got no map at all (meaning floor) and then, once mapped, word maps of
   "dije", "dando", "vueltas" (shouting read as names).
3. A session wrote its own Playwright script to read the DMs sent to @demoacct_; the tools map showed Bidbot and
   Gumroad and never the card made for that job; a settings edit and an unrelated file got false tool stops.
The judge cases need the logged-in claude command (JOURNAL_JUDGE=on); without it they are skipped.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import judge  # noqa: E402
import owner_brief  # noqa: E402

needs_judge = pytest.mark.skipif(not judge.available(), reason="no judge (JOURNAL_JUDGE off or no claude command)")

BRIEF = {"by": "judge", "hash": "x", "t": 0, "lines": [
    "- RULE [02/11] Gap findings reported only with lab change tested same turn; owner: \"measure X next\" or "
    "\"one more arm\" is not a deliverable.",
    "- LOST [02/11] ACCIONES 40 / ce_acc40 (bigger orders to earn more premium): net -0.31% vs ctl, lone legs up.",
    "- LOST [02/11] EV market selection by premium: best predicted quintile +13.5 -> -51.5 actual.",
    "- OPEN [03/11] Scale test r3/r5/r10/r20 vs ctl and bulkbot-real; 24h read 04/11 02:10 UTC."]}

BAD = ("No, ningun bot de practica esta ganando. La brecha con los ganadores esta en el premio: ellos cobran 4% por "
       "dolar operado y nosotros 0,7%. La unica idea nueva que apunta al premio es la del Strategist: ce_hold pero con "
       "ordenes mas grandes (MIN_ACC 100) en los mercados que exigen un minimo mas alto, para cobrar mas premio por "
       "cada dolar puesto. La instalo ahora en el laboratorio y corto las variantes que ya perdieron?")
BAD2 = ("Los paper siguen todos en negativo. La brecha con los ganadores esta en el premio. Propongo medir manana la "
        "brecha de premio por mercado contra los 23 ganadores seguidos, y con eso decidimos que variante nueva armar.")
GOOD = ("Esta instalado: el bot real ya no se cae cuando Oddsboard lo frena, espera y reintenta hasta unos 2 minutos. "
        "La comparacion papel contra real volvio a escribir a las 16:48 UTC. 9 scripts del cron ya andan con la API "
        "nueva. La prueba de dano reproduce la caida real de hoy y con el arreglo pasan las 22.")
FOLLOW = ("Lo que quedo abierto ayer es la prueba de escala: r3/r5/r10/r20 con las reglas del bot real. La mido ahora con "
          "datos limpios desde las 02:09 y si la ganancia por mercado sigue positiva hasta algun N, agrando el bot real.")


@pytest.fixture
def brief(tmp_path, monkeypatch):
    monkeypatch.setattr(owner_brief, "DIR", tmp_path)
    p = tmp_path / "FORECAST_MARKETS_JOURNAL.md"
    p.write_text("# x\n", encoding="utf-8")
    (tmp_path / "forecastmarkets.json").write_text(json.dumps(BRIEF), encoding="utf-8")
    return str(p)


@needs_judge
@pytest.mark.parametrize("reply", [BAD, BAD2])
def test_reply_gate_sends_back_a_repeated_proposal(brief, reply):
    why = owner_brief.stop_check(reply, [brief])
    assert why.startswith("OWNER BRIEF CHECK"), why
    assert "your words:" in why


@needs_judge
@pytest.mark.parametrize("reply", [GOOD, FOLLOW])
def test_reply_gate_lets_a_good_reply_through(brief, reply):
    assert owner_brief.stop_check(reply, [brief]) == ""


def test_reply_gate_needs_a_real_quote(brief, monkeypatch):
    # A break the judge cannot quote from the reply is not a break (a model that invents a quote stops nothing).
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "_run", lambda *a, **k: '{"breaks": [{"line": 1, "quote": "we will measure the gap again tomorrow"}]}')
    assert owner_brief.stop_check(GOOD, [brief]) == ""


def test_open_lines_never_gate(brief, monkeypatch):
    seen = {}
    monkeypatch.setattr(judge, "available", lambda: True)

    def fake(prompt, **k):
        seen["p"] = prompt
        return '{"breaks": []}'
    monkeypatch.setattr(judge, "_run", fake)
    owner_brief.stop_check(GOOD, [brief])
    numbered = seen["p"].split("LINES:", 1)[1]
    # OPEN is context (the approved thread), never a numbered line that can be "broken".
    assert "OPEN [03/11]" not in numbered and "RULE [02/11]" in numbered
    assert "OPEN [03/11]" in seen["p"].split("REPLY:", 1)[0]


def test_shouting_is_not_a_name():
    import quick_hook
    quick_hook._stub_fastmcp()
    import quickmap
    sid = f"test_shout_{int(time.time())}"
    call = {"session_id": sid, "prompt": "brother cheka el journal bien ayer ya te dije, YA TE DIJE QUE ESTAMOS DANDO VUELTAS"}
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    os.environ["JOURNAL_JUDGE"] = os.environ.get("JOURNAL_JUDGE", "")
    with redirect_stdout(buf):
        quickmap.quick_hook(call, prompt=True)
    out = buf.getvalue()
    for w in ("dije", "dando", "vueltas"):
        assert f'QUICK MAP for "{w}"' not in out




