"""Exists probe: when a message asks whether something exists ("do we have", "is there", "did we build", "tenemos",
"hay", "hicimos"), show what the journals record as SHIPPED, BUILT or APPROVED about it, before anyone answers "no".

Why (2026-11-13 real miss): the owner asked "do we have a specific mail journal in Shopsite?"; the session searched file
names, answered "no", while SHOPSITE_FULL_JOURNAL had the owner's approved list (2026-11-10 [owner-order] item 2 "CRM,
email list and newsletter") and REVIEW_JOURNAL had it passing its test. The prompt map only mapped "journal", and
only [ship] entries counted as "exists". This is one local full-text query (no AI call, no meaning service, works for
buyers without a GPU box), and it runs only on messages that ask whether something exists.
"""
import os
import re
from pathlib import Path

import quickmap as Q

EXIST_Q = re.compile(
    r"\b(?:tenemos|tienen|hay|existe|existen|hicimos|armamos|construimos|escribimos|teniamos|tenias|"
    r"do we have|is there|are there|did we (?:make|build|write|do|ship)|have we (?:got|built|made|written|shipped)|"
    r"do you have|we already have|faltan? (?:construir|hacer|armar|terminar)|esta (?:hecho|construido|armado|listo)|"
    r"is it (?:built|done|ready|live)|is .{1,40} (?:built|done|live) yet)\b", re.I)
_TAG = re.compile(r"^\s*\[([a-z][a-z -]*)\]", re.I)
_APPROVE_TAGS = {"owner-order", "decision", "owner", "plan"}
_BUILD_TAGS = {"build", "built", "feature", "release", "capability", "tool", "results", "result", "work", "new"}
_APPROVE_WORDS = re.compile(r"\b(?:APPROVED|ADDED|THE LIST|NEW SOLD|GO|YES)\b")
_BUILD_WORDS = re.compile(r"\b(?:PASS|PASSES|PASSED|READY|BUILT|WRITTEN|DONE|WORKING|LIVE|ON SALE|DELIVERED)\b")
_NOT = re.compile(r"\bnot (?:yet )?(?:built|ready|written|approved|live|done)\b", re.I)


def kind_of(heading: str) -> str:
    """SHIPPED / BUILT / APPROVED for an entry heading that records a thing as existing, else ''."""
    h = Q._HEAD_DATE.sub("", heading or "").strip()
    if Q._is_ship_heading(heading):
        return "SHIPPED"
    if _NOT.search(h):
        return ""
    m = _TAG.match(h)
    tag = (m.group(1).strip().lower() if m else "")
    if tag in _APPROVE_TAGS and _APPROVE_WORDS.search(h):
        return "APPROVED"
    if tag in _BUILD_TAGS and _BUILD_WORDS.search(h):
        return "BUILT"
    return ""


# filler of a question, not its topic ("any specific", "some kind of")
_FILLER = {"algun", "alguna", "algunos", "algo", "especifico", "especifica", "tipo", "cosa", "cosas", "specific", "some",
           "kind", "any", "thing", "things", "already", "todavia", "still", "bien", "really", "exactly",
           # the verbs of the question itself ("falta construir X", "did we build X"): X is the topic
           "falta", "faltan", "construir", "hacer", "armar", "terminar", "build", "built", "make", "made", "write",
           "written", "done", "ready", "hecho", "construido", "armado", "listo", "mande", "mandaste", "miralo",
           # everyday Spanish of an angry or quick question; as topics they matched any entry written in Spanish
           # (2026-11-16 miss: "no tenemos ya una version imprimible ... un link directo ... en su libreria" was
           # answered with entries that shared "pero", "esta", "esto", "antes", "puedes", "directo")
           "pero", "esta", "esto", "este", "estos", "estas", "eso", "esa", "ese", "antes", "despues", "puedes", "puede",
           "podes", "podemos", "directo", "directa", "donde", "man", "bro", "loco", "decirle", "decile", "decime",
           "habiamos", "habia", "tenemos", "tenia", "aca", "ahi", "aqui", "ahora", "tambien", "porque", "cuando"}


# Spanish everyday words whose English form the journals use (translations, same role as quickmap._ES_EN)
_ES_EXTRA = {"mail": {"email"}, "mails": {"email"}, "embudo": {"funnel"}, "embudos": {"funnel"},
             "pagina": {"page"}, "paginas": {"page"}, "anuncio": {"ad"}, "anuncios": {"ads"},
             "imprimible": {"print", "printable"}, "imprimibles": {"print", "printable"}, "imprimir": {"print"},
             "impresion": {"print"}, "libreria": {"library"}, "biblioteca": {"library"}, "catalogo": {"catalog"},
             "guia": {"guide"}, "guias": {"guide"}, "descarga": {"download"}, "descargas": {"download"},
             "boton": {"button"}, "compra": {"purchase"}, "compras": {"purchase"}, "pago": {"payment"},
             "pagos": {"payment"}, "tienda": {"store", "shop"}, "cuenta": {"account"}, "correo": {"email"}}


def _ideas(message: str) -> list[dict]:
    """Each content word is one idea: the word, its Spanish-English translation and its singular. Narrow on purpose:
    the map's synonym clusters ("mails" -> drip, dogfood, auto reply...) flood a full-text search with noise."""
    seen, out = set(), []
    for tok in Q._tokens(message):
        w = tok.lower().strip("_.-")
        if len(w) < 3 or w in Q._STOP or w in _FILLER or w.isdigit() or EXIST_Q.fullmatch(w) or w in seen:
            continue
        seen.add(w)
        phr = {w, w[:-1] if len(w) > 4 and w.endswith("s") else w}
        if w in Q._ES_EN:
            phr.add(Q._fold(Q._ES_EN[w]))
        phr |= _ES_EXTRA.get(w, set())
        out.append({"label": w, "phr": {p for p in phr if re.fullmatch(r"[a-z0-9]{3,}", p)}})
    return out


# A long message (a pasted brief, a spoken dump of several ideas) asks its question in one or two sentences; the rest
# is context. Every word of it taken as the topic built one full-text query with a clause per PAIR of words
# (2026-11-20: a 3,800 character brief spent 93 s here, the prompt map was cut at its 30 s limit and the session got no
# map at all for that message). Past MAX_IDEAS only the sentences that ask are read.
MAX_IDEAS = 12


def _question_ideas(message: str) -> list[dict]:
    """_ideas(message) for a short message; for a long one, the ideas of the sentences that hold the question (a
    window around it when the text has no stops), at most MAX_IDEAS."""
    ideas = _ideas(message)
    if len(ideas) <= MAX_IDEAS:
        return ideas
    text = message or ""
    parts, first = [], None
    for m in list(EXIST_Q.finditer(text))[:3]:
        a = max(text.rfind(ch, 0, m.start()) for ch in ".!?\n") + 1
        ends = [i for i in (text.find(ch, m.end()) for ch in ".!?\n") if i != -1]
        b = min(ends) + 1 if ends else len(text)
        if b - a > 400:
            a, b = max(a, m.start() - 150), min(b, m.end() + 250)
        first = a if first is None else first
        parts.append(text[a:b])
    if not parts:  # a forced claim with no question word: its first ideas
        return ideas[:MAX_IDEAS]
    seen, out = set(), []
    for g in (g for p in parts for g in _ideas(p)):
        if g["label"] not in seen:
            seen.add(g["label"])
            out.append(g)
    if len(out) < 2 and first:  # "I want the guide in white. Do we have that already?": the thing is one sentence back
        prev = text[max(0, first - 300):first]
        for g in _ideas(prev)[-6:]:
            if g["label"] not in seen:
                seen.add(g["label"])
                out.append(g)
    return out[:MAX_IDEAS]


def _covers(sentence: str, groups: list) -> set:
    s = Q._fold(sentence)
    # inside a compound too ("mail" in "email", "journal" in "journals"); short words only as whole words
    return {g["label"] for g in groups
            if any((p in s) if len(p) >= 4 else re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", s)
                   for p in g["phr"])}


def probe(message: str, cap: int = 3, force: bool = False) -> list[dict]:
    """Entries that record as existing the thing the message asks about. [] when the message does not ask that
    (force=True: the text is a claim of the reply, always searched)."""
    if not force and not EXIST_Q.search(message or ""):
        return []
    ideas = _question_ideas(message)
    c = Q._conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
    except Exception:
        c.close()
        return []
    # A word that names a project's journal ("shopsite", "boltlab") says WHERE to look, not WHAT: it scopes the search
    # and ranks that project's journals first, but never counts as the topic (2026-11-13: "a mail journal in Shopsite"
    # ranked a Reddit account entry first because it named Shopsite and email).
    # the project is the first word of a journal's name (SHOPSITE_FULL_JOURNAL -> shopsite); "journal" itself and words
    # inside a name ("mails" of MAILS_TEAM_JOURNAL is a role journal, the topic) never scope
    heads = {re.split(r"[_\s-]+", Q._fold(Path(p).stem))[0] for p in names}
    heads -= {"journal", "mails", "mail", "ai", "the", "run", "build", "make", "sell", "ship"}
    scope = [g["label"] for g in ideas if len(g["label"]) >= 4 and g["label"] in heads]
    groups = [g for g in ideas if g["label"] not in scope] or ideas
    mod_q = bool(re.search(r"\b(?:mod|journals? dna|quick map|journal tool|hook)\b", message or "", re.I))
    phr = sorted({p for g in groups for p in g["phr"]})
    if not phr:
        c.close()
        return []
    need = 2 if len(groups) >= 2 else 1
    try:
        # prefix queries so "mail" also reaches "mails"; compounds ("email") are checked below on the text itself
        ors = ["(" + " OR ".join(f'"{p}"*' for p in sorted(g["phr"])) + ")" for g in groups]
        expr = " OR ".join(f"({a} AND {b})" for i, a in enumerate(ors) for b in ors[i + 1:]) if need == 2 else ors[0]
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 6000",
                         (expr,)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    out = []
    for path, line, heading, body in rows:
        if re.search(r"\.bak|_WORKLOG_|ARCHIVE", path, re.I):
            continue
        # the mod's own journal retells every miss of every project: only for questions about the mod itself
        if not mod_q and re.search(r"JOURNAL_TOOL_JOURNAL", path, re.I):
            continue
        m = Q._HEAD_DATE.match(heading or "")
        if not m:
            continue
        kind = kind_of(heading)
        if not kind:
            continue
        # The entry must be ABOUT it: the ideas in its title, or together in one sentence of it (a long entry that
        # names each word somewhere is not about the thing, 2026-11-13 first test).
        in_head = _covers(heading, groups)
        best = set()
        for s in re.split(r"(?<=[.!?;:])\s+|\n+", body or ""):
            got = _covers(s, groups) | in_head
            if len(got) > len(best):
                best = got
        if len(best) < need:
            continue
        out.append({"kind": kind, "when": m.group(1) + " " + (m.group(2) or "00:00"), "line": int(line),
                    "journal": names.get(path, path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]),
                    "entry": Q._HEAD_DATE.sub("", heading).strip()[:140], "hit": sorted(best),
                    "score": (len(best), any(Q._fold(Path(path).stem).startswith(s) for s in scope),
                              len(in_head)), "n": len(groups)})
    out.sort(key=lambda x: (x["score"], x["when"]), reverse=True)
    seen, res = set(), []
    for x in out:
        k = (x["journal"], x["entry"][:60])
        if k not in seen:
            seen.add(k)
            res.append(x)
        if len(res) >= cap:
            break
    return res


def cards(message: str, cap: int = 2, force: bool = False) -> list[dict]:
    """"Already exists" cards whose job covers two of the message's ideas (they ARE the record that a thing exists)."""
    if not force and not EXIST_Q.search(message or ""):
        return []
    labels = [g["label"] for g in _question_ideas(message)]
    if not labels:
        return []
    try:
        import server
        return server._match_capabilities(" ".join(labels), limit=cap, min_cover=min(2, len(labels)))
    except Exception:
        return []


def block(message: str) -> str:
    """The prompt-map block, or '' when the message does not ask whether something exists or nothing was found."""
    try:
        hits = probe(message)
        cs = cards(message)
    except Exception:
        return ""
    if not hits and not cs:
        return ""
    lines = [f"- EXISTS (card, {c.get('journal', '?')}): {str(c.get('what', ''))[:150]} | how: {str(c.get('how', ''))[:120]}"
             for c in cs]
    lines += [f"- {h['kind']} {h['when']} ({h['journal']}:{h['line']}): {h['entry']} [matches: {', '.join(h['hit'])}]"
              for h in hits]
    return ("EXISTS? THE MESSAGE ASKS WHETHER SOMETHING EXISTS. Before answering no, open these (the journals record "
            "them as shipped, built or approved):\n" + "\n".join(lines))


# ── The same probe on the finished reply (owner 2026-11-13: "I see the bad answer and swear at you before you can
# correct it"; "it must not slow anything"). A reply line that says a thing does not exist, or proposes to create one,
# is searched like a question; a strong hit (the thing in the title of a shipped, built or approved entry, every idea
# covered) adds ONE correction line right after the reply. Lines with neither pattern cost nothing (one regex).
# Only a THING is checked: the negation or the offer to create must be followed by an article and a noun ("no hay UN
# journal de mails", "que arme UN journal", "we don't have A tool"); "no hay nada ganando", "no hay errores" and
# "el control de no existe" are not claims about an artifact (first live test, 2026-11-13: 3 false stops of 6).
_ART = r"(?:un|una|ningun|ninguna|el|la|los|las|a|an|any|the)\s+"
_OBJ = r"((?:[a-z0-9][\w-]*\s*){1,8})"
# modifiers of the object, never the thing itself ("un solo caso", "una venta nueva", "el ultimo aviso", "dedicado")
_MODIFIERS = {"solo", "sola", "unico", "unica", "dedicado", "dedicada", "nuevo", "nueva", "nuevos", "nuevas", "ultimo",
              "ultima", "caso", "casos", "desde", "hoy", "ayer", "manana", "otro", "otra", "mismo", "misma", "real",
              "propio", "propia", "simple", "completo", "completa", "general", "single", "only", "new", "own", "same",
              "other", "whole", "full"}
NEG = re.compile(
    r"\b(?:no (?:hay|tenemos|existe|existen)|todavia no (?:hay|existe|tenemos)|nunca (?:se )?(?:hizo|armo|construyo)|"
    r"we (?:don'?t|do not) have|there (?:is|are) no|we never built)\s+" + _ART + _OBJ, re.I)
CREATE = re.compile(
    r"\b(?:armo|arme|armemos|hago|hagamos|creo|creemos|construyo|construyamos|escribo|escribamos)\s+(?:un|una)\s+" + _OBJ +
    r"|\b(?:i'?ll|let me|shall i|should i|want me to)\s+(?:build|create|write|make)\s+(?:a|an)\s+(?:new\s+)?" + _OBJ, re.I)
_QUOTED = re.compile(r'["“«][^"”»\n]{0,120}["”»]')


def reply_claims(reply: str, cap: int = 2) -> list[tuple[str, str]]:
    """(the reply line, the thing it says is missing or offers to create)."""
    out = []
    for line in re.split(r"(?<=[.!?])\s+|\n+", reply or ""):
        s = _QUOTED.sub(" ", line).strip()
        f = Q._fold(s)
        m = NEG.search(f) or CREATE.search(f)
        if len(s) < 15 or not m:
            continue
        obj = next(g for g in m.groups() if g)
        out.append((s[:300], obj.strip()))
        if len(out) >= cap:
            break
    return out


def reply_check(reply: str) -> str:
    """'' when the reply claims nothing missing; else the correction request (one short line per wrong claim)."""
    if os.environ.get("JOURNAL_EXISTS_PROBE", "on") == "off":
        return ""
    bad = []
    for s, obj in reply_claims(reply):
        try:
            obj = " ".join(w for w in obj.split() if Q._fold(w) not in _MODIFIERS)
            ideas = [g for g in _ideas(obj) if g["label"] not in _MODIFIERS]
            if len(ideas) < 2:
                continue   # one word ("no hay un problema") is too thin to say the reply is wrong
            # strong only: EVERY idea of the thing covered, at least one of them in the entry's title
            hits = [h for h in probe(obj, cap=6, force=True)
                    if h["score"][2] >= 1 and h["score"][0] >= max(2, h["n"] - (1 if h["n"] >= 4 else 0))][:2]
            cs = [] if hits else [c for c in cards(obj, cap=3, force=True)
                                  if len(_covers(f"{c.get('what', '')} {c.get('keys', '')}", ideas)) >= len(ideas) - 1][:1]
        except Exception:
            continue
        if not hits and not cs:
            continue
        rec = [f"{h['kind']} {h['when']} ({h['journal']}:{h['line']}): {h['entry'][:120]}" for h in hits]
        rec += [f"EXISTS (card, {c.get('journal', '?')}): {str(c.get('what', ''))[:140]}" for c in cs]
        bad.append(f'- your line: "{s[:200]}"\n  the journals record: ' + " | ".join(rec))
    if not bad:
        return ""
    return ("EXISTS CHECK (no AI) OF THE REPLY YOU JUST GAVE: it says something does not exist or proposes to create "
            "it, and the journals record it:\n" + "\n".join(bad))
