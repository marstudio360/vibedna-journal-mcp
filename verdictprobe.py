"""Verdict probe: an idea the journals record as withdrawn, rejected or ruled out is not proposed again as new.

Why (2026-11-14 real miss, third of its kind after 2026-11-07 and 2026-11-09): a session proposed, built and previewed
an "Open in your browser to pay" button for Facebook-app visitors. TONE_GARDEN_JOURNAL 2026-11-05 19:17 already said
'the "open in Safari" idea is NOT backed by our data and is withdrawn', as the last sentence of a bullet inside an entry
titled "PAYPAL IN FB/IG MEASURED". No Decided card was ever written, so nothing showed it while the payment was being
changed; the entry was listed once by its title (third, by meaning) and the session did not open it.

Two cheap pieces, no AI call, no meaning service (buyers without a GPU box get both):
1. write_hint(): journal_append tells the writer, in its result, that the entry withdraws or rejects an idea and that
   only a Decided card puts it in front of the next session.
2. reply_check(): a finished reply that PROPOSES something gets its proposal lines compared with the journals'
   sentences that rule out an idea (one local full-text query per line). A match is a NOTE given with the owner's
   next message, never a stop: measured on 2,355 real replies (549 with a proposal) of 30 sessions, with the project
   scope it fires 10 times, 1 of them the real miss. A wrong note costs a few words; a wrong stop costs a turn.
"""
import os
import re
from pathlib import Path

import quickmap as Q
import existsprobe as E

# the word that withdraws an idea, in a journal sentence
VERDICT = re.compile(r"(?<![\w-])(withdrawn|owner-rejected|ruled out|discarded|scrapped|not backed|rejected|"
                     r"descartad[oa]s?|rechazad[oa]s?)(?![\w-])", re.I)
_FTS_VERDICT = ('(withdrawn OR "owner-rejected" OR "ruled out" OR discarded OR scrapped OR "not backed" OR rejected OR '
                'descartado OR descartada OR descartados OR descartadas OR rechazado OR rechazada OR rechazados OR '
                'rechazadas)')
# "rejected" about a machine answer or a payment, never about an idea
_MACHINE = re.compile(r"\b(?:http|api|request|requests|card|cards|tarjeta|tarjetas|payment|pago|login|token|upload|"
                      r"tx|transaction|bid|puja|order|orden|signature|firma|captcha|sim|simulation)\b[^.]{0,40}"
                      r"\b(?:rejected|rechazad[oa]s?)\b|\b(?:rejected|rechazad[oa]s?)\b[^.]{0,25}\b(?:by|por)\s+"
                      r"(?:the\s+|el\s+|la\s+)?(?:api|server|servidor|bank|banco|stripe|paypal|meta|google|tiktok)\b", re.I)

# ── 1. at write time ────────────────────────────────────────────────────────────────────────────────────────────────
_IDEA_VERDICT = re.compile(
    r"\b(?:idea|plan|approach|option|proposal|hypothesis|path|route|variant|version|design|propuesta|opcion|"
    r"hipotesis|camino|variante)\b[^.\n]{0,160}?(?<![\w-])(?:withdrawn|owner-rejected|ruled out|discarded|scrapped|"
    r"not backed|rejected|descartad[oa]s?|rechazad[oa]s?)(?![\w-])"
    r"|(?<![\w-])(?:is|are|was|were|stays?|queda|quedo|fue)\s+(?:now\s+)?(?:withdrawn|ruled out|discarded|scrapped|"
    r"owner-rejected|descartad[oa]s?)(?![\w-])"
    r"|\bowner[- ]rejected\b|\b(?:the )?owner (?:rejected|ruled out)\b|\bel dueno (?:rechazo|descarto)\b", re.I)


def write_hint(entry: str, tag: str = "") -> str:
    """'' or the note for journal_append's result when the entry withdraws, rejects or rules out an idea."""
    # a [mod-miss] entry retells someone else's verdict (first live append, 2026-11-14: the hint fired on the entry
    # that reports this very miss)
    if os.environ.get("JOURNAL_VERDICT_PROBE", "on") == "off" or not entry or (tag or "").strip().lower() == "mod-miss":
        return ""
    for s in re.split(r"(?<=[.!?])\s+|\n+", entry):
        # a long quote is someone else's sentence being retold (a report, a rule about verdicts), not this entry's verdict
        f = Q._fold(re.sub(r"'[^'\n]{20,}'|\"[^\"\n]{20,}\"", " ", s))
        if len(f) < 25 or _MACHINE.search(f):
            continue
        if _IDEA_VERDICT.search(f):
            return ("This entry withdraws, rejects or rules out an idea: \"" + s.strip()[:220] + "\". A verdict left as a "
                    "sentence inside an entry is NOT shown to the next session that touches the same thing (real miss "
                    "2026-11-14: a withdrawn idea was proposed, built and previewed again). If it is a standing verdict, "
                    "add it now as a Decided card so every session sees it first: journal_decision_add(journal, "
                    "decision=\"Do not <the idea>: <why>, <date>\", aliases=\"<every other word for it, any language>\", "
                    "see=\"<this entry>\"). If it only corrects a number or a one-off, ignore this note.")
    return ""


# ── 2. on the finished reply ────────────────────────────────────────────────────────────────────────────────────────
PROPOSE = re.compile(
    r"\b(?:propongo|propuesta|recomiendo|recomendacion|cambiaria|haria|agregaria|pondria|sumaria|sacaria|moveria|"
    r"probaria|conviene|deberiamos|podriamos|siguiente (?:paso|movida)|proxim[oa] (?:paso|movida)|i propose|"
    r"i recommend|i would|i'd|we should|we could|let'?s|next (?:step|move|test)|want me to|should i|shall i)\b"
    r"|¿\s*(?:lo\s+|la\s+|los\s+|las\s+|te\s+(?:lo\s+|la\s+)?)?(?:hago|armo|avanzo|arranco|publico|preparo|"
    r"construyo|sumo|agrego|pruebo)\b", re.I)
_LIST = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S")
# the reply already knows the verdict, or reports something it took out
_KNOWS = re.compile(r"\b(?:descart\w+|retir\w+|rechaz\w+|withdrawn|rejected|ruled out|discarded|dropped|removed|"
                    r"taken out|saque|quite|sin publicar|no (?:lo |la |los |las )?(?:publique|hice|voy a|va)|"
                    r"not (?:shipped|published|live)|ya se habia|already (?:tried|ruled))\b", re.I)
# everyday Spanish product words whose English form the journals use (same role as existsprobe._ES_EXTRA)
_ES = {"abrir": "open", "abri": "open", "abre": "open", "tarjeta": "card", "boton": "button", "pantalla": "screen",
       "formulario": "form", "aviso": "notice", "cartel": "notice", "comprador": "buyer", "compradores": "buyer",
       "descuento": "discount", "anuncio": "ad", "anuncios": "ads", "correo": "email", "mail": "email",
       "mails": "email", "pagina": "page", "paginas": "page", "navegador": "browser", "pago": "pay",
       "pagos": "pay", "precio": "price", "precios": "price", "oferta": "offer", "regalo": "gift", "gratis": "free",
       "suscripcion": "subscription", "mensual": "monthly", "anual": "yearly", "prueba": "trial", "carrito": "cart",
       "ventana": "window", "embudo": "funnel", "encuesta": "survey", "cupon": "coupon", "contador": "countdown",
       "reloj": "timer", "testimonio": "testimonial", "testimonios": "testimonial", "resena": "review",
       "resenas": "review", "titulo": "headline", "imagen": "image", "musica": "music", "voz": "voice",
       "subtitulos": "captions", "portada": "cover", "miniatura": "thumbnail", "horario": "schedule",
       "seguidores": "followers", "comentarios": "comments", "mensajes": "messages", "bucle": "loop"}
# words of the proposal's grammar, never its topic
_GRAMMAR = {"quien", "entra", "desde", "mas", "arriba", "abajo", "primera", "primero", "todo", "todos", "todas",
            "cada", "cambios", "cambio", "tres", "dos", "antes", "despues", "luego", "ahora", "vista", "previa",
            "solo", "sola", "vez", "seria", "puede", "pueden", "cuando", "donde", "dentro", "fuera", "hacer", "poner",
            "would", "should", "could", "first", "then", "above", "below", "inside", "every", "each", "also", "make",
            "change", "changes", "show", "add", "move", "before", "after", "want", "need"}


def proposal_lines(reply: str, cap: int = 8) -> list[str]:
    """The lines where the reply proposes something: a line with a proposal word and the lines under it until a blank
    line ("What I would change:" and its list). Findings, tables and the rest of the reply are never read: a long
    diagnostic bullet shares everyday words with any journal (first run, 2026-11-14: "the server answered wrong" was
    matched to a discarded install method of another project)."""
    lines = (reply or "").splitlines()
    folded = [Q._fold(ln) for ln in lines]
    out, take = [], False
    for ln, f in zip(lines, folded):
        if PROPOSE.search(f):
            take = True
        elif not ln.strip():
            take = False
        if take and len(ln.strip()) >= 40 and not _KNOWS.search(f) and not ln.lstrip().startswith("|"):
            out.append(ln.strip())
    seen, res = set(), []
    for ln in out:
        if ln not in seen:
            seen.add(ln)
            res.append(ln)
    return res[:cap]


def _ideas(line: str) -> list[dict]:
    out = []
    for g in E._ideas(E._QUOTED.sub(lambda m: " " + m.group(0)[1:-1] + " ", line)):
        w = g["label"]
        if w in _GRAMMAR or w in E._MODIFIERS:
            continue
        if w in _ES:
            g["phr"].add(_ES[w])
        out.append(g)
    return out


def verdicts_for(line: str, folders: set | None = None, cap: int = 2, before: str = "") -> list[dict]:
    """Journal sentences that withdraw, reject or rule out what the line proposes. Strong matches only: the verdict
    sentence itself shares two ideas with the line and its journal line (one bullet) shares five, or the sentence
    alone shares four. With the session's project folders known, only their journals count (everyday words such as
    server, payment, form and buyer sit next to "discarded" in every project)."""
    ideas = _ideas(line)
    if len(ideas) < 4:
        return []
    # A line that names a product, a project or a company is only about a verdict that names one of them too (in the
    # journal's name, the entry title or the line itself). 2026-11-20: a plans page sentence that named one product
    # was matched to a content calendar line of another brand on "day, free, loads, page, ships". Measured on the 18
    # notes logged until then: 7 dropped, all wrong ones; the real case names no product and is kept.
    try:
        named = {Q._fold(e["name"]) for e in Q._entities_in(line) if len(e.get("name") or "") >= 4}
    except Exception:
        named = set()
    ors = ["(" + " OR ".join(f'"{p}"*' for p in sorted(g["phr"])) + ")" for g in ideas[:14]]
    pairs = " OR ".join(f"({a} AND {b})" for i, a in enumerate(ors) for b in ors[i + 1:])
    c = Q._conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 800",
                         (f"{_FTS_VERDICT} AND ({pairs})",)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    out = []
    for path, line0, heading, body in rows:
        # copies, archives, raw owner speech and the mod's own journal (it retells every miss) are not verdicts
        if re.search(r"\.bak|_WORKLOG_|ARCHIVE|JOURNAL_TOOL_JOURNAL|OWNER_VOICE|journals-drafts", path, re.I):
            continue
        m = Q._HEAD_DATE.match(heading or "")
        if not m or (before and m.group(1) >= before):   # before: replay a past miss as the journals stood then
            continue
        inside = bool(folders) and Q._fold(str(Path(path).parent)) in folders
        if folders and not inside:
            continue
        about = Q._fold(names.get(path, "").replace("_", " ") + " " + (heading or ""))
        for jl in (body or "").split("\n"):
            if not VERDICT.search(jl):
                continue
            line_cov = E._covers(jl, ideas)
            if len(line_cov) < 4:
                continue
            if named and not any(n in about or n in Q._fold(jl) for n in named):
                continue
            for s in re.split(r"(?<=[.!?])\s+", jl):
                fs = Q._fold(s)
                # Only a sentence that rules out an IDEA ("the X idea is withdrawn", "owner-rejected", "queda
                # descartado"). Any sentence with "rejected" or "descartado" in it stopped 119 of 549 real proposals
                # in the first sweep (2026-11-14), nearly all about a rejected clip or a discarded file.
                if not _IDEA_VERDICT.search(fs) or _MACHINE.search(fs):
                    continue
                sent_cov = E._covers(s, ideas)
                if (len(sent_cov) >= 2 and len(line_cov) >= 5) or len(sent_cov) >= 4:
                    out.append({"when": m.group(1) + " " + (m.group(2) or "00:00"), "line": int(line0),
                                "journal": names.get(path, path.replace("\\", "/").rsplit("/", 1)[-1]),
                                "sentence": s.strip()[:260], "hit": sorted(line_cov),
                                "score": (inside, len(sent_cov), len(line_cov))})
    out.sort(key=lambda x: (x["score"], x["when"]), reverse=True)
    seen, res = set(), []
    for x in out:
        k = x["sentence"][:80]
        if k not in seen:
            seen.add(k)
            res.append(x)
        if len(res) >= cap:
            break
    return res


def reply_hits(reply: str, folders: set | None = None, before: str = "") -> list[dict]:
    """The proposal lines of the reply that the journals ruled out, at most two: [{"line", "hits"}]."""
    # No project scope (the session read no journal): silent. Unscoped it fired 26 times on the same 2,355 replies
    # and missed the real case; a session that works on a project has read its journal by the time it proposes.
    if os.environ.get("JOURNAL_VERDICT_PROBE", "on") == "off" or not folders:
        return []
    bad = []
    for ln in proposal_lines(reply):
        try:
            hits = verdicts_for(ln, folders, before=before)
        except Exception:
            continue
        if hits:
            bad.append({"line": ln, "hits": hits})
        if len(bad) >= 2:
            break
    return bad


def judge_item(hit: dict) -> dict:
    """One ruled-out note as a case for the alarm judge (alarmjudge.py), which reads it before it is said."""
    h = hit["hits"][0]
    return {"kind": "ruled_out", "reply": hit["line"][:600], "hit": hit,
            "alarm": "The reply proposes something the journals record as withdrawn, rejected or ruled out.",
            "entry": f"{h['journal']} ({h['when']}) says: {h['sentence']}"}


def render(bad: list[dict]) -> str:
    """'' for no hits; else the correction request."""
    if not bad:
        return ""
    rows = []
    for b in bad:
        rec = " | ".join(f"{h['when']} ({h['journal']}:{h['line']}): \"{h['sentence']}\"" for h in b["hits"])
        rows.append(f'- your line: "{b["line"][:200]}"\n  the journals record: {rec}')
    return ("RULED OUT BEFORE (no AI check of your last reply): it proposed something the journals record as withdrawn, "
            "rejected or ruled out:\n" + "\n".join(rows) + "\nOpen that entry BEFORE you build or defend the proposal. "
            "If it is the same thing, tell the owner first, in one or two lines, when and why it was ruled out, and "
            "build it only if something new reopens it. If it is about something else, ignore this note.")


def reply_check(reply: str, folders: set | None = None, before: str = "") -> str:
    """'' when the reply proposes nothing the journals ruled out; else the correction request."""
    return render(reply_hits(reply, folders, before))
