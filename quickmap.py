"""Quick map: one word, file or topic in, everything that matters about it out, in a few lines.

Separate from server.py on purpose (2026-10-24): it only uses the server's index helpers, so it runs next to
any copy of the journal server (the PC copy and the one the companies improve on the box) without either
copy having to carry it. Used by quick_hook.py (the journals mod) and by server.py's journal_quick tool.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from quick_hook import gate as _gate
from server import (_SEC_DECIDED, _STOP, _conn, _expand_terms, _find_section, _fold, _fts_or,
                    _index_refresh_internal, _match_capabilities, _sync_changed)


# ─── Quick map: one word, file or topic in, everything that matters about it out, in a few lines ──
# Built 2026-10-24 after a session edited a shared worker that a role manual owned: the before-build
# cards showed unrelated things and the edit gate only knew folders, so nobody read what was already done.
# There are no owners (one brain, anyone takes any piece): a "## Brain map" table in any journal says, per piece,
# which journal to read first and who is working on it now. Rows are written, never guessed (a guess picked the
# wrong journal in tests). No AI, only the FTS index: fast enough for a hook.
_GENERIC_STEMS = set("""server main index app utils util helpers helper lib core config settings common test tests
tool tools script scripts run runner worker cli api mod mods module handler handlers hooks hook data file files new old
copy backup bak tmp temp src dist build page pages component components readme install plugin plugins package
manifest register types type index style styles test spec license changelog docs doc map maps rename fix fixes
update split patch probe check sim box_install box_update desk desks employees employee""".split())
# Role names that come from startup messages ("You are DIRECTOR of X", manuals): Memory Team 2026-10-24 measured the map
# followed 1/14 (director), 2/15 (quality), 2/13 (auditor). Silent as bare words unless the Brain map names them.
_ROLE_WORDS = set("""director quality auditor copywriter manager desk desks employees employee builder supervisor memory
numbers research customers tester feedback""".split())
_HEAD_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?")


def _file_token(text: str) -> str:
    """The file a command line names: the first token with a path, else the first with an extension. A whole
    path with spaces ("C:/Users/Ann Lee/x/quickmap.py") is one file, not a command: split, every edit
    under that folder mapped "ann" (2026-10-26)."""
    whole = str(text or "").strip().strip("\"'")
    if re.match(r"^(?:[A-Za-z]:[\\/]|[\\/~])", whole) and re.search(r"\.\w{1,5}$", whole) \
            and not re.search(r"\s-{1,2}\w|[&|;<>]", whole):
        return whole
    toks = [x.strip().rstrip(".,;:!?)\"'") for x in str(text or "").split()]
    return (next((x for x in toks if re.search(r"[\\/]", x)), "") or
            next((x for x in toks if re.search(r"\.\w{1,5}$", x)), ""))


def _quick_terms(text: str) -> list[str]:
    """The specific words of a query or a file path: file stems split on _ and -, generic names dropped."""
    t = str(text or "").strip().rstrip(".,;:!?)\"'")  # "brake.py." from a sentence end is "brake.py"
    f = _file_token(t)
    if f and len(t.split()) > 1:  # a command line: the script it runs, not its arguments
        t = f
    if re.search(r"[\\/]|\.\w{1,5}$", t):
        t = Path(t.replace("\\", "/")).stem
        # ".astro" or "*.astro" is a file type, never a name: it mapped the ASTRO project (2026-10-27)
        t = re.sub(r"^[*.]*\.\w{1,6}$", "", t)
    out = []
    for w in re.split(r"[^A-Za-zÀ-ÿ0-9]+", t):
        f = _fold(w)
        if len(f) >= 3 and f not in _STOP and f not in _GENERIC_STEMS and not f.isdigit() and f not in out:
            out.append(f)
    return out[:4]


def _map_rows(query: str, terms: list[str]) -> list[dict]:
    """Rows of any journal's '## Brain map' table (| Piece | Keys | Working on it now | Read first | Notes |)
    whose keys match the query or its file name. The older heading 'Brain map' is read too."""
    c = _conn()
    try:
        paths = [r[0] for r in c.execute("SELECT DISTINCT path FROM entries_fts WHERE entries_fts MATCH ?",
                                         ('heading : (("memory" OR "brain" OR "owners") AND "map")',)).fetchall()]
    except Exception:
        paths = []
    finally:
        c.close()
    q = _fold(query.replace("\\", "/"))
    stem = _fold(Path(query.replace("\\", "/")).name) if re.search(r"[\\/]|\.\w{1,5}$", query) else ""
    # A file extension is a type, never a piece: "index.astro" must not hit a key "astro" (2026-10-27). Keys
    # that hold a dot ("quick_hook.py") still match the whole name.
    ext = re.compile(r"(?<=[\w*-])\.[a-z][a-z0-9]{0,5}(?=$|[\s\"'/,;:)|])")
    q_bare, stem_bare = ext.sub("", q), ext.sub("", stem)
    out = []
    for p in paths:
        try:
            sec = _find_section(Path(p).read_text(encoding="utf-8", errors="replace"), ("brain map",))
        except Exception:
            sec = None
        if not sec:
            continue
        for ln in sec[1].splitlines():
            cells = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(cells) < 4 or cells[0].lower() in ("piece", "") or set(cells[0]) <= set("-: "):
                continue
            keys = [_fold(k.strip()) for k in cells[1].split(",") if k.strip()]
            # Whole words only: "appuser" must not match the typo "mbaicos" (2026-10-24).
            whole = lambda k, text: bool(text) and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text)
            hit = any((len(k) >= 3 and ((whole(k, q) or whole(k, stem)) if "." in k
                                        else (whole(k, q_bare) or whole(k, stem_bare)))) or k in terms
                      # a multi-word key needs ALL its words: "real" of real_test.py is not the "real bot" piece
                      # (2026-10-27: a Playwright check of the HQ app was stopped as the Real Oddsboard bot)
                      or (len(k.split()) > 1 and all(t in terms for t in k.split())) for k in keys)
            if hit:
                out.append({"piece": cells[0], "now": cells[2], "path": cells[3] if len(cells) > 3 else "",
                            "notes": cells[4] if len(cells) > 4 else "", "keys": keys})
    return out


def _vault_rows(terms: list[str]) -> list[dict]:
    """Vault entries whose NAME or category carries one of the words, read from a names-only index of your secrets
    vault (JOURNAL_INCLUDE_VAULT_PATH, a JSON file {"entries": [{"name", "category", "fields"}]}): names, categories
    and field names, never values. Optional: without the setting nothing is shown. 2026-10-25: a Cloudmodel key sat in the vault for months and
    a session asked the owner for a new one, because maps only looked at journals."""
    v = os.environ.get("JOURNAL_INCLUDE_VAULT_PATH", "").strip()
    if not v:
        return []   # opt-in: no vault index unless you point at one
    p = Path(v).expanduser()
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("entries", [])
    except Exception:
        return []
    terms = [t for t in terms if len(t) >= 4 and _share(t) <= 0.3]  # "live", "social": common words name no key
    out = []
    for r in rows:
        words = set(re.split(r"[^a-z0-9]+", _fold(r.get("name", ""))))  # the name only: category "social" matched 40 entries
        if any(t in words for t in terms):
            out.append(r)
    return out if len(out) <= 4 else []  # a word in many entry names ("social") names no one key: say nothing


def _vault_latest(name: str, cap: int = 2) -> list[dict]:
    """Newest dated entries, in ANY journal, that name a vault entry exactly. 2026-10-29 real case: the map showed
    the key ai-subscription-token-vpsone and the session read only the 17:30 accounts map ("runs on vpsone,
    Freelance Engine brain"); FREELANCE_ENGINE_JOURNAL_USER said at 19:02 that vpsone was shut down, naming the
    same key, and the session told the owner the account was shared with vpsone. Who uses a key and where it runs
    is the newest entry that names it, not the first map found."""
    phrase = " ".join(x for x in re.split(r"[^a-z0-9]+", _fold(name)) if x)
    if len(phrase) < 4:
        return []
    exact = re.compile(r"(?<![a-z0-9_-])" + re.escape(_fold(name)) + r"(?![a-z0-9_-])")
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 400",
                         (f'"{phrase}"',)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    out = []
    for path, line, heading, body in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m or not (exact.search(_fold(body or "")) or exact.search(_fold(heading or ""))):
            continue
        said = next((s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", body or "") if exact.search(_fold(s))), "")
        out.append({"when": m.group(1) + " " + (m.group(2) or "00:00"), "journal": names.get(path, Path(path).name),
                    "line": int(line), "entry": _HEAD_DATE.sub("", heading or "").strip()[:140],
                    "said": re.sub(r"^\s*[-*|]\s*", "", said)[:200],
                    "state": "" if _STATE_CLAIM.search(said) else _state_sentence(body, name)})
    out.sort(key=lambda x: x["when"], reverse=True)
    return out[:cap]


def _name_words(name: str) -> set:
    """Whole words of a journal's name: "box" is not STUDIO_DASHBOARD_AND_GPUBOX, "localmodel" is LOCALMODEL_JOURNAL."""
    return set(re.split(r"[^a-z0-9]+", _fold(Path(name).stem)))


def names_all(c) -> list[str]:
    return [Path(n).stem for (n,) in c.execute("SELECT name FROM journals").fetchall()]


# ─── Open plans and named things (2026-10-26) ──────────────────────────────────────────────────────────────
# Owner 2026-10-26: "the map must never depend on my exact words; it has to be smarter and solid". The plan
# "stream one AI team live on mapleworks.dev/live" lived as ONE sentence inside a long [ship] entry ("...
# mapleworks.dev/live page written, NOT deployed: owner sees a screenshot and says publish first") and in a
# Current state line, so "mapleworks" and "en vivo" brought nothing about it. Now:
# 1. Sentences that state unfinished work are mined from every dated entry and Current state when a journal is
#    indexed (plans_fts); a later entry anywhere that names the same things with LIVE / shipped / deployed /
#    done / closed / published closes one. The map shows the open ones as "OPEN PLAN" lines.
# 2. A named thing (company, Brain map key, journal, product named in a card) always brings its decisions,
#    what exists and its open plans, whatever the other words are. Each Decided card's aliases are one synonym
#    cluster, so "en vivo" also means "live", "streaming", "public office".
_PLAN_MARK = re.compile(
    r"\bnot\s+(?:yet|live|deployed|published|shipped|built|wired|started)\b|\brequested\s+from\b|\bplanned\b"
    r"|(?-i:\bTODO\b)|\bto-do\b|\b(?:left|still) to do\b|\bwait(?:s|ing)?\s+(?:for|on)\s+the\s+owner|\bneeds?\s+the\s+owner"
    r"|\bowner\s+sees\b[^.]{0,80}?\bsays\b|\bon\s+hold\b|\bheld\s+(?:back|until|for|off)\b"
    r"|(?<!\bno )\bpending\b(?!\s+(?:cards?|lines?|sections?)\b)|\bnext\s*:|\bsin\s+publicar\b|\bfaltan?\b"
    r"|\bpendientes?\b|\bplanead[oa]s?\b|\btodav[ií]a\s+no\b|\ba[uú]n\s+no\b|\bno\s+est[aá]\s+en\s+vivo\b", re.I)
# Closing words: "LIVE" in capitals is how a ship is written ("journals mod LIVE ON gpubox"); a lowercase
# "live" is usually the topic itself ("live view"), so only "is/now/went live" closes.
_PLAN_CLOSE = re.compile(r"\bLIVE\b|(?i:\b(?:is|are|now|went|goes)\s+live\b|\b(?:shipped|deployed|done|closed|published)\b)")
_PLAN_CLOSE_WORDS = {"live", "shipped", "deployed", "done", "closed", "published", "ship", "deploy", "close", "publish"}
_QUOTED = re.compile(r'"[^"\n]{0,80}"|“[^”\n]{0,80}”')   # 'the line "requested from X / NOT deployed"' talks about a plan
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(\[])|\s+·\s+|\s+\|\s+")
_STATE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T~]{1,3}(\d{2}:\d{2}))?")
_PLAN_CAP = 3
# Plain substrings one of the markers needs: the regex alone cost ~2 s on a 2 MB journal of long lines.
_PLAN_HINTS = ("not ", "request", "planned", "todo", "to-do", "to do", "wait", "need", "on hold", "held", "pending",
               "next", "publicar", "falta", "pendiente", "planead", "todav", "aun no", "aún no", "owner sees", "en vivo")


def _has_mark(s: str) -> bool:
    """_PLAN_MARK somewhere in s, checked only in a small window around each plain-text hint (fast on long lines)."""
    low = s.lower()
    for h in _PLAN_HINTS:
        i = low.find(h)
        while i >= 0:
            if _PLAN_MARK.search(s, max(0, i - 12), i + 110):
                return True
            i = low.find(h, i + 1)
    return False


def _plan_skip() -> set:
    return (_STOP | _CHAT_WORDS | _INTENT_GENERIC | _PLAN_CLOSE_WORDS | set(
        """not yet planned plan plans pending requested request held hold next todo waits wait waiting needs need sees
        says first still written sin publicar falta faltan pendiente pendientes planeado planeada todavia aun utc
        the and was were has had its into after before now then""".split()))


def _plan_words(s: str, skip: set) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", _fold(s)):
        if len(w) >= 3 and not w.isdigit() and w not in skip and w not in out:
            out.append(w)
    return out


def _trim_plan(s: str, pos: int, width: int = 220) -> str:
    s = s.strip()
    if len(s) <= width:
        return s
    start = 0 if pos < width - 60 else max(0, pos - 120)
    return ("..." if start else "") + s[start:start + width].rstrip() + "..."


def _mine_plans(text: str) -> list[tuple[int, str, str, str]]:
    """(line, date, sentence shown, words) for each sentence of a dated entry or the Current state section that
    states unfinished work. A Current state line takes the section's own date ("As of 2026-10-24"), else the
    newest entry of the journal."""
    lines = text.splitlines()
    newest = max((m.group(1) + " " + (m.group(2) or "00:00") for m in
                  (_HEAD_DATE.match(ln[3:].strip()) for ln in lines if ln.startswith("## ")) if m), default="")
    skip = _plan_skip()
    out, mode, date, fence = [], None, "", False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if ln.startswith("## "):
            title = ln[3:].strip()
            m = _HEAD_DATE.match(title)
            if m:
                mode, date = "entry", m.group(1) + " " + (m.group(2) or "00:00")
            elif any(n in title.lower() for n in ("current state", "estado actual")):
                mode, date = "state", newest
                for nxt in lines[i + 1:i + 40]:
                    if nxt.startswith("## "):
                        break
                    sm = _STATE_DATE.search(nxt)
                    if sm:
                        date = sm.group(1) + " " + (sm.group(2) or "00:00")
                        break
            else:
                mode = None
            continue
        s0 = ln.strip()
        if not mode or not s0 or s0.startswith(("#", "- [x]", "- [X]", "|---", "| ---")) \
                or not _has_mark(s0):
            continue   # the raw line is checked first: folding every line of every journal took 8 s
        for s in _SENT_SPLIT.split(s0.lstrip("-*> ").strip()):
            m = _PLAN_MARK.search(_QUOTED.sub(lambda q: " " * len(q.group(0)), s))
            if not m:
                continue
            words = _plan_words(s[:600], skip)
            if len(words) >= 2:
                # head: the sentence's first 12 words, its SUBJECT (the shown text may be cut in the middle)
                out.append((i + 1, date, _trim_plan(s, m.start()), " ".join(words), " ".join(_tokens(s)[:12])))
    return out


_PLANS_READY = {"db": None}
PLANS_VERSION = "2"   # bump when _PLAN_MARK, _mine_plans or the table change: every journal is mined again once


def _plans_schema(c):
    from server import _DB
    if _PLANS_READY["db"] == str(_DB):
        return
    c.execute("CREATE TABLE IF NOT EXISTS plans_version (v TEXT)")
    if (c.execute("SELECT v FROM plans_version").fetchone() or [""])[0] != PLANS_VERSION:
        c.execute("DROP TABLE IF EXISTS plans_fts")
        c.execute("DROP TABLE IF EXISTS plans_meta")
        c.execute("DELETE FROM plans_version")
        c.execute("INSERT INTO plans_version(v) VALUES(?)", (PLANS_VERSION,))
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts USING fts5(path UNINDEXED, line UNINDEXED, "
              "date UNINDEXED, text UNINDEXED, head UNINDEXED, words, tokenize='porter unicode61')")
    c.execute("CREATE TABLE IF NOT EXISTS plans_meta (path TEXT PRIMARY KEY, mtime REAL DEFAULT 0)")
    c.commit()
    _PLANS_READY["db"] = str(_DB)


def index_plans(c, path: str, text: str, mtime: float) -> None:
    """Replace one journal's mined plans. Called where the entry index is written (server._index_entries) and,
    for journals another server copy indexed, by _sync_plans before a map is built. Only raw journals: sold
    journals and docs have no plans of ours."""
    _plans_schema(c)
    if c.execute("SELECT 1 FROM plans_meta WHERE path = ?", (path,)).fetchone():   # path is not indexed in FTS: a
        c.execute("DELETE FROM plans_fts WHERE path = ?", (path,))                # delete scans, skip it when new
    row = c.execute("SELECT kind, name FROM journals WHERE path = ?", (path,)).fetchone()
    raw = ((row[0] or "raw") == "raw") if row else ("JOURNAL" in Path(path).name.upper())
    if raw:
        c.executemany("INSERT INTO plans_fts(path, line, date, text, words, head) VALUES(?,?,?,?,?,?)",
                      [(path, ln, d, s, w, hd) for ln, d, s, w, hd in _mine_plans(text)])
    c.execute("INSERT INTO plans_meta(path, mtime) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime",
              (path, mtime))


def _sync_plans(c, budget: float = 1.2) -> int:
    """Journals whose entries were re-read (by any server copy) since their plans were mined: mine them again.
    At most `budget` seconds per call, progress committed: the first build (~6 s for 350 journals) must not run
    inside one hook call that a timeout could kill and roll back every time."""
    _plans_schema(c)
    t0 = time.time()
    stale = c.execute("SELECT e.path, e.mtime FROM entries_meta e LEFT JOIN plans_meta p ON p.path = e.path "
                      "WHERE p.mtime IS NULL OR abs(p.mtime - e.mtime) > 1e-6").fetchall()
    gone = c.execute("SELECT path FROM plans_meta WHERE path NOT IN (SELECT path FROM entries_meta)").fetchall()
    for path, mt in stale:
        if time.time() - t0 > budget:
            break
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        index_plans(c, path, text, mt)
    for (p,) in gone:
        c.execute("DELETE FROM plans_fts WHERE path = ?", (p,))
        c.execute("DELETE FROM plans_meta WHERE path = ?", (p,))
    if stale or gone:
        c.commit()
    return len(stale) + len(gone)


def _cards_cache() -> list[dict]:
    """Decided and Already-exists cards of every raw journal, re-parsed only for journals that changed
    (~/.journal/quick_cards.json): the prompt hook cannot pay a full parse of every journal at each message."""
    from server import _SEC_EXISTS, _parse_capabilities
    f = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "quick_cards.json"
    try:
        cache = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    c = _conn()
    try:
        rows = c.execute("SELECT path, name, mtime, kind FROM journals").fetchall()
    finally:
        c.close()
    changed, live, out = False, set(), []
    for path, name, mtime, kind in rows:
        if (kind or "raw") != "raw":
            continue
        live.add(path)
        ent = cache.get(path)
        if not ent or abs(ent.get("m", 0) - (mtime or 0)) > 1e-6:
            cards = []
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            low = text.lower()
            for k, secs in (("decided", _SEC_DECIDED), ("exists", _SEC_EXISTS)):
                if not any(f"## {n}" in low for n in secs):
                    continue
                for cap in _parse_capabilities(text, secs):
                    cards.append({"k": k, "what": cap.get("what", "")[:500],
                                  "how": (cap.get("how") or cap.get("como") or "")[:220],
                                  "status": (cap.get("status") or cap.get("estado") or "")[:140],
                                  "date": cap.get("date") or cap.get("fecha") or cap.get("since") or cap.get("desde") or "",
                                  "aliases": cap.get("aliases") or cap.get("alias") or "",
                                  "keys": cap.get("keys") or cap.get("claves") or ""})
            ent = cache[path] = {"m": mtime or 0, "n": name, "c": cards}
            changed = True
        for card in ent.get("c", []):
            out.append(dict(card, journal=ent.get("n") or Path(path).name, path=path))
    for p in [p for p in cache if p not in live]:
        cache.pop(p)
        changed = True
    if changed:
        try:
            tmp = f.with_suffix(".tmp%d" % os.getpid())
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            os.replace(tmp, f)
        except Exception:
            pass
    return out


_ENTITY_GENERIC = set("""system studio studios desk lab labs hub app apps site web page pages journal journals full user
juice notes curriculum manual manuals sys mods mod tool tools product products company companies brand brands live
owner team box server""".split())
_ENT = {"stamp": None, "names": {}, "cards": [], "clusters": []}


def _entity_index() -> dict:
    """Named things, folded: {phrase: (kind, home)}. Kinds: company (company.json name and folder), key (Memory
    map keys), journal (journal name stems outside manuals), card (capitalized names inside card titles).
    home: a folder fragment or journal stem whose plans and cards belong to the thing."""
    from server import _default_roots
    c = _conn()
    try:
        stamp = c.execute("SELECT COUNT(*), MAX(mtime) FROM journals").fetchone()
        journals = c.execute("SELECT path, name, kind FROM journals").fetchall()
    finally:
        c.close()
    stamp = (tuple(stamp), os.environ.get("JOURNAL_ROOTS", ""), os.environ.get("JOURNAL_HOME", ""))
    if _ENT["stamp"] == stamp:
        return _ENT
    names: dict[str, tuple[str, str]] = {}
    for root in _default_roots():
        for cj in list(Path(root).glob("companies/*/company.json")) + list(Path(root).glob("*/companies/*/company.json")):
            slug = cj.parent.name
            try:
                nm = str(json.loads(cj.read_text(encoding="utf-8")).get("name") or "")
            except Exception:
                nm = ""
            for ph in {_fold(nm).strip(), _fold(slug.replace("-", " ").replace("_", " ")).strip()}:
                if len(ph) >= 3:
                    names[ph] = ("company", f"/companies/{_fold(slug)}/")
    for k in _map_keys():
        names.setdefault(k, ("key", ""))
    for path, name, kind in journals:
        if (kind or "raw") != "raw" or "/manuals/" in path.replace("\\", "/").lower():
            continue
        ws = [w for w in re.split(r"[^a-z0-9]+", _fold(Path(name).stem)) if w]
        ws = [w for w in ws if w not in ("journal", "full", "user", "notes")]
        if ws and not any(w in _ROLE_WORDS or w in _GENERIC_STEMS or w in _CHAT_WORDS or w in _ENTITY_GENERIC for w in ws):
            names.setdefault(" ".join(ws), ("journal", _fold(Path(name).stem)))
    cards = _cards_cache()
    for card in cards:
        toks = re.findall(r"[A-Za-zÀ-ÿ0-9][\w.-]*", card["what"])
        run: list[str] = []
        for j, t in enumerate(toks + [""]):
            cap = j > 0 and t[:1].isupper() and not t.isupper() and any(ch.islower() for ch in t)
            if cap:
                run.append(t.rstrip(".-"))
                continue
            if run:
                ph = _fold(" ".join(run[:3]))
                # One capitalized word in a card title is too loose ("Suite" of Calmline Suite matched "run the
                # suite"): single words only when mixed case or with a digit (Chatbot, Webweave, Localmodel3).
                if len(ph) >= 4 and (len(run) > 1 or re.search(r"[a-z].*[A-Z]|\d", run[0])):
                    names.setdefault(ph, ("card", ""))
                run = []
    clusters = []
    skip = _STOP | _CHAT_WORDS
    for card in cards:
        if card["k"] != "decided" or not card.get("aliases"):
            continue
        cl = [a for a in (_fold(x).strip() for x in card["aliases"].split(",")) if len(a) >= 3 and a not in skip]
        if len(cl) >= 2:
            clusters.append(cl)
    companies = [(set(nm.split()), h) for nm, (k, h) in names.items() if k == "company" and nm not in _ENTITY_GENERIC]
    _ENT.update(stamp=stamp, names=names, cards=cards, clusters=clusters, companies=companies)
    return _ENT


def _stem_phrase(name: str) -> str:
    return " ".join(w for w in re.split(r"[^a-z0-9]+", _fold(Path(name).stem)) if w and w not in ("journal", "full", "user", "notes"))


def _is_home(e: dict, path: str, name: str) -> bool:
    """A journal belongs to a named thing: it sits in the company's folder or is named after it."""
    return bool((e.get("home") and e["home"].startswith("/") and e["home"] in _fold(path.replace("\\", "/")))
                or e["name"] == _stem_phrase(name))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(str(text or "")).replace("_", " "))


def _subject(e: dict, text: str, n: int = 12) -> bool:
    """The named thing is the subject of a text: it is named in its first n words."""
    return f" {e['name']} " in " " + " ".join(_tokens(text)[:n]) + " "


def _company_count(text: str) -> int:
    """How many different companies a text names (all words of a company name present). 3 or more: a roster.
    Links and paths are not mentions: "hq.example.com/live/launch-desk ... mapleworks.dev/live" is one plan."""
    text = re.sub(r"\S*(?:[\\/]|\.(?:ai|dev|com|io|net|org|app|run)\b)\S*", " ", str(text or ""))
    words = set(_tokens(text))
    comps = _ENT.get("companies") if _ENT.get("stamp") else None
    if comps is None:   # built with the entity index; never re-read per card or plan row (each read is a DB query)
        comps = _entity_index()["companies"]
    return len({h for ws, h in comps if ws <= words})


def _entities_in(text: str, kinds: tuple = ("company", "key", "journal", "card")) -> list[dict]:
    """Named things in a query, longest phrase first, at most 3. A single word that is not a company or a Memory
    map key must also be specific: in at most 40% of journals (journal names) or 30% (names in cards)."""
    idx = _entity_index()["names"]
    toks = _tokens(text)
    found, used = [], set()
    for n in (3, 2, 1):
        for i in range(len(toks) - n + 1):
            if any(j in used for j in range(i, i + n)):
                continue
            ph = " ".join(toks[i:i + n])
            hit = idx.get(ph)
            if not hit or hit[0] not in kinds or any(e["name"] == ph for e in found):
                continue
            if n == 1:
                w = ph
                if len(w) < 3 or w in _STOP or w in _CHAT_WORDS or w.isdigit() or \
                        (hit[0] != "key" and (w in _ROLE_WORDS or w in _GENERIC_STEMS or w in _ENTITY_GENERIC)):
                    continue
                if hit[0] in ("journal", "card") and _share(w) > (0.4 if hit[0] == "journal" else 0.3):
                    continue
            found.append({"name": ph, "kind": hit[0], "home": hit[1]})
            used |= set(range(i, i + n))
    return sorted(found, key=lambda e: -len(e["name"].split()))[:3]


def _query_groups(text: str, ents: list[dict], cap: int = 8) -> list[dict]:
    """The ideas of a query: each named thing is one, each other content word is one with its synonyms (the
    Spanish to English table, the alias groups, and every Decided card's alias cluster it falls in)."""
    toks, trans = _tokens(text), _tokens(_to_english(str(text or "")))
    ent_words = {w for e in ents for w in e["name"].split()}
    groups = [{"label": e["name"], "phr": {e["name"]}, "entity": True} for e in ents]
    for w in toks:
        if len(groups) >= cap + len(ents):
            break
        if len(w) < 3 or w in ent_words or w in _STOP or w in _CHAT_WORDS or w in _GENERIC_STEMS or w.isdigit() \
                or any(w in g["phr"] for g in groups):
            continue
        phr = {w} | ({_ES_EN[w]} if w in _ES_EN else set())
        phr |= {t for t in _expand_terms(w) if re.fullmatch(r"[a-z0-9 ]+", t) and len(t) >= 3}
        groups.append({"label": w, "phr": phr, "entity": False})
    line = " " + " ".join(toks) + " " + " | " + " ".join(trans) + " "
    tokset = set(toks) | set(trans)
    labels = {g["label"] for g in groups}
    for cl in _entity_index()["clusters"]:
        trig = [a for a in cl if set(a.split()) <= tokset and f" {a} " in line]
        if not trig:
            continue
        for g in groups:
            if g["entity"]:
                continue
            if any(g["label"] in a.split() or _ES_EN.get(g["label"], "#") in a.split() for a in trig):
                g["phr"] |= {a for a in cl if not (set(a.split()) & (labels - {g["label"]})) and not (set(a.split()) & ent_words)}
    return groups


def _hits(words: set, groups: list[dict]) -> int:
    """How many ideas of the query a text covers (a phrase counts when all its words are there, stemmed)."""
    return sum(1 for g in groups if any(all(_stem(x) in words for x in p.split()) for p in g["phr"]))


def _stemset(text: str) -> set:
    return {_stem(w) for w in _tokens(text)}


def _plan_closed(c, plan: dict, skip: set) -> bool:
    """A later dated entry in any journal closes the plan: one of its sentences has a closing word, no open-work
    word, and shares at least 3 of the plan's words (and 30% of them, so a long plan needs more)."""
    words = [w for w in plan["words"].split() if w not in _PLAN_CLOSE_WORDS]
    if len(words) < 3:
        return False
    need = max(3, -(-3 * len(words) // 10))
    mine = {_stem(w) for w in words}
    probe = sorted(words, key=len, reverse=True)[:12]
    q = "body : (" + " OR ".join(f'"{w}"' for w in probe) + ') AND body : ("live" OR "shipped" OR "deployed" OR ' \
        '"done" OR "closed" OR "published")'
    try:
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? "
                         "AND substr(heading, 1, 10) >= ? ORDER BY rank LIMIT 150", (q, plan["date"][:10])).fetchall()
    except Exception:
        return False
    for path, line, heading, body in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m or (m.group(1) + " " + (m.group(2) or "00:00")) <= plan["date"]:
            continue
        for ln in (body or "").splitlines():
            for s in _SENT_SPLIT.split(ln.strip()):
                if not _PLAN_CLOSE.search(s) or _PLAN_MARK.search(_QUOTED.sub(" ", s)):
                    continue
                if len(mine & {_stem(w) for w in _plan_words(s, skip)}) >= need:
                    return True
    return False


_CLOSED_MEMO: dict = {}


def _open_plans(groups: list[dict], ents: list[dict], cap: int = _PLAN_CAP, single: bool = False) -> list[dict]:
    """Open plans that match the query, ranked by how many of its ideas they share, newest first. A plan
    qualifies when it names (or lives in the home of) a named thing of the query, or shares 2 ideas (1 when
    the query is a single word)."""
    if not groups:
        return []
    words = sorted({w for g in groups for p in g["phr"] for w in p.split() if len(w) >= 3})
    if not words:
        return []
    c = _conn()
    try:
        _sync_plans(c)
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        cols = "path, line, date, text, words, head"
        rows = c.execute(f"SELECT {cols} FROM plans_fts WHERE plans_fts MATCH ? LIMIT 3000",
                         ("words : (" + " OR ".join(f'"{w}"' for w in words[:40]) + ")",)).fetchall()
        home_paths = {p for p in names if any(_is_home(e, p, names[p]) for e in ents)}
        for path in sorted(home_paths)[:12]:
            rows += c.execute(f"SELECT {cols} FROM plans_fts WHERE path = ?", (path,)).fetchall()
        others = [g for g in groups if not g["entity"]]
        need = 1 if single or len(groups) == 1 else 2
        scored, seen = [], set()
        for path, line, date, text, pw, head in rows:
            key = (path, line, text)
            if key in seen:
                continue
            seen.add(key)
            ws = {_stem(w) for w in pw.split()}
            if _company_count(text) >= 3:
                continue   # a roster line ("Launch Desk ..., Forecast Desk ..., Tone Garden ...") is about none
            # A plan belongs to a named thing only when the thing is its SUBJECT (its first 12 words) or it sits in
            # the thing's own journal; a name somewhere in the middle is a passing mention (2026-10-26 regression).
            home = path in home_paths
            subj = any(_subject(e, head or "") for e in ents)
            rel = 2 if home else (1 if subj else 0)
            h = _hits(ws, others) + (1 if rel else 0)
            # Without a named thing, the query's own words (or their translation) must be there: a chat word
            # expanded through an alias cluster must never turn into a topic on its own.
            direct = _hits(ws, [dict(g, phr={g["label"], _ES_EN.get(g["label"], g["label"])}) for g in others])
            if not (rel or direct >= need) or h < 1:
                continue
            scored.append(((h, rel), date, {"journal": names.get(path, Path(path).name), "line": int(line),
                                            "date": date, "plan": text, "words": pw, "path": path}))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        out, texts, skip = [], set(), _plan_skip()
        stamp = tuple(c.execute("SELECT COUNT(*), MAX(mtime) FROM entries_meta").fetchone())   # a new entry may close one
        for _, _, p in scored[:12]:
            t = re.sub(r"\W+", " ", _fold(p["plan"]))[:120]
            if t in texts:
                continue
            k = (p["path"], p["line"], p["plan"], stamp)
            if k not in _CLOSED_MEMO:
                _CLOSED_MEMO[k] = _plan_closed(c, p, skip)
            if _CLOSED_MEMO[k]:
                continue
            texts.add(t)
            out.append({x: p[x] for x in ("journal", "line", "date", "plan")})
            if len(out) >= cap:
                break
        return out
    except Exception:
        return []
    finally:
        c.close()


def _entity_about(ents: list[dict], groups: list[dict], cap: int = 2) -> list[dict]:
    """Dated entries of a named thing's own journals whose TITLE carries another idea of the query: "tone garden
    goal" -> "[goal] COMPANY GOAL ..." in the company's Director manual."""
    others = [g for g in groups if not g["entity"]]
    words = sorted({w for g in others for p in g["phr"] for w in p.split() if re.fullmatch(r"[a-z0-9]{3,}", w)})
    if not ents or not words:
        return []
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading FROM entries_fts WHERE entries_fts MATCH ? LIMIT 2000",
                         ("heading : (" + " OR ".join(f'"{w}"' for w in words[:30]) + ")",)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    out = []
    for path, line, heading in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m or not any(_is_home(e, path, names.get(path, "")) for e in ents):
            continue
        if not _hits(_stemset(heading), others):
            continue
        out.append((m.group(1) + " " + (m.group(2) or "00:00"), names.get(path, Path(path).name), int(line), heading))
    out.sort(reverse=True)
    return [{"when": w, "journal": j, "line": ln, "entry": h[:160]} for w, j, ln, h in out[:cap]]


def _entity_cards(ents: list[dict], groups: list[dict]) -> tuple[list[dict], list[dict]]:
    """A named thing's own Decided and Already-exists cards, from any journal: the card names it (title first,
    then its aliases and keys) or sits in the thing's home journal; ranked by the query's other ideas, then date."""
    if not ents:
        return [], []
    others = [g for g in groups if not g["entity"]]
    dec, exi = [], []
    for card in _entity_index()["cards"]:
        if _company_count(card["what"]) >= 3:
            continue   # a card that lists every company is a roster, not about one of them
        extra = " " + " , ".join(_fold(x).strip() for x in (card.get("aliases", "") + "," + card.get("keys", "")).split(",")) + " "
        extra_toks = " " + " ".join(_tokens(card.get("aliases", "") + " " + card.get("keys", ""))) + " "
        best = 0
        for e in ents:
            # A card belongs to a named thing only when the thing is its SUBJECT (first 12 words of its title), an
            # alias or key of it, or the card sits in the thing's own journal. A name further inside the title is a
            # passing mention: the Launch Desk name card mentions "Mapleworks Labs", the Dreamfield MCP card an
            # "Tone Garden account" (2026-10-26 regression: both showed on every map of those names).
            if _subject(e, card["what"]) or _is_home(e, card["path"], card["journal"]):
                best = max(best, 2)
            elif f" {e['name']} " in extra or f" {e['name']} " in extra_toks:
                best = max(best, 1)
        if not best:
            continue
        h = _hits(_stemset(card["what"] + " " + card.get("aliases", "") + " " + card.get("keys", "")), others)
        (dec if card["k"] == "decided" else exi).append((best, h, card.get("date") or "", card))
    pick = lambda xs, n: [x[3] for x in sorted(xs, key=lambda x: (x[0], x[1], x[2]), reverse=True)[:n]]
    return ([{"what": x["what"], "journal": x["journal"], "date": x.get("date")} for x in pick(dec, 3)],
            [{"what": x["what"], "status": x.get("status"), "journal": x["journal"], "how": x.get("how")} for x in pick(exi, 2)])


# Owner verdicts on things already tried live in plain dated entries ("Veredicto de Owner sobre Glowcam Ray 3.2 ...:
# esta bueno pero el loop no es seamless"), not in cards, so no map showed them and a session proposed a tested
# method as new (2026-10-26, Glowcam loop; same class as the fal, Chatbot, generar.py, mail list and /live misses:
# know-how written as an entry never surfaced). The map now reads the entries themselves for verdict sentences.
_VERDICT_FTS = ('(veredicto OR verdict OR rechazado OR rejected OR "dead end" OR "no sirve" OR "does not work" OR '
                '"not seamless" OR "not usable" OR "owner said" OR "dueño dijo" OR "owner verdict" OR owner OR dueño)')
_VERDICT_RE = re.compile(r"veredicto|verdict|rechazad|rejected|dead end|no sirve|does not work|doesn't work|"
                         r"not seamless|not usable|owner said|dueño dijo|owner:", re.I)


# The owner's own word on a test ranks above a technical rejection: "Veredicto de Owner ...", "owner verdict",
# "Owner: \"...\"", "owner said".
# "owner still sees the camera move in the crossing" (2026-10-27 Inner Sight) is a verdict too: it sat inside a summary
# line with no "verdict" word, a session wrote "no owner verdict" in the Handoff and re-showed the rejected clip.
_OWNER_SAID = re.compile(r"(veredicto|verdict)\W+(?:de|del|of|from)?\s*(owner|dueño)|(owner|dueño)(?:'s)?\s+"
                         r"(?:still\s+|also\s+|sigue\s+|todavia\s+)?(verdict|veredicto|dijo|said|says|rejected|rechaz|"
                         r"sees|saw|ve|vio|prefers|preferred|prefiere|picked|chose|eligio|approved|aprobo|likes|liked|"
                         r"does not like|did not like|didn't like|doesn't like|no le gusta|wants|quiere|"
                         r"correction|corrected|corrige|corrigio|corrigió|correccion|corrección)\b|"
                         r"corregido por (?:el |la )?(owner|dueño)\b|"
                         r"(owner)\b[^:\"]{0,30}:\s*[\"“]", re.I)


# A verdict still to come is not one ("Pendiente el veredicto de Owner y el resultado de E", 2026-10-28: shown
# as what the owner already said about Clipgen).
_AWAIT_VERDICT = re.compile(r"\b(?:pendiente|pending|falta|esperando|espera|awaiting|waiting(?: for)?|needs?|sin|no)\s+"
                            r"(?:el |the |an? |su |his |her |their |del |un )?(?:veredicto|verdict)|"
                            r"\b(?:veredicto|verdict)\s+(?:pendiente|pending|to come|por venir)", re.I)


def _verdicts(expr: str, words: list, cap: int = 3, near: set = None) -> list[dict]:
    """Dated entries matching the topic that carry an owner verdict or a rejection; returns the sentence that says
    it (the verdict itself, not just the title), entries of the topic's own journals first, newest first."""
    words = [w for w in words if re.fullmatch(r"[a-z0-9]{3,}", w)]
    if not expr or not words:
        return []
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 300",
                         (f"({expr}) AND {_VERDICT_FTS}",)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    has = lambda s: any(re.search(r"(?<![a-z0-9])" + re.escape(w), _fold(s)) for w in words)
    out, seen = [], set()
    for path, line, heading, body in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m:
            continue
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+|\s+·\s+", (body or "") + "\n" +
                                             _HEAD_DATE.sub("", heading or "")) if s.strip()]
        # file and script names are not verdicts: "_rechazado.mp4", "veredicto.py", "_veil40_rejected.mp4"
        bare = lambda s: re.sub(r"\S*[._/\\]\S*", " ", s)
        vs = [s for s in sents if (_VERDICT_RE.search(bare(s)) or _OWNER_SAID.search(bare(s))) and not s.lstrip().startswith("- [")
              and not _AWAIT_VERDICT.search(bare(s))]
        owner = [s for s in vs if _OWNER_SAID.search(bare(s))]
        # "Seen down: a, b. Owner correction: these are NOT outages" names the thing one sentence before (2026-10-28)
        beside = lambda s: any(has(x) for x in sents[max(0, sents.index(s) - 1):sents.index(s) + 2])
        said = (next((s for s in owner if has(s)), "") or (owner[0] if owner and has(heading) else "")
                or next((s for s in owner if beside(s)), "")
                or next((s for s in vs if has(bare(s)) and len(bare(s).split()) >= 6), ""))
        if not said:
            continue
        score = (3 if re.search(r"veredicto|verdict", said, re.I) else 2) if said in owner else 1
        said = re.sub(r"^\d{4}-\d{2}-\d{2}[ T]?\d{0,2}:?\d{0,2}\s*(\[[^\]]*\]\s*)?", "", said)
        key = _fold(said)[:80]
        if key in seen:
            continue
        seen.add(key)
        j = names.get(path, Path(path).name)
        out.append((score, bool(near) and j in near, m.group(1) + " " + (m.group(2) or "00:00"), j, int(line), said[:260], path))
    out.sort(reverse=True)
    out.sort(reverse=True)
    return [{"when": w, "journal": j, "line": ln, "said": s, "owner": sc >= 2, "path": p}
            for sc, _, w, j, ln, s, p in out[:cap]]


# A newer entry that says a piece was replaced, moved or redesigned (2026-10-27: a session edited media-library.js
# three times because a 2026-10-22 entry said "Library tab ... media-library.js"; since the App Studio tab redesign
# of 2026-10-25 the company Library tab is clib() in aa.html, and the map showed that only as one passive line).
# said AFTER the piece ("the Library tab is NOT media-library.js", "X moved to aa.html")
# "is not / is now / moved to / now lives in" only when what follows names a file or code ("is NOT
# media-library.js", "is now clib() inside aa.html"): "the drip file isn't reachable" is not a replacement.
_FILE_OR_CODE = r"[^.;\n]{0,40}?(?:[\w-]+\.(?:js|mjs|ts|tsx|py|html?|css|sh|json|astro|vue)\b|\w+\(\))"
_REPL_AFTER = re.compile(r"\b(?:replaced (?:by|with)|no longer (?:used|in use|served|loaded)|superseded|deprecated|"
                         r"retired|was replaced)\b|\b(?:is not|isn't|is now|moved (?:to|into)|now lives (?:in|at))"
                         + _FILE_OR_CODE, re.I)
# said around it ("media-library.js (old Studio library) instead of new code")
_REPL_ANY = re.compile(r"\b(?:replaced (?:by|with)|instead of|replaces)\b", re.I)
_BULLET_DATE = re.compile(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2})?")


def _near(rx: re.Pattern, a: re.Pattern, text: str, span: int = 80, after: bool = False) -> bool:
    """A match of rx within span characters of a match of a (after it, when after=True)."""
    ps = [m.end() for m in a.finditer(text)]
    return any((0 <= m.start() - p <= span) if after else abs(m.start() - p) <= span
               for m in rx.finditer(text) for p in ps)


def newer_about(token: str, cap: int = 3) -> dict:
    """For a file an action touches: the older entry that says which piece the file is (its title names the piece
    with every word of the file's stem, its body names the file) and NEWER entries, in any journal, saying that
    piece was replaced, moved, redesigned or rebuilt (the marker next to the piece word in the same sentence).
    {"claim": {...}, "newer": [{when, journal, line, said}]} or {}."""
    name = _fold(Path(str(token).replace("\\", "/")).name)
    stem = re.sub(r"\.[a-z0-9]{1,6}$", "", name)
    toks = [w for w in re.split(r"[^a-z0-9]+", stem) if len(w) >= 4]
    words = [w for w in toks if w not in _GENERIC_STEMS]
    if not words or stem == name:
        return {}
    phrase = " ".join(x for x in re.split(r"[^a-z0-9]+", stem) if x)
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 400",
                         (f'"{phrase}"',)).fetchall()
        claims, knows = [], set()
        for path, line, heading, body in rows:
            if name in _fold(body or "") or name in _fold(heading or ""):
                knows.add(path)
            m = _HEAD_DATE.match(heading or "")
            h = _fold(_HEAD_DATE.sub("", heading or ""))
            # every word of the stem in the title ("library_index.py" needs "index" too) and the file in the body
            if m and all(re.search(r"(?<![a-z0-9])" + re.escape(w), h) for w in toks) and name in _fold(body or ""):
                claims.append((m.group(1) + " " + (m.group(2) or "00:00"), path, int(line), heading))
        if not claims:
            return {}
        claims.sort()
        cw, cpath, cline, chead = claims[0]
        kn = sorted(knows)
        cand = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? AND path IN ("
                         + ",".join("?" * len(kn)) + ") LIMIT 1500", (" OR ".join(words), *kn)).fetchall() if kn else []
    except Exception:
        return {}
    finally:
        c.close()
    piece_re = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?:s|'s)?(?![a-z0-9])")
    # "rebuilt" and "rewrite" are everyday work on a piece (a calendar rebuilt from its data), not a replacement
    joined = re.compile(r"(?<![a-z0-9])" + r"[\s_-]*".join(re.escape(w) for w in toks) + r"(?![a-z0-9])")
    redo_re = re.compile(r"\bredesign(?:ed)?\b|\bold\s+(?:"
                         + "|".join(re.escape(w) for w in words) + r")")
    out, seen = [], set()
    for path, line, heading, body in cand:
        # only journals that know this file: the same word in another product's journal ("ONE Library tab" of
        # the AA site) is another piece
        if (path, int(line)) == (cpath, cline) or path not in knows:
            continue
        hm = _HEAD_DATE.match(heading or "")
        units = []
        if hm:
            units.append((hm.group(1) + " " + (hm.group(2) or "00:00"), (body or "") + "\n" + _HEAD_DATE.sub("", heading)))
        for ln in (body or "").splitlines():
            bm = _BULLET_DATE.match(ln)
            if bm:
                units.append((bm.group(1) + " " + (bm.group(2) or "00:00"), ln))
        for when, text in units:
            if when <= cw or (path, int(line), when) in seen:
                continue
            for s in re.split(r"(?<=[.!?;])\s+|\n+", text):
                fs = _fold(s)
                if not all(re.search(r"(?<![a-z0-9])" + re.escape(w), fs) for w in words):
                    continue   # every word of the piece ("drip" and "runner"), not one of them
                if len(toks) >= 2 and not joined.search(fs):
                    continue   # with_keys.py is "with keys" together, never "Keys ... replaced with vault" (2026-10-28)
                strong = _near(_REPL_AFTER, piece_re, fs, 40, after=True) or _near(_REPL_ANY, piece_re, fs, 40)
                redo = _near(redo_re, piece_re, fs, 60)
                if name in fs and not strong:
                    continue   # an entry about the file itself must SAY it was replaced
                if not (strong or redo):
                    continue
                seen.add((path, int(line), when))
                said = re.sub(r"^\s*[-*]\s*", "", s.strip())
                out.append((2 if strong else 1, when, names.get(path, Path(path).name), int(line), said[:240]))
                break
    if not out:
        return {}
    out.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return {"claim": {"when": cw, "journal": names.get(cpath, Path(cpath).name), "line": cline,
                      "entry": _HEAD_DATE.sub("", chead).strip()[:140]},
            "newer": [{"when": w, "journal": j, "line": ln, "said": s} for _, w, j, ln, s in out[:cap]]}


def newer_text(nb: dict, what: str) -> str:
    L = [f"REPLACED/NEWER for {what}: newer entries say this piece was replaced, moved or redesigned. Check which "
         "file serves it NOW before editing:"]
    for x in nb["newer"]:
        L.append(f"- REPLACED/NEWER ({x['when']}, {x['journal']}:{x['line']}): {x['said']}")
    cl, n0 = nb["claim"], nb["newer"][0]
    L.append(f"- MAY BE STALE, newer: {n0['journal']}:{n0['line']}: {cl['entry']} ({cl['journal']}:{cl['line']}, {cl['when']})")
    return "\n".join(L)


# Shipped work beats an older "not built" (2026-10-28 real case, PC main session): the owner was told "pending:
# Shapesmith, build it on the box" while SHOPSITE_FULL_JOURNAL had "[ship] CRAFT ENGINES CONNECTED" and "[ship] CRAFT
# ENGINES IN THE BROWSER LIVE" of 2026-10-27 (titles that never name Shapesmith; the body does, also as
# "shapesmith-cli"). The map's ABOUT lines only read titles, a map shown again dropped every LATEST line, and the
# CREATIVE_HUB Current state (dated 2026-10-25, "Built? NOT built") looked like today's truth. The newest ship entries
# that mention the word anywhere, in any journal, now show first and survive the short re-shown map.
_SHIP_HEAD_TAG = re.compile(r"^\s*\[(?:ship|shipped|live|deploy)\]", re.I)
_SHIP_HEAD_WORD = re.compile(r"\b(?:LIVE|BUILT|CONNECTED|INSTALLED|SHIPPED|DEPLOYED)\b")
_NOT_SHIPPED = re.compile(r"\bnot (?:yet )?(?:shipped|built|live|installed|deployed|connected)\b", re.I)
# A line that says a thing is not done yet: older than a ship of the same thing, it may be stale.
_NOT_DONE = re.compile(r"\bnot (?:yet )?(?:built|forked|installed|live|shipped|connected|deployed|started)\b|"
                       r"\bpc only\b|\bplanned only\b|\bonly planned\b|\bpending\b|\bnot yet\b|\bto build\b", re.I)


_RUNS = re.compile(r"\b(?:live|built|builds? ok|connected|installed|shipped|deployed|released|running|working)\b", re.I)


# A STATE claim is a fact that changes after it is written: active/inactive, verified, paused/running, live/down,
# suspended, pending approval, a balance, a count, "0 orders", "not created yet". 2026-10-30 real case: the map
# printed NEWEST WORD ON 'whop-launch-desk-business' (a 10-29 ship entry whose body said "payouts INACTIVE until
# the owner verifies identity once") and the session repeated it to the owner as current; the Whop API showed the
# identity approved and the payout account connected. 12+ earlier cases had the same shape (a farm listed active
# while off, a mail list count 890 vs 1115 live, a stale credit file, "out of credit", a 64 fps claim). A map line
# that carries one is marked: as of when it was written, check it live before repeating it.
_STATE_CLAIM = re.compile(
    r"(?<![\w-])(?:"
    # English status words. A bare common one ("Active projects", "keep it active", "the code expired while...")
    # is no state: it needs a verb or an "=" / ":" before it (live probe 2026-10-30). Rare ones stand alone.
    r"suspended|banned|deactivated|unverified|disconnected|"
    r"(?:paused|active|enabled|disabled)\s*[:=]\s*(?:true|false|yes|no|on|off|1|0)|"
    r"(?:is|are|was|were|now|still|stays?|currently|not|no longer|isn't|aren't|[:=])\s*"
    r"(?:(?:yet|fully|really)\s+)?(?:live|running|down|off|stopped|verified|approved|rejected|"
    r"blocked|connected|working|available|(?:in)?active|enabled|disabled|paused|offline|online|expired)|"
    r"(?:account|payouts?|payments?|identity|store|shop|listing|business|server|bot|service|worker|cron|farm)\s+"
    r"(?:is\s+|are\s+)?(?:still\s+|now\s+)?(?:connected|verified|approved|up|down|live|running|stopped|paused|"
    r"enabled|disabled|active|inactive)|"
    r"(?:live|running|up|down|off)\s+now|"
    r"not\s+(?:yet\s+)?(?:created|verified|approved|enabled|listed|published|paid out|set up|configured)|"
    r"(?:pending|awaiting|waiting for)\s+(?:the\s+)?(?:\w+\s+)?"
    r"(?:approval|review|verification|activation|confirmation|payout)|"
    r"(?:needs?|requires?)\s+(?:the\s+)?(?:\w+\s+)?(?:approval|verification|activation)|"
    r"(?:approval|review|verification|payout|activation)\s+(?:is\s+)?(?:still\s+)?pending|"
    r"verif(?:y|ies|ied)\s+(?:his\s+|her\s+|their\s+|the\s+)?identity|identity\s+(?:is\s+)?(?:not\s+)?"
    r"(?:verified|approved|pending)|"
    r"runs?\s+on|running\s+on|"
    r"out of credits?|no credits?(?:\s+left)?|credits?\s+left|"
    r"(?:wallet|account|usd|sol|stripe|whop|credit)\s+balance|balance\s*(?:is|of|:|=)?\s*(?:us)?\$?\d|"
    r"(?:no|zero|\d[\d,.]*)\s+(?:orders|sales|buyers|customers|subscribers|members|contacts|followers|signups|"
    r"sign-ups|downloads|installs)|"
    r"\d+(?:\.\d+)?\s*fps|"
    r"(?:[a-z]+_)?status\s*[:=]?\s*\"?(?:not_available|available|active|inactive|connected|approved|pending|paused)|"
    # Spanish status words
    r"(?:est[aá]n?|qued[oó]|quedaron|sigue|siguen|ya|no)\s+(?:est[aá]n?\s+)?(?:activ[oa]s?|inactiv[oa]s?|"
    r"pausad[oa]s?|apagad[oa]s?|prendid[oa]s?|encendid[oa]s?|ca[ií]d[oa]s?|verificad[oa]s?|aprobad[oa]s?)|"
    r"inactiv[oa]s?|suspendid[oa]s?|bloquead[oa]s?|"
    r"(?:est[aá]n?|sigue|siguen|ya)\s+(?:en vivo|corriendo|andando|funcionando)|"
    r"pendiente\s+de\s+(?:aprobaci[oó]n|verificaci[oó]n|revisi[oó]n|pago|activaci[oó]n)|"
    r"sin\s+(?:saldo|cr[eé]ditos?|ventas|pedidos)|saldo|"
    r"(?:\d[\d,.]*|cero)\s+(?:ventas|pedidos|compras|clientes|suscriptores|miembros|contactos|seguidores)|"
    r"(?:todav[ií]a|a[uú]n)\s+no\s+(?:cread[oa]|verificad[oa]|aprobad[oa]|activ[oa])|"
    r"no\s+(?:cread[oa]|verificad[oa]|aprobad[oa])\s+(?:todav[ií]a|a[uú]n)"
    r")(?![\w-])", re.I)
_STATE_URL = re.compile(r"https?://[^\s)\]\"'>|]+")
_STATE_HOW = re.compile(r"\b(?:how|check|see|verify|c[oó]mo|ver)\s*:\s*([^|;\n]{4,})", re.I)
_STATE_FILE = re.compile(r"(?<![\w-])((?:[\w~.-]+/)*[\w.-]+\.(?:json|jsonl|csv|txt|log|toml|ya?ml|db|sqlite|md))\b")


def _state_hint(text: str, keys: tuple = (), how: str = "", key: str = "") -> str:
    """"" when the text carries no state claim; else a short "how to check it live" taken from what the line
    already carries: a vault key (the line's own key, or one it names), a URL, a card's how/see/check field, a
    file path, or a generic one."""
    s = text or ""
    if not _STATE_CLAIM.search(s):
        return ""
    fs = _fold(s)
    if not key:
        key = next((k for k in keys if k and re.search(r"(?<![a-z0-9_-])" + re.escape(_fold(k)) + r"(?![a-z0-9_-])",
                                                       fs)), "")
    if not key:
        m = re.search(r"\bvault\s+(?:entry\s+|key\s+)?['\"]?([a-z0-9][a-z0-9_-]{3,60}[a-z0-9])", fs)
        key = m.group(1) if m else ""
    if key:
        return f"read it live with the {key[:50]} key's API"
    url = _STATE_URL.search(s)
    if url:
        return f"open or curl {url.group(0).rstrip('.,;:')[:60]}"
    h = (how or "").strip() or next((m.group(1).strip() for m in [_STATE_HOW.search(s)] if m), "")
    if h:
        return f"as its card says: {h[:60]}"
    f = _STATE_FILE.search(s)
    if f:
        return f"read {Path(f.group(1)).name[:60]} now"
    return "measure it live before saying it"


_STATE_HEADER = ("- STATE CLAIMS BELOW are as of when they were written; check them live (API, file, command) "
                 "before telling anyone.")


def _state_sentence(body: str, anchor: str = "") -> str:
    """The sentence of an entry body that carries a state claim nearest to the sentence naming `anchor` (a vault
    key), cut around the claim. The NEWEST WORD line only shows the sentence naming the key; in the Whop case the
    claim ("payouts INACTIVE until the owner verifies identity") sat in the next one, and an earlier sentence
    ("the Save stayed disabled") was about a button, not the key's account."""
    sents = [re.sub(r"^\s*[-*|]\s*", "", x.strip()) for x in re.split(r"(?<=[.!?])\s+|\n+", body or "") if x.strip()]
    rx = re.compile(r"(?<![a-z0-9_-])" + re.escape(_fold(anchor)) + r"(?![a-z0-9_-])") if anchor else None
    at = next((i for i, x in enumerate(sents) if rx and rx.search(_fold(x))), 0)
    hits = [(abs(i - at) + (0.5 if i < at else 0), i) for i, x in enumerate(sents) if _STATE_CLAIM.search(x)]
    if not hits:
        return ""
    s = sents[min(hits)[1]]
    u = _STATE_URL.search(s)
    s = (s[:u.start()] if u and _STATE_CLAIM.search(s[:u.start()]) else _STATE_URL.sub("", s)).strip()
    m = _STATE_CLAIM.search(s)
    a = max(0, m.start() - 40) if m else 0
    return ("..." if a else "") + s[a:a + 90].rstrip(" :;,(")


def _is_ship_heading(heading: str) -> bool:
    h = _HEAD_DATE.sub("", heading or "")
    return bool(_SHIP_HEAD_TAG.search(h)) or (bool(_SHIP_HEAD_WORD.search(h)) and not _NOT_SHIPPED.search(h))


def shipped_about(groups: list, cap: int = 3) -> list[dict]:
    """Newest dated ship entries ([ship] tag, or a LIVE / BUILT / CONNECTED title) whose title or body names the
    word (also inside a compound: "shapesmith-cli"), across every journal, newest first. Each carries the sentence
    that names it."""
    words = [t for g in groups for t in g if re.fullmatch(r"[a-z0-9_]{3,}", t)]
    if not words:
        return []
    expr = " AND ".join(_fts_or(g) for g in groups)
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 4000",
                         (expr,)).fetchall()
    except Exception:
        return []
    finally:
        c.close()
    rx = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")")
    rare = len(groups) == 1 and _share(groups[0][0]) <= 0.15
    out = []
    for path, line, heading, body in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m or not _is_ship_heading(heading):
            continue
        title = _HEAD_DATE.sub("", heading or "").strip()
        naming = [re.sub(r"^\s*[-*|]\s*", "", x.strip())
                  for x in re.split(r"(?<=[.!?;])\s+|\n+", title + "\n" + (body or "")) if rx.search(_fold(x))]
        said = naming[0] if naming else ""
        if not said:
            continue   # the FTS synonyms matched, the text never names it
        # The entry must be ABOUT it: named in the title; or, for a word few journals use (a product name such as
        # Shapesmith), named twice or in a sentence that says it runs ("shapesmith-cli ... release builds OK").
        # A passing mention of a common word ("localmodel" inside a load governor ship, "webweave" inside a social tool,
        # "glowcam" in a list of past misses) is not a ship of that thing.
        # A family title counts for a rare compound name: "CRAFT ENGINES CONNECTED" is about Shapesmith.
        ft = _fold(title)
        family = rare and any(len(t) >= 4 and t not in words and any(w != t and (w.endswith(t) or w.startswith(t))
                                                                      for w in words)
                              for t in re.findall(r"[a-z0-9]+", ft))
        if not rx.search(ft) and not (rare and (family or len(rx.findall(_fold(body or ""))) >= 2 or _RUNS.search(said))):
            continue
        out.append({"when": m.group(1) + " " + (m.group(2) or "00:00"), "journal": names.get(path, Path(path).name),
                    "line": int(line), "entry": title[:140], "said": said[:220], "path": path,
                    "ctx": " ".join([title] + naming[:6])[:1500]})
    out.sort(key=lambda x: x["when"], reverse=True)
    seen, res = set(), []
    for x in out:
        k = (x["journal"], x["line"])
        if k not in seen:
            seen.add(k)
            res.append(x)
    return res[:cap]


def _stale_state_lines(path: str, text: str, rx: re.Pattern, newest: dict, own: bool = True) -> str:
    """A home journal's Current state is stale when its date is older than a ship: its own newest [ship]
    (server.state_staleness) or a newer ship of the mapped word in any journal, when a state line naming the word
    says it is not done."""
    from server import state_staleness
    st = state_staleness(text) if own else {}
    name = Path(path).name
    if st:
        return (f"- CURRENT STATE MAY BE STALE ({name}, dated {st['state_date']}): this journal shipped newer work "
                f"on {st['ship_when']} ({st['ship_title'][:100]}). Trust the newer entries.")
    if not newest:
        return ""
    sec = _find_section(text, ("current state", "estado actual"))
    if not sec:
        return ""
    ds = re.findall(r"20\d\d-\d\d-\d\d", sec[1])
    if not ds or max(ds) >= newest["when"][:10]:
        return ""
    bad = [ln.strip() for ln in sec[1].splitlines() if rx.search(_fold(ln)) and _NOT_DONE.search(ln)]
    if not bad:
        return ""
    return (f"- CURRENT STATE MAY BE STALE ({name}, dated {max(ds)}: \"{bad[0][:100]}\"): newer ship on "
            f"{newest['when']} in {newest['journal']}:{newest['line']}.")


def _english_stems(text: str) -> set:
    # 3 letters: "caja" is "box"
    return ({_stem(w) for w in re.findall(r"[a-z]{3,}", _fold(_to_english(text)))}
            - {_stem(w) for w in _STOP | _CHAT_WORDS} - _GENERIC_REPLY)


_GENERIC_REPLY = set("first primer primera nuevo nueva todo todos para este esta esto with from that this then "
                     "also only more ahora despues the and for por con los las del una uno que not are was its "
                     "you your can now new all any "
                     # words about our own way of working are in every entry, never the topic (2026-10-28: "journal"
                     # tied a reply about the journals mod to a 10-15 Clipgen quote that says "busca journal")
                     "journal journals mod mods session sesion sesiones entry entries entrada entradas".split())


# Words in a journal's name or folder that do not say which project it is.
_GENERIC_ID = set("journal journals user full the and dna md mcp studios studio system desktop coding "
                  "users companies company manuals desks".split()) | {
    w for w in re.split(r"[^a-z0-9]+", Path.home().name.lower()) if w}   # your home folder name is no project
_ROOT_NAMES = None


def _journal_identity(name: str, path: str) -> set:
    """The words that say which project a journal belongs to: its name, plus its folder when that folder is not
    one of the roots (HIGH TIDE MUSIC/SOCIAL_AUTOPILOT_JOURNAL.md is a High Tide journal)."""
    global _ROOT_NAMES
    if _ROOT_NAMES is None:
        from server import _default_roots
        _ROOT_NAMES = {_fold(Path(r).name) for r in _default_roots()}
    words = re.findall(r"[a-z0-9]{3,}", _fold(Path(name).stem))
    parent = Path(path).parent.name if path else ""
    if parent and _fold(parent) not in _ROOT_NAMES:
        words += re.findall(r"[a-z0-9]{3,}", _fold(parent))
    return {w for w in words if w not in _GENERIC_ID}


def _journal_named(name: str, path: str, folded_text: str) -> bool:
    ident = _journal_identity(name, path)
    return not ident or any(re.search(r"(?<![a-z0-9])" + re.escape(w), folded_text) for w in ident)


def _project_journals() -> list:
    c = _conn()
    try:
        return c.execute("SELECT name, path FROM journals").fetchall()
    finally:
        c.close()


# The AI's own reply was never checked: the mod mapped tool calls and the owner's messages, so a method proposed in
# plain chat ("let's wire Glowcam loop", "Blender clouds") reached the owner without the journal's verdict on it
# (2026-10-26). reply_check reads the finished reply when it PROPOSES something and returns what the owner already
# said about each named thing in it, shown under the reply and given to the next turn.
_PROPOSES = re.compile(r"\b(propongo|propuesta|recomiendo|recomendaci[oó]n|le doy|lo pruebo|pruebo|probamos|probar|"
                       r"proba(?:r|mos)|vamos con|ataco|arranco|conecto|sumarlo|lo hago|i propose|i recommend|"
                       r"recommend|let'?s try|next test|i'?ll try|should we|want me to|go with)\b", re.I)


# A reply that lists something as still to do (2026-10-28 real case: "Pendiente: Shapesmith: compilarlo en la caja y
# diseñar el primer mandala vectorial") while a newer [ship] entry or a working Already-exists card says it is done.
# The verdict check only ran on replies that PROPOSE something and only knew owner verdicts, so it said nothing.
# A short lead is allowed ("Qué falta para abrirla", "What's left", 2026-10-28 real case: a header that did not START
# with "Falta" let a whole table of pending items through unchecked).
_PENDING_HEAD = re.compile(r"^(?:(?:qu[eé]|lo que|what'?s|what is|what)\s+)?"
                           r"(?:pendientes?|pending|falta|faltan|next(?: steps?)?|siguiente|pr[oó]ximos? pasos?|"
                           r"por hacer|to do|todo|queda|quedan|left|open|abiertos?|trabado|blocked|waiting|sin hacer)\b", re.I)
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}")
_PRECEDENT = re.compile(r"\b(?:(?:que es )?lo mismo que|igual que|como (?:hicimos|hice|pas[oó])|same as|like we did)\b", re.I)
_BRAND_NAMES = {n.strip().lower() for n in os.environ.get("JOURNAL_BRAND_NAMES", "").split(",") if n.strip()}
# Stores, payments, hosting, code and social platforms: in a pending line they say WHERE a thing goes ("las subo al
# sitio, a Stripe y a Gumroad"), not WHICH thing is pending. 2026-10-29 real case: three new covers waiting for the
# owner's OK were called shipped by the 10-28 Gumroad catalog sync ships, on the word "Gumroad" alone.
_PLATFORM_NAMES = set("""gumroad stripe paypal whop payhip lemonsqueezy shopify etsy amazon kdp draft2digital vercel
netlify cloudflare render supabase neon github gitlab instagram tiktok youtube facebook meta twitter threads reddit
linkedin pinterest telegram discord whatsapp gmail resend notion dropbox spotify pexels""".split())
# Words that say where a thing goes, how it moves, when, or in what state it is, never which thing it is (Spanish
# and English, compared after _stem). In the same case the shared words were "sitio", "subí" and "regla", from owner
# quotes inside the sync entries; on 2026-10-29 06:00 UTC "post" tied "Carpeta de posts y calendario" to a hand post.
_GENERIC_TOPIC = set("""site sitio web website page catalog catalogo store tienda shop library biblioteca listing
upload subi subo sube subis subimos suben subido subida publish publico publicamos publicado post posteo postear sync
push deploy send enviar envio mando release released update updated actualizar change changed cambio cambiar fix
arregle live vivo done listo rule regla owner dueno today hoy yesterday ayer tomorrow manana libraries""".split())
_PHRASE_RX = re.compile(r"\b((?:[A-Z]{2,}|[A-Z][a-z0-9]+)(?:\s+(?:[A-Z]{2,}|[A-Z][a-z0-9]+)){1,3})\b")
_DONE_HEAD = re.compile(r"^(?:hecho|hechos|done|listo|listos|shipped|terminado|completado|ya est[aá])\b", re.I)
_PENDING_LINE = re.compile(r"- \[ \]|⏳|\b(?:pendiente|falta|faltan|hay que|to build|still to|next step|"
                           r"pr[oó]ximo paso|todav[ií]a no|not built|not yet|queda por|sin hacer|por construir|"
                           r"compilarlo|construirlo|armarlo|conectarlo|instalarlo)\b", re.I)
# The line itself says the thing works ("Shapesmith ya funciona desde el 26/10"): a correction, never a pending claim.
# "ya esta restaurada", "ya quedo", "volvieron 482" report a finished thing (2026-10-28: a restored stock library line
# with "el unico que falta" in it was flagged as pending).
_LIVE_AFFIRM = re.compile(r"\b(?:ya (?:funciona|anda|existe|quedo|volvio|esta (?:en vivo|hech|andando|instalad|restaurad|"
                          r"arreglad|resuelt|list|subid|terminad|cerrad)\w*)|funciona desde|volvieron|"
                          r"en vivo desde|esta en vivo|already (?:works|live|exists|shipped|built|restored|fixed)|is live|"
                          r"live since|works since|(?:is|was|got) restored)\b")
# A name right after a use verb is the tool the pending work uses, not the pending thing ("Pattern Studio usa la
# geometria de Shapesmith", 2026-10-28): folded text.
# Trying or testing a thing uses it ("probar Clipgen 1.5 pro en esta foto", 2026-10-28: flagged against the 10-16
# ship that made it the default model).
_USE_VERB = re.compile(r"\b(?:usa|usan|usar|usando|use|uses|using|con|with|via|desde|from|probar|probarlo|probamos|"
                       r"pruebo|prueba con|intento con|testear|try|trying|test|testing|run|correr)\b")
_LIVE_STATUS = re.compile(r"\b(?:working|live|done|built|shipped|installed|connected)\b", re.I)
_NAME_RX = re.compile(r"\b([A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*|[a-z]+[A-Z][A-Za-z0-9]+|[A-Z]{2,}[a-z0-9]*|[A-Z][a-z]{2,})\b")


def _pending_lines(text: str) -> list[str]:
    """Lines of a reply that say something is still to do: bullets under a "Pendiente / Next / Falta" header, or a
    line that says so itself. Lines under "Hecho / Done" and checked boxes never count."""
    out, mode = [], ""
    for raw in text.splitlines():
        ln = raw.strip()
        if ln.startswith("|"):
            # a markdown table row is an item like a bullet: keep its cells that say something, drop the "#" cell
            if _TABLE_SEP.match(ln.replace(" ", "")):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            cells = [c for c in cells if c and not re.fullmatch(r"\d+[.)]?|#", c)]
            if not cells or max(len(re.sub(r"[*_`]", "", c)) for c in cells) <= 14:
                continue  # the header row ("# | Qué | Quién")
            ln = "- " + " ".join(cells)
        bare = re.sub(r"[*#_`>]+", "", ln).strip(" :-\t")
        is_head = bool(ln) and len(bare) <= 60 and not re.match(r"(?:[-*]\s|\d+[.)]\s)", ln)
        if is_head and _PENDING_HEAD.match(bare):
            mode = "p"
            continue
        if is_head and _DONE_HEAD.match(bare):
            mode = "d"
            continue
        if not ln or re.match(r"[-*]\s*\[[xX]\]", ln):
            continue
        bullet = bool(re.match(r"(?:[-*]|\d+[.)])\s", ln))
        if (mode == "p" and bullet) or (mode != "d" and _PENDING_LINE.search(ln)):
            out.append(ln)
    return out


_NEGATED = re.compile(r"\bnot\b|\bno\b|\bnever\b|\bwithout\b|\bpending\b")


def _last_not_done(group: list) -> str:
    """When the journals last said the thing is NOT done: a dated non-ship entry whose sentence naming it says
    not built / pending / not yet ([todo] and [plan] entries count whole). "" when none."""
    rx = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in group) + r")")
    c = _conn()
    try:
        rows = c.execute("SELECT heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 2000",
                         (_fts_or(group),)).fetchall()
    except Exception:
        return ""
    finally:
        c.close()
    best = ""
    for heading, body in rows:
        m = _HEAD_DATE.match(heading or "")
        if not m or _is_ship_heading(heading):
            continue
        when = m.group(1) + " " + (m.group(2) or "00:00")
        if when <= best:
            continue
        title = _HEAD_DATE.sub("", heading or "")
        todo = re.match(r"\s*\[(?:todo|plan|pending|bug)\]", title, re.I) and rx.search(_fold(title))
        if todo or any(rx.search(_fold(x)) and _near(_NOT_DONE, rx, _fold(x), 80)
                       for x in re.split(r"(?<=[.!?;])\s+|\n+", title + "\n" + (body or ""))):
            best = when
    return best


def _entry_stems(sh: dict) -> set:
    """The title and the sentences of a ship entry that name the thing: the rest of a long entry is other work."""
    return _english_stems(sh.get("ctx") or (sh["entry"] + " " + sh["said"]))


def _session_folders(call: dict, folded_reply: str) -> set:
    """The project folders this session works in: folders of the journals it read, plus journals the reply names.
    Empty when the session read nothing (no scope: every journal counts). 2026-10-28: a Dreamfield reply about the
    restored Pexels stock library was told a Pexels ship of the content agency's coffee shops made it wrong."""
    seen = {}
    if call.get("session_id"):
        try:
            seen = _quick_seen(str(call["session_id"]))[1]
        except Exception:
            seen = {}
    read = set(seen.get("jr") or {}) | set(seen.get("jt") or {})
    if not read:
        return set()
    out = set()
    for name, path in _project_journals():
        if _jkey(name) in read or (_journal_identity(name, path) and _journal_named(name, path, folded_reply)):
            out.add(_fold(str(Path(path).parent)))
    return out


def _shipped_vs_pending(text: str, folders: set = None) -> list[str]:
    lines, warned = [], set()
    for pl in _pending_lines(text)[:12]:
        body = re.sub(r"`[^`]*`|\S*[\\/]\S*|https?://\S+", " ", pl)
        # "**Buyers copy:** port ... the journals mod": the label says WHAT is pending; names after it are context.
        # up to 80 chars: a 52-char label ("Pasar a la cuenta nueva a los que ya están corriendo") failed the match,
        # the whole line became the subject and "Owner Proxy" in its detail was flagged as shipped (2026-10-29)
        lab = re.match(r"^[^\w*]*(?:\[ \]\s*)?[^\w*]*\**([^:*\n]{2,80}?)\**\s*:", body)
        subject = lab.group(1) if lab else body
        # "..., que es lo mismo que hicimos con Launch Desk" names a precedent, not a pending thing (2026-10-28)
        subject = _PRECEDENT.split(subject)[0]
        names, parts = [], set()
        # A product name of several capitalised words ("MIDI Tools", "Sound Healing Room") is ONE name: split into
        # words, "MIDI" alone matched the 82-release catalog card and missed the MIDI Tools ship (2026-10-28).
        for m in _PHRASE_RX.finditer(subject):
            fp = _fold(m.group(1))
            if fp in _BRAND_NAMES:
                parts |= set(fp.split())   # a company name is context, never the pending thing ("Tone Garden")
                continue
            if fp not in warned and fp not in _CHAT_WORDS:
                names.append((fp, True))
                parts |= set(fp.split())
        for m in _NAME_RX.finditer(subject):
            w = m.group(1)
            fw = _fold(w)
            # a capitalised first word ("Primer post automático ...") is a common word, not a name (2026-10-29:
            # "primer" matched an Growvine X ship whose title ends in "Primer")
            if fw in parts or fw in _STOP or fw in _CHAT_WORDS or fw in _GENERIC_REPLY or fw in warned or \
                    len(fw) < 3 or any(fw == n for n, _ in names):
                continue
            names.append((fw, any(ch.isupper() for ch in w[1:])))
        for e in _entities_in(subject):
            # A company found as an entity is context too: it came back here as a "sure" name and matched ships and
            # cards of the company itself ("Launch Desk" first post, "Tone Garden catalog" card, 2026-10-29).
            if e["name"] in _BRAND_NAMES or e.get("kind") == "company":
                continue
            if e["name"] not in warned and all(e["name"] != n for n, _ in names):
                names.append((e["name"], True))
        # Every name in the line (also outside the label) is a name, never a shared topic word ("Shopsite").
        all_names = {_fold(m.group(1)) for m in _NAME_RX.finditer(body)} | {e["name"] for e in _entities_in(body)}
        name_stems = {_stem(p) for n in all_names | {n for n, _ in names} for p in n.split()}
        topic = _english_stems(body) - name_stems
        generic = {_stem(w) for w in _GENERIC_TOPIC}
        for name, sure in names[:4]:
            # a platform is where the thing goes: its ships prove nothing about this item unless they share the item's
            # own words (below), and its Already-exists card ("Gumroad MCP: working") is never this item
            weak = name in _PLATFORM_NAMES
            g = [t for t in _expand_terms(name) if re.fullmatch(r"[a-z0-9_]+", t)] or [name]
            hits = []
            nrx = re.compile(r"(?<![a-z0-9])" + re.escape(name).replace(r"\ ", r"[\s-]+"))
            fl = _fold(pl)
            if _near(_LIVE_AFFIRM, nrx, fl, 80) or _near(nrx, _USE_VERB, _fold(subject), 30, after=True):
                continue
            if " " in name:
                # a several-word name: every word must be in the entry, and the entry must name the whole phrase
                ships = [s for s in shipped_about([[w] for w in name.split()], cap=8)
                         if nrx.search(_fold(s.get("ctx") or ""))][:3]
            else:
                ships = shipped_about([g], cap=3)
            # Only a ship NEWER than the last entry that says the thing is still not done counts: "Webweave fix
            # pending" of 10-26 outlives the "Box employees get Webweave" ship of 10-24.
            last_open = _last_not_done([name] if " " in name else g) if ships else ""
            for sh in ships:
                if sh["when"] <= last_open or _near(_NEGATED, nrx, _fold(sh.get("ctx") or ""), 40, after=True):
                    continue   # older than an open claim, or the ship itself says this thing is not done
                if folders and _fold(str(Path(sh.get("path") or "").parent)) not in folders:
                    continue   # another project's ship of a thing with the same name
                ov = topic & _entry_stems(sh)
                # A distinctive name (Shapesmith, MIDI Tools) is the subject itself: one shared word confirms it.
                # A plain or platform name needs the ship to share 2 of the item's OWN words, never only where it
                # goes, how it moves or when ("sitio", "subí", "post", "hoy").
                own = ov - generic
                in_title = nrx.search(_fold(sh["entry"]))
                if (sure and not weak and ov) or (in_title and len(own) >= 2):
                    hits.append(sh)
            cards = []
            if sure and not weak:
                for x in _match_capabilities(name, limit=4, min_cover=1):
                    # the card must be ABOUT the name (its first words), not mention it in a list: "Google Ads from
                    # the AI ...: reports, YouTube video campaigns" is not a YouTube upload (2026-10-28)
                    head = " ".join(_fold(x.get("what") or "").split()[:5])
                    if re.search(r"(?<![a-z0-9])" + re.escape(name), head) and _LIVE_STATUS.search(x.get("status") or ""):
                        cards.append(x)
            if not hits and not cards:
                continue
            warned.add(name)
            said = re.sub(r"^[-*]\s*(?:\[ \]\s*)?", "", pl)[:140]
            for sh in hits[:2]:
                extra = "" if _fold(sh["said"])[:60] in _fold(sh["entry"]) else f" | {sh['said'][:150]}"
                lines.append(f"- {name}: you listed it as still to do (\"{said}\"), but {sh['journal']}:{sh['line']} "
                             f"({sh['when']}) says it shipped: {sh['entry'][:110]}{extra}")
            for x in cards[:1]:
                lines.append(f"- {name}: you listed it as still to do, but the Already-exists card says "
                             f"[{(x.get('status') or '')[:60]}]: {(x.get('what') or '')[:160]} ({x.get('journal')})")
        if len(lines) >= 4:
            break
    return lines


_TIME_WORDS = {"utc", "gmt"}
# "Y uses X", "runs on Y", "shared with Y": a statement of what runs where, in Spanish or English.
_USE_CLAIM = re.compile(r"(?<![a-z])(?:usa|usan|usando|uses|used|using|corre|corren|corriendo|runs|running|"
                        r"comparte|comparten|compartida|compartido|compartir|shared|shares|vive|viven|lives|holds)(?![a-z])")
# A thing switched off: strong words only ("stopped" alone is everyday brake talk).
_SHUT = re.compile(r"(?<![a-z])(?:shut ?down|shutdown|turned off|switched off|apagad[oa]s?|apagamos|apague|apagaste|"
                   r"no longer (?:runs|running|used)|decommission\w*|is off|off now|off since|kept running)(?![a-z])")


def _shutdown_claims(text: str, days: int = 10) -> list[str]:
    """The reply says something uses or runs on a name, and a dated entry of the last `days` days, in any journal,
    says that name was shut down or turned off. Real case 2026-10-29: the reply said vpsone uses mainacct and
    shares its week, while FREELANCE_ENGINE_JOURNAL_USER had said 4 hours earlier that vpsone was shut down."""
    from datetime import datetime, timedelta
    # A quoted sentence is an example or a citation, not a claim (2026-10-29: the reply that described this very check
    # quoted "Vpsone ya usa mainacct" and was flagged).
    plain = re.sub(r"`[^`]*`|https?://\S+|\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”", " ", text)
    folded = _fold(plain)
    # Only names count: capitalised in the reply, an identifier (digit, dash, underscore) or a known entity;
    # "chequeo" next to "corre" is a common word (2026-10-29).
    named = {_fold(w) for w in re.findall(r"\b([A-Z][A-Za-z0-9]{3,}|[a-z]+[A-Z][A-Za-z0-9]+)\b", plain)}
    named |= {e["name"] for e in _entities_in(plain)}
    words = []
    for m in _USE_CLAIM.finditer(folded):
        win = folded[max(0, m.start() - 30): m.end() + 30]
        for w in re.findall(r"(?<![a-z0-9_-])([a-z][a-z0-9_-]{3,})(?![a-z0-9_-])", win):
            if not (w in named or re.search(r"[0-9_-]", w)):
                continue
            if (w not in _STOP and w not in _CHAT_WORDS and w not in _GENERIC_REPLY and w not in _TIME_WORDS
                    and not _USE_CLAIM.fullmatch(w) and w not in words):
                words.append(w)
    if not words:
        return []
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    c = _conn()
    try:
        names = dict(c.execute("SELECT path, name FROM journals").fetchall())
        for w in words[:8]:
            wrx = re.compile(r"(?<![a-z0-9_-])" + re.escape(w) + r"(?![a-z0-9_])")
            rows = c.execute("SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 300",
                             (f'"{w}"',)).fetchall()
            best = []
            for path, line, heading, body in rows:
                hm = _HEAD_DATE.match(heading or "")
                if not hm or hm.group(1) < since:
                    continue
                for snt in re.split(r"(?<=[.!?;])\s+|\n+", _HEAD_DATE.sub("", heading or "") + ".\n" + (body or "")):
                    # the name is the subject ("vpsone kept running", "vpsone was shut down"); a quote inside an
                    # entry ("a session said ...") is not the entry's own statement
                    if re.search(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_JOURNAL\w*", snt):
                        continue   # it names another journal: that entry is the fact, this one a reference
                    fs = _fold(re.sub(r"\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”", " ", snt))
                    if wrx.search(fs) and _near(_SHUT, wrx, fs, 50, after=True):
                        best.append((hm.group(1) + " " + (hm.group(2) or "00:00"), names.get(path, Path(path).name),
                                     int(line), snt.strip()[:200]))
                        break
            for when, j, ln, snt in sorted(best, reverse=True)[:1]:
                out.append(f"- {w}: your reply says something uses or runs on it, but {j}:{ln} ({when}) says: {snt}")
            if len(out) >= 3:
                break
    except Exception:
        pass
    finally:
        c.close()
    return out


def reply_check(call: dict) -> None:
    text = str(call.get("reply") or "")[:8000]
    if len(text) < 40:
        return
    try:
        c = _conn()
        try:
            _sync_changed(c)
        finally:
            c.close()
    except Exception:
        pass
    try:
        folders = _session_folders(call, _fold(text))
    except Exception:
        folders = set()
    shipped = _shipped_vs_pending(text, folders)
    verdicts = _verdict_lines(text) if _PROPOSES.search(text) else []
    try:
        claims = _shutdown_claims(text)
    except Exception:
        claims = []
    parts = []
    if claims:
        parts.append("CHECK THIS CLAIM IN YOUR LAST REPLY: you said something uses or runs on these, and a recent entry "
                     "says it was shut down or turned off. Re-read that entry and, if your claim was stale, correct it "
                     "for the owner before anything else:\n" + "\n".join(claims))
    if shipped:
        parts.append("WRONG IN YOUR LAST REPLY: you told the owner something is still pending that the journals say "
                     "already shipped. Correct it in your next reply, before anything else, and update that journal's "
                     "Current state / Handoff:\n" + "\n".join(shipped))
    if verdicts:
        parts.append("JOURNAL CHECK ON THE LAST REPLY (it proposed things the journals already have a word on; do not "
                     "present them as new, start from what was said):\n" + "\n".join(verdicts))
    if parts:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": "\n\n".join(parts)}}, ensure_ascii=False))


# What a command RETURNED names things too (2026-10-28: a box `systemctl --failed` listed starpair-drip,
# clip-farm and xvfb-game; the owner had said on 2026-10-23 "these are NOT outages to report" and the session
# reported them anyway: the mod mapped only the command it was about to run, never what came back).
# Identifiers only (a dash or underscore inside: unit, script, folder, session names); plain words are chat noise.
_OUT_ID = re.compile(r"(?<![\w-])([a-z][a-z0-9]*(?:[-_][a-z0-9]+){1,4})(?![\w-])")


_GIT_STATE_CMD = re.compile(r"\bgit\b[^\n|;&]*\b(status|diff)\b")
_GIT_MODIFIED = re.compile(r"^\s?M[ M]?\s+\S|^\s*modified:\s+\S|\|\s+\d+\s+[+-]+", re.M)


def git_eol_check(call: dict, shown: set) -> set:
    """A git status/diff that lists modified files: says how many differ ONLY by line endings (CRLF), once per
    repo per session. Real case 2026-10-28: 82 'modified' site files were reported to the owner as other sessions'
    unpublished work; with --ignore-cr-at-eol they were identical to the commit."""
    ti = call.get("tool_input") or {}
    cmd = str(ti.get("command") or "")
    out = str(call.get("output") or "")
    if not _GIT_STATE_CMD.search(cmd) or len(_GIT_MODIFIED.findall(out)) < 3:
        return set()
    m = re.search(r"""git\s+-C\s+(?:"([^"]+)"|'([^']+)'|(\S+))""", cmd) or re.search(r"""\bcd\s+(?:"([^"]+)"|'([^']+)'|(\S+))""", cmd)
    repo = next((g for g in (m.groups() if m else ()) if g), None) or str(call.get("cwd") or "")
    if re.match(r"^/[a-z]/", repo):  # Git Bash path on Windows
        repo = repo[1].upper() + ":" + repo[2:]
    key = "git-eol:" + repo
    if not repo or key in shown:
        return set()
    try:
        base = ["git", "-C", repo, "-c", "core.autocrlf=false", "diff"]
        # stdin=DEVNULL: with no valid stdin (pytest capture, some hook launches) Windows raised "handle is invalid"
        # and the check went silent about 1 run in 3 (2026-10-29)
        r = subprocess.run(base + ["--name-only"], capture_output=True, text=True, timeout=8,
                           stdin=subprocess.DEVNULL)
        allm = [x for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else None
        # Older git (2.43 on the box) still lists line-ending-only files under --name-only even with
        # --ignore-cr-at-eol: read the patch instead and count a file as really changed only if it has a hunk.
        p = subprocess.run(base + ["--ignore-cr-at-eol", "--no-color"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           timeout=15, encoding="utf-8", errors="replace")
        real = None
        if p.returncode == 0:
            real = []
            for blk in p.stdout.split("diff --git ")[1:]:
                if "\n@@" in blk:
                    real.append(blk.split("\n", 1)[0].split(" b/", 1)[-1].strip())
    except Exception:
        return set()
    if not allm or real is None:
        return set()
    eol = len(allm) - len(real)
    if eol < 3:
        return set()
    shown_real = ", ".join(real[:8]) + (" ..." if len(real) > 8 else "") if real else "none"
    print(f"GIT CHECK ({repo}): {eol} of {len(allm)} modified files differ ONLY by line endings (CRLF), "
          f"their content equals the commit. Real changes: {len(real)} ({shown_real}). Never report the "
          f"line-ending ones as unpublished work; `git checkout -- <file>` restores them.")
    return {key}


def output_check(call: dict, shown: set) -> set:
    """Prints the owner's verdicts on identifiers named in a command's output, once per session per name."""
    text = _fold(str(call.get("output") or "")[-60000:])
    ids = []
    for m in _OUT_ID.finditer(text):
        t = m.group(1)
        parts = re.split(r"[-_]", t)
        if t in shown or t in ids or len(t) < 6 or sum(ch.isdigit() for ch in t) * 3 > len(t):
            continue
        if not any(len(p) >= 4 and not re.fullmatch(r"[0-9a-f]+", p) for p in parts):
            continue
        ids.append(t)
        if len(ids) >= 40:
            break
    if not ids:
        return set()
    try:
        c = _conn()
        try:
            _sync_changed(c)
        finally:
            c.close()
    except Exception:
        pass
    found, hit = {}, set()   # one line per verdict, listing every name it covers ("these are NOT outages" = 3 units)
    for t in ids:
        words = [p for p in re.split(r"[-_]", t) if p]
        phrase = '"' + " ".join(words) + '"'
        # The name must be written AS IS (dash or underscore kept) in the verdict sentence or the entry's title:
        # FTS splits "owner_orders" into two common words that match any owner sentence (2026-10-28 noise test).
        # The sentence right before or after counts too ("Seen down: a, b. Owner correction: these are NOT outages").
        try:
            c = _conn()
            try:
                ents = {(p, int(ln)): (_fold(h or ""), [_fold(s) for s in re.split(r"(?<=[.!?])\s+|\n+", b or "")])
                        for p, ln, h, b in c.execute(
                            "SELECT path, line, heading, body FROM entries_fts WHERE entries_fts MATCH ? LIMIT 300",
                            (f"({phrase}) AND {_VERDICT_FTS}",)).fetchall()}
            finally:
                c.close()
        except Exception:
            ents = {}
        lit = re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])")

        def named(v) -> bool:
            head, sents = ents.get((v["path"], int(v["line"])), ("", []))
            if lit.search(head) or lit.search(_fold(v["said"])):
                return True
            key = _fold(v["said"])[:40]
            i = next((k for k, s in enumerate(sents) if key and key in s), -1)
            return i >= 0 and any(lit.search(s) for s in sents[max(0, i - 1):i + 2])
        vs = [v for v in _verdicts(phrase, words, cap=3) if v.get("owner") and named(v)]
        for v in vs[:2]:
            if v["said"] not in found and len(found) >= 6:
                continue
            found.setdefault(v["said"], [[], v])[0].append(t)
            hit.add(t)
    lines = [f"- {', '.join(names)}: the owner already said ({v['when']}, {v['journal']}:{v['line']}): {s}"
             for s, (names, v) in found.items()]
    if lines:
        print(json.dumps({"hookSpecificOutput": {"additionalContext":
              "WHAT THIS COMMAND RETURNED names things the owner already ruled on. Read those entries before you "
              "report or act on them:\n" + "\n".join(lines)}}, ensure_ascii=False))
    return hit


def _verdict_lines(text: str) -> list[str]:
    body = re.sub(r"`[^`]*`|\S*[\\/]\S*|https?://\S+", " ", text)
    cands = []
    # Capitalized or mixed-case words that do not open a sentence or a list line name things (Glowcam, Blender, Veo).
    # A word right after "**" opens a bold label ("- **Mapa rápido:**"), not a thing (2026-10-28: "mapa" pulled a
    # July Dreamfield loop insight into a reply about the journals mod).
    for m in re.finditer(r"(?<![.!?:¿¡\n*#|-]\s)(?<!^)(?<!\*)\b([A-Z][a-zA-Z0-9]{2,}|[a-z]+[A-Z][A-Za-z0-9]+)\b", body):
        w = _fold(m.group(1))
        if (w not in _STOP and w not in _CHAT_WORDS and w not in cands and len(w) >= 3 and w not in _TIME_WORDS
                and not any(w in b.split() for b in _BRAND_NAMES)):
            cands.append(w)
    for e in _entities_in(body):
        # a company name is context, never the thing proposed (same rule as the pending check)
        if e["name"] not in cands and e["name"] not in _BRAND_NAMES and e.get("kind") != "company":
            cands.append(e["name"])
    # A journal named by its full name ("Content Agency") is a reference, its words are not things the reply
    # proposes (2026-10-28: "contenido" pulled an old content-agency quote into a reply about the journals mod).
    folded0 = _fold(body)
    ref = set()
    for j, p in _project_journals():
        ws = [w for w in re.findall(r"[a-z0-9]{3,}", _fold(Path(j).stem)) if w not in _GENERIC_ID]
        if len(ws) >= 2 and re.search(r"(?<![a-z0-9])" + r"[\s_-]+".join(map(re.escape, ws)), folded0):
            ref |= set(ws)
    cands = [c for c in cands if c not in ref]
    # What the reply is about ("nubes", "loop", "foto") ranks a thing's verdicts: Blender verdicts on mandala
    # geometry are not the answer to "Blender clouds" (2026-10-26 replay).
    # Names (brands, tools) are not a shared topic: "tone garden" in the reply and in an BOLTLAB widget verdict
    # made that verdict look on-topic (2026-10-27 replay, Instagram map for Mapleworks).
    names = {_stem(p) for c in cands for p in c.split()}
    about = ({_stem(w) for w in re.findall(r"[a-z]{4,}", _fold(_to_english(body)))}
             - {_stem(w) for w in _STOP | _CHAT_WORDS | _GENERIC_REPLY} - names)
    folded = _fold(body)
    named_project = any(_journal_named(j, p, folded) for j, p in _project_journals())
    lines, seen = [], set()
    for w in cands[:10]:
        g = [t for t in _expand_terms(w) if re.fullmatch(r"[a-z0-9_]+", t)] or [w]
        vs = [v for v in _verdicts(_fts_or(g), g, cap=8) if v.get("owner") and v["said"] not in seen]
        ov = lambda v: len({_stem(x) for x in re.findall(r"[a-z]{4,}", _fold(_to_english(v["said"])))} & about)
        # A verdict from another project's journal (High Tide reels in a Mapleworks reply) is noise once the
        # reply names a project; every verdict also needs a real topic word in common, not just a shared name.
        vs = [v for v in vs if ov(v) >= 1 and (not named_project or _journal_named(v["journal"], v["path"], folded))]
        for v in sorted(vs, key=ov, reverse=True)[:2]:
            seen.add(v["said"])
            lines.append(f"- {w}: the owner already said ({v['when']}, {v['journal']}:{v['line']}): {v['said']}")
        if len(lines) >= 4:
            break
    return lines


def quick_map(query: str, limit: int = 5, cards: bool = True, context: str = "") -> dict:
    """cards=False skips the decided/exists/pending cards (the slow part: ~0.4 s of capability parsing); the edit
    hook asks first without them and builds them only for a file that maps to a piece or its own journal.
    context: the rest of the message the query word came from; it ranks the named thing's cards and plans."""
    terms = _quick_terms(query)
    all_terms = list(terms)
    if not terms:
        return {"query": query, "terms": []}
    c = _conn()
    try:
        if c.execute("SELECT COUNT(*) FROM entries_meta").fetchone()[0] == 0:   # first run: index BEFORE the Brain map is read
            _index_refresh_internal()
        else:
            _sync_changed(c)
    finally:
        c.close()
    pieces = _map_rows(query, terms)
    c = _conn()
    try:
        if len(terms) > 1:
            # "localmodel_probe.py": search by the word that names the piece, or else the word with most entries,
            # not by every word together (which only finds loose matches).
            keyed = [t for t in terms if any(t in _fold(p.get("piece", "") + " " + p.get("path", "")) or
                                             t in p.get("keys", []) for p in pieces)]
            if keyed:
                terms = keyed[:1]
            else:
                hits = {t: c.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?", (_fts_or([t]),)).fetchone()[0]
                        for t in terms}
                together = c.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?",
                                     (" AND ".join(_fts_or([t]) for t in terms),)).fetchone()[0]
                if together < 3:
                    # A word that names a journal wins (haven -> HAVEN_SYNTH_JOURNAL), then the most
                    # specific word that still has a few entries, then whatever has any.
                    jn = " ".join(_fold(n) for n in names_all(c))
                    named_t = [t for t in terms if t in jn and hits[t]]
                    rare = [t for t in terms if hits[t] >= 3]
                    terms = named_t[:1] or ([min(rare, key=hits.get)] if rare else [max(hits, key=hits.get)])
        groups = [[t for t in _expand_terms(w) if re.fullmatch(r"[a-z0-9_]+", t)] or [w] for w in terms]
        expr = " AND ".join(_fts_or(g) for g in groups)
        names = {p: n for p, n in c.execute("SELECT path, name FROM journals").fetchall()}
        rows = c.execute("SELECT path, line, heading FROM entries_fts WHERE entries_fts MATCH ? LIMIT 4000",
                         (expr,)).fetchall()
        # Entries whose TITLE carries the word are about it (2026-10-25: "codex" had a decision entry titled
        # "CODEX (Model-X) JUNTO A CLAUDE CODE" but no journal named after it, so the map was dropped).
        head_rows = c.execute("SELECT path, line, heading FROM entries_fts WHERE entries_fts MATCH ? LIMIT 400",
                              (" AND ".join("heading : " + _fts_or(g) for g in groups),)).fetchall()
    finally:
        c.close()
    word_in = lambda h: all(any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", _fold(h)) for t in g)
                            for g in groups)
    about = []
    for path, line, heading in head_rows:
        m = _HEAD_DATE.match(heading or "")
        if m and word_in(heading):
            about.append((("[decision]" in (heading or "").lower(), m.group(1) + " " + (m.group(2) or "00:00")),
                          path, int(line), heading))
    about.sort(reverse=True)
    per_path: dict[str, int] = {}
    dated = []
    for path, line, heading in rows:
        per_path[path] = per_path.get(path, 0) + 1
        m = _HEAD_DATE.match(heading or "")
        if m:
            dated.append((m.group(1) + " " + (m.group(2) or "00:00"), path, int(line), heading))
    is_manual = lambda p: "/manuals/" in p.replace("\\", "/").lower()
    named = lambda p: any(t in _name_words(names.get(p, "")) for t in terms)  # LOCALMODEL_JOURNAL.md is the home of "localmodel"
    home = sorted(((n, p) for p, n in per_path.items() if not is_manual(p)),
                  key=lambda x: (named(x[1]), x[0]), reverse=True)[:3]
    dated.sort(reverse=True)
    latest = [{"when": d, "journal": names.get(p, Path(p).name), "line": ln, "entry": h[:140]}
              for d, p, ln, h in dated[:limit]]
    words = " ".join(terms)
    # Cards only from the topic's own journals or the map's: "brake" must not pull a checkout rule.
    near = {names.get(p, Path(p).name) for _, p in home} | {Path(o.get("path", "")).name for o in pieces}
    near |= {w for o in pieces for w in re.findall(r"[\w.-]+_JOURNAL\.md", o.get("path", ""))}
    # A word that names a journal (quality -> QUALITY_CONTROL_JOURNAL) takes its cards from that journal only.
    home_named = {names.get(p, Path(p).name) for _, p in home if named(p)}
    near_exists = near
    if home_named and not pieces:
        near = home_named
        latest = [x for x in latest if x["journal"] in near]
    # A file name is specific: a concept card that only shares its stem (credit.json -> "credit pacing") is noise.
    # A command line ("/data/x/generar.py --pid 1") names its file in ONE token: taking everything after the
    # last slash kept the arguments and hid every decision about the file (2026-10-25, dogfood rule missed).
    tok = _file_token(query)
    is_file = bool(tok)
    fname = _fold(Path(tok.replace("\\", "/")).name) if is_file else ""
    has_name = lambda x: fname in _fold(x.get("what") or "")
    if is_file and pieces:  # a file of a mapped piece: lines come from that piece's journals, not from every journal using the stem
        latest = [x for x in latest if x["journal"] in near]
        home = [(n, p) for n, p in home if names.get(p, Path(p).name) in near] or home
    decided, exists, pending = [], [], []
    if cards:
        decided = [{"what": x.get("what"), "journal": x.get("journal"), "date": x.get("date")}
                   for x in _match_capabilities(words, limit=8, min_cover=len(terms), sections=_SEC_DECIDED)
                   if x.get("journal") in near and (not is_file or has_name(x))][:3]
        exists = [{"what": x.get("what"), "status": x.get("status"), "journal": x.get("journal"), "see": x.get("see")}
                  for x in _match_capabilities(words, limit=8, min_cover=len(terms)) if x.get("journal") in near_exists][:3]
    ents, plans, entity_about = [], [], []
    if cards:
        # Named things: in a file path only a company folder or the file's own words name one ("C:/Users/..."
        # would name anything); in text, the whole query plus the message it came from.
        # Named things come from the mapped word only; the rest of the message (context) only ranks. Taking them
        # from the context put "shopsite" (named once in a message) into the map of every chat word of it
        # ("pertenencia", "probado", "tiempos"), all with the same cards (2026-10-26 regression).
        gtext = " ".join(all_terms) if is_file else query
        ents = _entities_in(gtext)
        if is_file:
            ents += [e for e in _entities_in(query.replace(chr(92), "/").replace("/", " / "), kinds=("company",))
                     if all(e["name"] != x["name"] for x in ents)]
        qgroups = _query_groups(gtext + " " + context, ents)
        plans = _open_plans(qgroups, ents)
        if ents:
            ea = _entity_about(ents, qgroups)
            about = [x for x in about if all(x[2] != y["line"] or names.get(x[1]) != y["journal"] for y in ea)]
            entity_about = ea
            ed, ee = _entity_cards(ents, qgroups)
            merge = lambda a, b, n: list({x["what"]: x for x in a + b}.values())[:n]
            # A query that names something shows that thing's own cards only; the loose word matches of the older
            # path brought cards that merely mention it (2026-10-26).
            decided = merge(decided, ed, 3) if is_file else (ed or decided)[:3]
            exists = merge(exists, ee, 3) if is_file else (ee or exists)[:3]
    for p in ([p for _, p in home] if cards else []):
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ln in text.splitlines():
            s = ln.strip()
            if (s.startswith("- [ ]") or s.lower().startswith("next:")) and any(t in _fold(s) for g in groups for t in g):
                pending.append({"journal": names.get(p, Path(p).name), "item": s[:180]})
                if len(pending) >= 4:
                    break
        if len(pending) >= 4:
            break
    verdicts = _verdicts(expr, [t for g in groups for t in g], near=near | home_named)
    nb = newer_about(tok) if is_file else {}
    # Ship entries of the word in ANY journal, newest first; older "not built / pending" lines get marked.
    shipped = shipped_about(groups) if not is_file else []
    newest = shipped[0] if shipped else {}
    stale_marks, stale_state = {}, []
    if newest:
        tag = f"newer ship {newest['when']} in {newest['journal']}:{newest['line']}"
        ship_keys = {(s["journal"], s["line"]) for s in shipped}
        latest = [x for x in latest if (x["journal"], x["line"]) not in ship_keys]
        rx_w = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for g in groups for t in g) + r")")
        not_done_near = lambda t: _near(_NOT_DONE, rx_w, _fold(t or ""), 80)
        for x in latest + [{"when": k[1], "journal": names.get(p, Path(p).name), "line": ln, "entry": h}
                           for k, p, ln, h in about]:
            if x["when"] < newest["when"] and not_done_near(x.get("entry")):
                stale_marks[f"{x['journal']}:{x['line']}"] = tag
        for p in plans:
            if str(p.get("date") or "") < newest["when"] and not_done_near(p.get("plan")):
                stale_marks[f"{p['journal']}:{p['line']}"] = tag
        # A pending item is marked only when ONE ship entry shares two of its topic words ("connect", "path layer").
        word_stems = {_stem(t) for g in groups for t in g}
        for p in pending:
            item = _english_stems(p["item"]) - word_stems
            hit = next((s for s in shipped if len(item & _english_stems(s["entry"] + " " + s["said"])) >= 2), None)
            if hit:
                p["stale"] = f"newer ship {hit['when']} in {hit['journal']}:{hit['line']}"
    rx_t = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for g in groups for t in g) + r")")
    homes = {p for _, p in home}
    for p in (sorted(homes | {s["path"] for s in shipped}) if cards and not is_file else ()):
        try:
            line = _stale_state_lines(p, Path(p).read_text(encoding="utf-8", errors="replace"), rx_t, newest,
                                      own=p in homes)
        except Exception:
            line = ""
        if line and line not in stale_state:
            stale_state.append(line)
    return {"query": query, "terms": terms, "pieces": pieces[:2], "verdicts": verdicts, "newer": nb,
            "shipped": [{k: v for k, v in s.items() if k not in ("path", "ctx")} for s in shipped],
            "stale_marks": stale_marks, "stale_state": stale_state[:2],
            "journals": [{"journal": names.get(p, Path(p).name), "entries": n, "path": p} for n, p in home],
            "about": (entity_about + [{"when": k[1], "journal": names.get(p, Path(p).name), "line": ln, "entry": h[:160]}
                                      for k, p, ln, h in about])[:3],
            "vault": [dict(r, latest=_vault_latest(r.get("name", ""))) for r in _vault_rows(terms)],
            "decided": decided, "exists": exists, "latest": latest, "pending": pending,
            "entities": [e["name"] for e in ents], "plans": plans}


def _handoff_behind(m: dict) -> str:
    """2026-10-28: "seguimos con la sesión de Dreamfield" got a map of 10-17 ships and 10-18 plans, while
    DREAMFIELD_JOURNAL's Handoff was 20 entries behind the day's real work. When the word names a project's journal,
    the map says whether that Handoff is behind and lists what came after it."""
    try:
        from server import _SEC_HANDOFF, _SEC_PENDING, _behind_note
    except ImportError:
        return ""
    terms = [_fold(t) for t in m.get("terms") or []]
    for j in (m.get("journals") or [])[:3]:
        # the word must BE the project's own name ("dreamfield"), never a generic word inside it ("mcp" matched
        # MCP_USO_EN_PC_JOURNAL on every MCP command, 2026-10-28)
        if not set(terms) & _journal_identity(j["journal"], j.get("path") or ""):
            continue
        try:
            content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sec = _find_section(content, _SEC_PENDING) or _find_section(content, _SEC_HANDOFF)
        note = _behind_note(content, sec[1], cap=8) if sec else ""
        if note:
            return f"- IN {j['journal']}: " + note.lstrip("> ").rstrip()
    return ""


def quick_map_text(m: dict) -> str:
    if not m.get("terms") or not (m.get("pieces") or m.get("journals") or m.get("latest") or m.get("vault")
                                  or m.get("plans") or m.get("decided") or m.get("verdicts") or m.get("newer")
                                  or m.get("shipped")):
        return ""
    L = [f"JOURNAL QUICK MAP for \"{' '.join(m['terms'])}\":"]
    hb = _handoff_behind(m)
    if hb:
        L.append(hb)
    nb = m.get("newer") or {}
    stale = {}
    if nb:
        L.append(newer_text(nb, m.get("query") or ""))
        stale = {(nb["claim"]["journal"], nb["claim"]["line"]): f"{nb['newer'][0]['journal']}:{nb['newer'][0]['line']}"}
    marks = m.get("stale_marks") or {}
    vkeys = tuple(v.get("name", "") for v in m.get("vault") or [] if v.get("name"))
    fired = []
    def st(text: str, keys: tuple = vkeys, how: str = "", claim: str = "", key: str = "") -> str:
        h = _state_hint(text, keys, how, key)
        if not h:
            return ""
        fired.append(h)
        said = f" in that entry: \"{claim}\"" if claim else ""
        return f" [STATE{said}: check live before repeating it; how: {h}]"
    def mark(e: dict) -> str:
        k = (e.get("journal"), e.get("line"))
        if k in stale:
            return f" (may be stale, newer: {stale[k]})"
        k2 = f"{k[0]}:{k[1]}"
        return f" (MAY BE STALE: {marks[k2]})" if k2 in marks else ""
    # What shipped comes first: a re-shown (short) map keeps these lines.
    for x in (m.get("shipped") or [])[:2]:
        said = "" if _fold(x["said"])[:60] in _fold(x["entry"]) else f" | {x['said'][:160]}"
        L.append(f"- SHIPPED {x['when']} ({x['journal']}:{x['line']}): {x['entry'][:110]}{said}"
                 + st(x["entry"] + " | " + x["said"]))
    for ln in m.get("stale_state") or []:
        L.append(ln)
    for o in m.get("pieces", []):
        L.append(f"- PIECE: {o['piece']}. Read first: {o['path']}. Working on it now: {o.get('now') or 'nobody noted'}"
                 + (f". {o['notes']}" if o.get("notes") else "") + ".")
    for v in m.get("vault", []):
        L.append(f"- VAULT: entry '{v['name']}' [{v.get('category') or '?'}] fields {', '.join(v.get('fields', [])[:8])}: "
                 "it already exists: use it (search_credentials / get_credential) before asking anyone for a new key.")
        for x in v.get("latest", []):
            L.append(f"- NEWEST WORD ON '{v['name']}' ({x['when']}, {x['journal']}:{x['line']}): {x['entry']}"
                     + (f" | {x['said']}" if x.get("said") else "")
                     + ". Who uses this key and where it runs NOW is what the newest entry says, not an older map."
                     + (st(f"{x['entry']} | {x.get('said') or ''}", key=v["name"])
                        or (st(x["state"], key=v["name"], claim=x["state"]) if x.get("state") else "")))
    for e in m.get("about", []):
        L.append(f"- ABOUT IT {e['when']}: {e['entry']} ({e['journal']}:{e['line']}){mark(e)}" + st(e["entry"]))
    for v in m.get("verdicts", []):
        L.append(f"- OWNER SAID ON IT ({v['when']}, {v['journal']}:{v['line']}): {v['said']}")
    if m.get("journals"):
        L.append("- Journals: " + ", ".join(f"{j['journal']} ({j['entries']} entries)" for j in m["journals"]))
    for d in m.get("decided", []):
        L.append(f"- DECIDED: {d['what']} ({d['journal']}{', ' + d['date'] if d.get('date') else ''})")
    for x in m.get("exists", []):
        L.append(f"- EXISTS: {x['what']} [{x.get('status') or ''}] ({x['journal']})"
                 + (f" how: {x['how'][:160]}" if x.get("how") else "")
                 + st(x.get("status") or "", how=x.get("see") or x.get("how") or ""))
    for p in m.get("plans", []):
        L.append(f"- OPEN PLAN ({p['date']}, {p['journal']}:{p['line']}): {p['plan']}" + mark(p) + st(p["plan"]))
    for e in m.get("latest", []):
        L.append(f"- LATEST {e['when']}: {e['entry']} ({e['journal']}:{e['line']}){mark(e)}" + st(e["entry"]))
    for p in m.get("pending", []):
        L.append(f"- PENDING: {p['item']} ({p['journal']})" + (f" (MAY BE DONE: {p['stale']})" if p.get("stale") else "")
                 + st(p["item"]))
    if fired:   # right above the first marked line: what shipped stays first
        L.insert(next(i for i, ln in enumerate(L) if " [STATE" in ln), _STATE_HEADER)
    return "\n".join(L)


_WRITE_CMD = re.compile(r"(?<![\w./~\\-])(ssh|scp|rsync|sed\s+-i|tee|cp|mv|crontab|systemctl|git\s+push)(?![\w./\\-])|(?<![0-9&>])>{1,2}(?!&)\s*(?!/dev/null\b|\$null\b|nul\b)[^\s&|;]")
_FILE_TOKEN = re.compile(r"[\w./\\~-]*?([A-Za-z][\w-]{2,}\.(?:py|sh|js|ts|tsx|mjs|json|toml|yaml|yml|service|conf))\b")


def _quick_seen(session: str) -> tuple[Path, dict]:
    d = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "quick_seen"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.json"):
        if time.time() - old.stat().st_mtime > 3 * 86400:
            old.unlink(missing_ok=True)
    f = d / (re.sub(r"[^\w-]", "", session or "nosession")[:80] + ".json")
    try:
        return f, json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return f, {}


def _share(word: str) -> float:
    """Share of journals that mention the word: the lower, the more it names one thing."""
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*) FROM journals").fetchone()[0] or 1
        df = c.execute("SELECT COUNT(DISTINCT path) FROM entries_fts WHERE entries_fts MATCH ?", (f'"{word}"',)).fetchone()[0]
    finally:
        c.close()
    return df / total


def _specific(word: str, share: float = 0.4) -> bool:
    """A word names something only if few journals mention it: on 2026-10-24 "local" (59% of journals) pulled
    unrelated maps, while "localmodel" (16%), "growvine" (18%) or "oddsboard" (10%) point at one thing."""
    return _share(word) <= share


# Job and org words name WHO, not a topic: Memory Team measured them as noise on 2026-10-24 (director 1/14,
# quality 2/15, auditor 2/13, copywriter 1/8, desk 2/15, manager 0/2, employees 1/5 maps followed), and on
# 2026-10-25 "manager" and "modelo" took both map slots of a message about Chatbot, Codex and Stella.
_ROLE_WORDS = _ROLE_WORDS | set("""manager managers director directors directora supervisor supervisora employee employees empleado
empleados empleada empleadas role roles quality auditor auditors copywriter desk desks team equipo company companies
compania companias empresa empresas owner owners dueno session sessions sesion sesiones worker workers jefe gerente
encargado encargada""".split())

# Everyday chat words (Spanish and English, accents folded). The journals are written in English, so Spanish chat
# words look rare to the index and slip past the share test; on 2026-10-25 "tengo" took a map slot from "chatbot".
_CHAT_WORDS = set("""tengo tenes tiene tienen tenemos tener tenia hay haber hace hacer hacemos haces hago hacelo hice
hizo puedo podes puede pueden podemos poder podria quiero queres quiere queremos querer necesito necesitas necesita
dale bueno buena buenos bien mejor peor mucho mucha muchos muchas poco poca pocos pocas todo toda todos todas nada algo
alguno alguna cada otro otra otros otras mismo misma este esta estos estas esto ese esa esos esas eso aqui aca alli
alla ahora antes despues luego siempre nunca tambien tampoco igual entonces pero porque cuando donde quien cual cuales
cuanto cuanta cuantos como sobre entre hasta desde hacia contra segun durante mientras sino solo sola solos solamente
muy mas menos tipo cosa cosas forma manera parte vez veces momento tiempo dias semana semanas mes meses gratis free
estoy estas esta estamos estan estar estaba estuve fue fueron era eran seria ser sera sido siendo voy vas vamos van
ver veo vemos mira mirar dice dicen decir digo decime sabe saber creo pienso pensando claro listo okay vale gracias
osea sea entiendo entendes probar prueba pruebas usar usamos usando sirve seguir sigue sigo tenga tengas tengan
hagan haga sumar subir bajar pasar poner ponerlo dejar dejalo cuenta cuentas plan planes cosa nuevo nueva nuevos
nuevas really just like want need make have will would could should about there their they them then than also more
some what when where which while into only very much many good great thanks please okay yeah
capaz posta loco loca locos bro man che chabon boludo boluda pelotudo pelotuda mierda carajo puta puto concha
reconcha joder onda irnos hacen hacemos hago estan meterlo buscar encontrar investigar entender entendi maneras desarrollo despegue""".split())

# Spanish work words -> the English the journals are written in (2026-10-25: "ahorrar credito ... contexto ...
# sesiones" mapped "cloud", "capaz" and "mierda" and missed the owner's own credit-saving rule and the
# token-floor measurement). Speech-to-text writes "Cloud Code" for Claude Code.
_ES_EN = {
    "credito": "credit", "creditos": "credit", "ahorrar": "saving", "ahorro": "saving", "ahorrando": "saving",
    "ahorramos": "saving", "contexto": "context", "contextos": "context", "comprimir": "compress",
    "comprimirlo": "compress", "comprimido": "compressed", "patrones": "patterns", "patron": "pattern",
    "repetitivas": "recurring", "repetitivos": "recurring", "repetitiva": "recurring", "repetitivo": "recurring",
    "modelo": "model", "modelos": "models", "gasto": "spend", "gastos": "spend", "consumo": "usage",
    "uso": "usage", "tokens": "tokens", "arranque": "start", "memoria": "memory", "ventas": "sales",
    "venta": "sale", "clientes": "customers", "cliente": "customer", "anuncios": "ads", "pagos": "payments",
    "pago": "payment", "precio": "price", "precios": "prices", "suscripcion": "subscription",
    # 2026-10-26: "en vivo" is how the owner says live (the mapleworks.dev/live plan was missed).
    "vivo": "live", "directo": "live", "transmision": "stream", "transmitir": "stream", "objetivo": "goal",
    "objetivos": "goals", "pagina": "page", "paginas": "pages", "publicar": "publish", "publicado": "published",
    "pendiente": "pending", "pendientes": "pending", "planeado": "planned", "lanzar": "launch",
    "lanzamiento": "launch", "tienda": "store", "oficina": "office", "empleados": "employees",
    # 2026-10-28: "Melodía de MIDI Tools con sonido real" against "MIDI TOOLS MELODY ON HAVEN'S ENGINE: LIVE".
    "melodia": "melody", "melodias": "melody", "sonido": "sound", "sonidos": "sounds", "instrumento": "instrument",
    "instrumentos": "instruments", "suave": "soft", "suaves": "soft", "voz": "voice", "voces": "voices",
    "sintetica": "synthetic", "sintetico": "synthetic", "acordes": "chords", "acorde": "chord", "arpegio": "arpeggio",
    "grabar": "record", "grabacion": "recording", "mezcla": "mix", "canal": "channel", "canales": "channels",
    # 2026-10-28: a Spanish pending line ("compilarlo en la caja") against English ship entries ("box", "build").
    "caja": "box", "compilar": "build", "compilarlo": "build", "compilado": "built", "construir": "build",
    "construirlo": "build", "armarlo": "build", "disenar": "design", "diseno": "design", "vectorial": "vector",
    "conectar": "connect", "conectarlo": "connect", "conectado": "connected", "instalar": "install",
    "instalarlo": "install", "instalado": "installed", "navegador": "browser", "motor": "engine",
    "motores": "engines",
}


# Words in almost every action description; matching on them pulled unrelated decisions (the app branding card).
_INTENT_GENERIC = set("""owner owners order orders company companies every file files work works check checks
start starts make makes run runs from into with this that these those show read write update add new box server
script scripts code session sessions""".split())


def _intent_text(tool: str, ti: dict) -> str:
    """What the AI says it is about to do, in its own words: a command's description, an agent's brief."""
    if tool in ("Bash", "PowerShell"):
        return str(ti.get("description") or "")
    if tool in ("Agent", "Task"):
        return f'{ti.get("description") or ""}. {str(ti.get("prompt") or "")[:400]}'
    return ""


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "ly", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


_TIME_WORD = re.compile(r"\b(?:\d+(?:/\d+)*[\s-]*(?:day|week|month|year)s?|weeks?|months?|quarters?|years?|deadlines?|phases?|roadmaps?)\b")
_PLAN_WORD = re.compile(r"\b(?:plans?|planning|goals?|roadmaps?|schedul\w*|estimat\w*|timelines?|milestones?|how long|by when|how many (?:days|weeks|months))\b")
# Words that mean "when / how long" on their own: no second time word is needed.
_TIME_ALONE = re.compile(r"\b(?:how long|by when|eta|timelines?|roadmaps?|milestones?|how many (?:days|weeks|months))\b")


_RL_FREE, _RL_DIV = 40, 50

# Everyday action words that say little about which rule applies (they made unrelated rules show).
_RULE_VAGUE = set("""page form test fix set about ask question land take many schedule next team open task list day
build make give keep find need want work plan goal week month publish release land launch update create add deploy
button store site screen panel tab link text""".split())


def _owner_rule_lines(intent: str, debug: bool = False, scope: dict = None, _all: bool = False) -> list:
    """Every OWNER_SAID rule line scored directly against the action (owner order 47227, 2026-10-25: a rule was shown
    only when journal_search returned the file with 60% of the query words). Stemmed words weighted by how rare they
    are among the rule lines: a rare word (2 lines or fewer) counts 2, a common one 1, a word in many rules 0.4; a
    "30 day / 2 weeks" phrase is one time token. Shown from a score of 3 (a rare word plus another), the best 2. debug=True adds the shared words."""
    def toks(t: str) -> set:
        f = _fold(t)
        out = {_stem(w) for w in re.findall(r"[a-z0-9]+", f)
               if len(w) >= 3 and w not in _STOP and w not in _INTENT_GENERIC and not w.isdigit()}
        return out
    ws = toks(intent)
    full = {_stem(w) for w in re.findall(r"[a-z0-9]+", _fold(intent)) if len(w) >= 3 and w not in _STOP and not w.isdigit()}
    fi = _fold(intent)
    if (_TIME_WORD.search(fi) and _PLAN_WORD.search(fi)) or _TIME_ALONE.search(fi):
        ws.add("#timeplan")   # planning in calendar time meets the rule on human time; a week or month alone does not
    if not ws:
        return []
    try:
        c = _conn()
        try:
            paths = [r[0] for r in c.execute("SELECT DISTINCT path FROM journals WHERE name = ? OR name LIKE ? ESCAPE '!'", ("OWNER_SAID_JOURNAL.md", "%!_RULES!_JOURNAL.md")).fetchall()]
        finally:
            c.close()
    except Exception:
        return []
    rules, src = {}, {}
    for p in paths:
        try:
            for ln in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.startswith("- 20"):
                    rules[ln] = toks(ln) | ({"#timeplan"} if "human time" in _fold(ln) else set())
                    src.setdefault(ln, Path(p).name)
        except OSError:
            continue
    df = {}
    for t in rules.values():
        for w in t:
            df[w] = df.get(w, 0) + 1
    many = max(20, len(rules) // 5)

    def weight(w: str) -> float:
        if w == "#timeplan":
            return 3.0
        if w in _RULE_VAGUE:
            return 0.4
        n = df.get(w, 0)
        return 2.0 if n <= 2 else (0.4 if n >= many else 1.0)
    scored = {}
    for ln, t in rules.items():
        shared = ws & t
        sc = sum(weight(w) for w in shared if w != "#timeplan")
        sc /= 1 + max(0, len(t) - _RL_FREE) / _RL_DIV   # a long rule shares words with anything: its score is diluted
        if "#timeplan" in shared:
            sc += 3.0
        cov = full & t   # the rule uses most of the action's own words (owner, money, ask...): enough on its own
        if len(cov) >= 3 and len(cov) >= 0.6 * len(full) and len(t) <= 60 and sc < 3.0:
            sc, shared = 3.0, cov
        if sc >= 3.0:
            scored[ln] = (sc, sorted(shared))
    # Which rules may STOP (2026-10-26: "Team HQ ... desktop layout" stopped "Map the paper lab layout on the
    # box" on 2 shared words). A rule that names the action's project stops on its score; a rule naming another
    # product is dropped once the project is known; a rule naming none (global) stops only with 3+ specific
    # shared words, else it is a note without a project and nothing with one.
    out = []
    for ln in sorted(scored, key=lambda k: -scored[k][0]):
        if len(out) >= (len(scored) if _all else 2):
            break
        sc, shared = scored[ln]
        strict = "#timeplan" in shared or len({w for w in shared if w not in _STRICT_GENERIC}) >= 3
        if scope and _names_scope(ln, scope):
            stop = True
        elif scope and (_other_product(ln, scope) or not strict):
            continue
        else:
            stop = strict
        tail = f" [shared: {', '.join(shared)}; score {sc:.1f}]" if debug else ""
        own = "" if src.get(ln) in (None, "OWNER_SAID_JOURNAL.md") else f" [rules: {src[ln]}]"
        out.append(f"- {'OWNER RULE' if stop else 'Related owner rule'}: {ln[2:300]}{tail}{own}")
    return out


# Everyday words of an action description (tests, commits, checks): they never make a decision apply.
_ACTION_GENERIC = set("""test tests tested testing suite suites confirm confirms confirmed verify verifies verified
check checks checked run runs ran rerun pass passes passed fail fails failed failing smoke commit commits committed
old new code fix fixes fixed apply applies applied measure measures measured timing timings time times add adds added
edit edits edited read reads write writes build builds built deploy deploys deployed step steps result results output
before after again first last whole full real live local copy file files line lines""".split())


# ─── Action scope (2026-10-26) ─────────────────────────────────────────────────────────────────────────────
# A Oddsboard session was stopped on an onboarding card of another product, an office-layout rule and a
# learning rule, because the intent map matched the words of the command's DESCRIPTION across every journal.
# The project of an action comes from its INPUT: Brain map keys and "## Scope map" keys (hosts, remote folders)
# named in the command, file path or description, companies, journal names, and paths under a journal root.
# With a project, only its journals speak (stops and notes); a rule or card naming another product is dropped.
# A "## Scope map" table (| Keys | Journals | Notes |, in any journal) only scopes actions: it never maps a
# prompt and never gates an edit, unlike the Brain map.
_SCOPE: dict = {"stamp": None}

# Words that say little about which rule or card applies: a stop outside the action's project needs 3+ others.
_STRICT_GENERIC = {_stem(w) for w in (_ACTION_GENERIC | _RULE_VAGUE | _INTENT_GENERIC | _ROLE_WORDS | _GENERIC_STEMS
                                      | _ENTITY_GENERIC | set("""journal journals entry entries log logs logged map maps
                                      case cases stop stops find found show shows list lists data real every owner
                                      owners correction corrections""".split()))}


def _norm_path(p: str) -> str:
    return _fold(str(p or "").replace("\\", "/"))


def _scope_index() -> dict:
    """Key phrases (token tuples) -> journal names, from every Brain map row (keys -> read first) and every Scope
    map row; journals (folded path, name); companies (folder, names, journals their STARTUP file names). Built
    once per index state."""
    from server import _default_roots
    c = _conn()
    try:
        stamp = (tuple(c.execute("SELECT COUNT(*), MAX(mtime) FROM journals").fetchone()),
                 os.environ.get("JOURNAL_ROOTS", ""), os.environ.get("JOURNAL_HOME", ""))
        if _SCOPE.get("stamp") == stamp:
            return _SCOPE
        cache = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "quick_scope.json"
        try:   # each hook call is a new process: the index is kept on disk until a journal changes
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("stamp") == json.loads(json.dumps(stamp)):
                _SCOPE.clear()
                _SCOPE.update(stamp=stamp, keys=[(tuple(t), js, s) for t, js, s in d["keys"]],
                              journals=[tuple(x) for x in d["journals"]], roots=d["roots"],
                              companies={k: dict(v, named=set(v["named"]), names=set(v["names"]))
                                         for k, v in d["companies"].items()})
                return _SCOPE
        except Exception:
            pass
        journals = [(_norm_path(p), n) for p, n in c.execute("SELECT path, name FROM journals").fetchall()]
        mpaths = [r[0] for r in c.execute("SELECT DISTINCT path FROM entries_fts WHERE entries_fts MATCH ?",
                                          ('heading : (("memory" OR "brain" OR "owners" OR "scope") AND "map")',)).fetchall()]
    finally:
        c.close()
    keys = []   # (key tokens, journal names, strong): a weak key (a shared host) adds journals, never a project alone
    for p in mpaths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for heads, kc, jc in ((("brain map",), 1, 3), (("scope map",), 0, 1)):
            sec = _find_section(text, heads)
            for ln in (sec[1].splitlines() if sec else []):
                cells = [x.strip() for x in ln.strip().strip("|").split("|")]
                if len(cells) <= jc or cells[0].lower() in ("piece", "keys", "") or set(cells[0]) <= set("-: "):
                    continue
                names = _PIECE_JOURNALS.findall(cells[jc])
                strong = kc == 1 or len(cells) < 3 or not cells[2].lower().startswith("no")
                for k in (cells[kc].split(",") if names else []):
                    t = tuple(_tokens(k))
                    if t and len(" ".join(t)) >= 3 and not (len(t) == 1 and (t[0] in _STOP or t[0] in _CHAT_WORDS)):
                        keys.append((t, names, strong))
    roots = [_norm_path(r).rstrip("/") + "/" for r in _default_roots()]
    comps = {}
    for root in _default_roots():
        for cj in list(Path(root).glob("companies/*/company.json")) + list(Path(root).glob("*/companies/*/company.json")):
            d = cj.parent
            try:
                nm = _fold(str(json.loads(cj.read_text(encoding="utf-8")).get("name") or "")).strip()
            except Exception:
                nm = ""
            named = set()
            for st in d.glob("STARTUP*.md"):
                try:
                    named |= set(_PIECE_JOURNALS.findall(st.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    pass
            slug = _fold(d.name)
            comps[slug] = {"dir": _norm_path(str(d)).rstrip("/") + "/", "named": named,
                           "names": {x for x in (nm, " ".join(_tokens(slug))) if len(x) >= 3}}
    count: dict = {}
    for v in comps.values():
        for n in v["named"]:
            count[n] = count.get(n, 0) + 1
    for v in comps.values():   # a journal 3+ companies name is shared craft, not one product
        v["named"] = {n for n in v["named"] if count[n] < 3}
    _SCOPE.clear()
    _SCOPE.update(stamp=stamp, keys=keys, journals=journals, companies=comps, roots=roots)
    try:
        tmp = cache.with_suffix(".tmp%d" % os.getpid())
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"stamp": stamp, "keys": keys, "journals": journals, "roots": roots,
                                   "companies": {k: dict(v, named=sorted(v["named"]), names=sorted(v["names"]))
                                                 for k, v in comps.items()}}), encoding="utf-8")
        os.replace(tmp, cache)
    except Exception:
        pass
    return _SCOPE


def _top_folder(fp: str, roots: list) -> str:
    """The project folder of a journal or file: the first folder under its root (none for a file at the root)."""
    for r in roots:
        if fp.startswith(r):
            parts = fp[len(r):].split("/")
            return r + parts[0] + "/" if len(parts) >= 2 and parts[0] else ""
    return ""


_FED_SCRIPT = re.compile(r"(?:<\s*|\b(?:bash|sh|python3?|py|node|pwsh|powershell(?:\.exe)?)\s+(?:-\w+\s+)*)"
                         r"[\"']?([^\s\"'|;&<>]+\.(?:sh|py|js|mjs|ps1|sql))\b")


def _fed_scripts(cmd: str, cwd: str = "") -> str:
    """The text of the local scripts a command runs or feeds ("ssh box bash -s < lab_layout.sh"): the project of
    the action is often only inside them (/data/fcd-lab). At most 3 files, 20 KB each."""
    out = []
    for m in list(_FED_SCRIPT.finditer(str(cmd or "")))[:3]:
        p = Path(os.path.expanduser(m.group(1)))
        if not p.is_absolute() and cwd:
            p = Path(cwd) / p
        try:
            if p.is_file() and p.stat().st_size <= 200_000:
                out.append(p.read_text(encoding="utf-8", errors="replace")[:20_000])
        except OSError:
            continue
    return "\n".join(out)


def _action_scope(tool: str, ti: dict, intent: str = "", cwd: str = "") -> dict:
    """The project(s) an action belongs to, from its input: {"names", "paths", "jnames"}, or {} when unknown."""
    raw = " ".join(str(x) for x in (ti.get("command"), ti.get("file_path"), ti.get("notebook_path"), ti.get("path"),
                                    intent) if x)
    if not raw.strip():
        return {}
    raw += "\n" + _fed_scripts(ti.get("command") or "", cwd)
    idx = _scope_index()
    line = " " + " ".join(_tokens(raw)) + " "
    names, jnames, comps, folders, weak = set(), set(), set(), set(), set()
    for t, js, strong in idx["keys"]:
        if " " + " ".join(t) + " " in line:
            if strong:
                names.add(" ".join(t))
                jnames |= set(js)
            else:
                weak |= set(js)
    for slug, v in idx["companies"].items():
        if any(f" {n} " in line for n in v["names"]):
            comps.add(slug)
    try:
        for e in _entities_in(raw, kinds=("journal",)):
            jnames |= {n for _, n in idx["journals"] if _fold(Path(n).stem) == e["home"]}
            names.add(e["name"])
    except Exception:
        pass
    low = re.sub(r"(?<![\w:./~-])/([a-z])/", r"\1:/", _norm_path(raw))   # Git Bash "/c/Users/..." is "c:/Users/..."
    for r in idx["roots"]:
        for m in re.finditer(re.escape(r), low):
            parts = re.split(r"[\"'`|<>;\n]", low[m.end():])[0].split("/")
            if len(parts) < 2 or not parts[0]:
                continue   # a file at the root names no project
            ci = next((i for i in (0, 1) if i + 1 < len(parts) and parts[i] == "companies"), None)
            if ci is not None and parts[ci + 1] in idx["companies"]:
                comps.add(parts[ci + 1])
            else:
                folders.add(r + parts[0] + "/")
    if not (jnames or comps or folders):
        return {}   # a shared host alone ("gpubox") names no project
    paths = {fp for fp, n in idx["journals"] if n in jnames or any(fp.startswith(f) for f in folders)}
    # A journal's project folder brings its siblings; a company that names the journal in its STARTUP file is the
    # same project (Forecast Desk runs the Oddsboard bot of FORECAST MARKETS), and the reverse.
    tops = {_top_folder(fp, idx["roots"]) for fp in paths if "/companies/" not in fp} - {""}
    paths |= {fp for fp, _ in idx["journals"] if any(fp.startswith(t) for t in tops)}
    have = {n for fp, n in idx["journals"] if fp in paths}
    for slug, v in idx["companies"].items():
        if v["named"] & have:
            comps.add(slug)
    for slug in comps:
        v = idx["companies"][slug]
        names |= v["names"]
        paths |= {fp for fp, n in idx["journals"] if fp.startswith(v["dir"]) or n in v["named"]}
    paths |= {fp for fp, n in idx["journals"] if n in weak}   # the host's own journal only, never what links to it
    jn = {n for fp, n in idx["journals"] if fp in paths}
    names |= {_stem_phrase(n) for fp, n in idx["journals"] if fp in paths and "/manuals/" not in fp} - {""}
    return {"names": names, "paths": paths, "jnames": jn} if paths else {}


def _names_scope(text: str, scope: dict) -> bool:
    """A text names the action's project: one of its names (keys, companies, journal names) appears whole."""
    line = " " + " ".join(_tokens(text)) + " "
    return any(f" {n} " in line for n in scope.get("names", ()))


def _other_product(text: str, scope: dict) -> bool:
    """A text names a product that is not the action's project (a company, a Brain map key, a journal name)."""
    try:
        ents = _entities_in(text, kinds=("company", "key", "journal"))
    except Exception:
        return False
    return any(e["name"] not in scope.get("names", ()) for e in ents)


def _named_lines(intent: str, scope: dict = None) -> list[str]:
    """A named thing in the AI's own action: its top decision and open plans, as notes (lowercase "decided", so
    they never stop the call; only OWNER RULE and DECIDED lines do). With a project, only its journals."""
    try:
        ents = _entities_in(intent)
        if not ents:
            return []
        groups = _query_groups(intent, ents)
        ed, _ = _entity_cards(ents, groups)
        jn = (scope or {}).get("jnames")
        if jn:
            ed = [d for d in ed if d.get("journal") in jn]
        out = [f'- About {ents[0]["name"]}, decided: {ed[0]["what"][:220]} ({ed[0]["journal"]})'] if ed else []
        return out + [f"- OPEN PLAN ({p['date']}, {p['journal']}:{p['line']}): {p['plan']}"
                      for p in _open_plans(groups, ents, cap=2) if not jn or p["journal"] in jn]
    except Exception:
        return []


def _jkey(name: str) -> str:
    """Same key as quick_hook.jkey: "OWNER_SAID_JOURNAL.md", "OWNER SAID", a path -> "ownersaid"."""
    base = re.split(r"[\\/]", str(name).strip())[-1]
    base = re.sub(r"\.md$", "", base, flags=re.I)
    return "".join(w for w in re.split(r"[^a-z0-9]+", _fold(base)) if w and w != "journal")


def _intent_stops_fresh(im: str, seen: dict) -> bool:
    """Whether an intent map with OWNER RULE / DECIDED lines still has to stop this session. A line stops only
    the first time it is shown, and never once its journal was read in the session (handoff brief, a section, a
    search hit in it, a Read or a sed/cat of the file). Before (2026-10-27): the stop was keyed on the call's
    description, so a session driving box Chromes was stopped ~12 times in a row, one per step, each time by
    another line of OWNER_SAID or WEBWEAVE_JOURNAL, even right after reading both."""
    read = {k for k in (seen.get("jt") or {})} | {k for k in (seen.get("jr") or {})}
    shown = seen.setdefault("ic", {})
    fresh = False
    for ln in im.splitlines():
        m = re.match(r"- (OWNER RULE|DECIDED): (.*)$", ln)
        if not m:
            continue
        if m.group(1) == "OWNER RULE":
            jm = re.search(r"\[rules: ([^\]]+?\.md)\]\s*$", m.group(2))
            j = jm.group(1) if jm else "OWNER_SAID_JOURNAL.md"
        else:
            jm = re.search(r"\(([^()]*?\.md)\)\s*$", m.group(2))
            j = jm.group(1) if jm else ""
        card = _fold(m.group(2))[:100]
        if card not in shown and (not j or _jkey(j) not in read):
            fresh = True
        shown[card] = time.time()
    return fresh


def _intent_map(intent: str, scope: dict = None) -> str:
    """Whole-phrase search of every journal for what the AI is about to do (2026-10-25: maps built from the owner's
    fast typing showed "cloud" and "capaz" and missed his own credit rule, so a duplicate order was filed). Shows
    the owner's decisions and rule lines that share at least two of the action's words, and the best entries.
    scope (_action_scope): the action's project; then only its journals' cards and entries are shown, and only
    rules and cards of that project (or global rules sharing 3+ specific words) stop."""
    from server import journal_search
    scope = scope or {}
    words = list(dict.fromkeys(w for w in re.findall(r"[a-z0-9]+", _fold(intent))
                               if len(w) >= 4 and w not in _STOP and w not in _CHAT_WORDS and not w.isdigit()))
    ws = {w for w in words if w not in _INTENT_GENERIC}   # what a card must share to be shown (precision)
    named = _named_lines(intent, scope)
    if len(ws) < 2:   # too short for the entry search; the owner's rules are still scored on their own
        rl = _owner_rule_lines(intent, scope=scope) + named
        return (f'JOURNALS FOR WHAT YOU ARE ABOUT TO DO ("{intent[:90]}"):\n' + "\n".join(rl)
                + "\nIf one of these already covers it, extend or follow it; never file or build a duplicate.") if rl else ""
    try:
        r = journal_search(" ".join(words[:14]), limit=6)   # every word to find (recall)
    except Exception:
        return ""
    r = json.loads(r) if isinstance(r, str) else r

    # Whole words, stemmed, never everyday action words: "run suite and confirm test" stopped on the Adshare
    # AI card because "test" sat inside "tested" and "confirm" inside "confirms" (2026-10-26).
    spec = {_stem(w) for w in ws if w not in _ACTION_GENERIC and _stem(w) not in _ACTION_GENERIC}
    try:
        ients = _entities_in(intent)
    except Exception:
        ients = []

    def hits(s: str) -> int:
        return len(spec & {_stem(w) for w in _tokens(s)})

    sp = scope.get("paths") or set()

    def in_scope(path: str, text: str = "") -> bool:
        """No project known, or the card lives in its journals, or the project is the card's subject."""
        return not sp or _norm_path(path) in sp or any(_subject({"name": n}, text) for n in scope.get("names", ()))

    lines = []
    for d in r.get("already_decided", []):
        if not in_scope(d.get("path", ""), d.get("what", "")):
            continue   # another project's card: never a stop, never a note (2026-10-26, Oddsboard session)
        h = hits(f'{d.get("what", "")} {d.get("aliases", "")}')
        subj = any(_subject(e, d.get("what", "")) for e in ients)
        # A stop needs 3+ specific shared words, or the card's own subject named in the action plus 2.
        if h >= 3 or (subj and h >= 2):
            lines.append(f'- DECIDED: {d["what"][:240]} ({d.get("journal", "")})')
        elif h >= 2:
            lines.append(f'- Related decision: {d["what"][:240]} ({d.get("journal", "")})')
    lines = lines[:3]
    shown = 0
    for m in r.get("matches", []):
        try:
            got, tot = (int(x) for x in str(m.get("terms_matched") or "0/1").split("/"))
        except ValueError:
            continue
        if not tot or got / tot < 0.6 or shown >= 3:
            continue
        if m.get("name") == "OWNER_SAID_JOURNAL.md" or str(m.get("name")).endswith("_RULES_JOURNAL.md"):   # scored below
            continue
        if not in_scope(m.get("path", "")):
            continue
        e = (m.get("entries") or [{}])[0]
        lines.append(f'- {m["name"]}:{e.get("line", "")} {str(e.get("heading") or "")[:120]}')
        shown += 1
    lines = _owner_rule_lines(intent, scope=scope) + lines + named
    if not lines:
        return ""
    return (f'JOURNALS FOR WHAT YOU ARE ABOUT TO DO ("{intent[:90]}"):\n' + "\n".join(lines)
            + "\nIf one of these already covers it, extend or follow it; never file or build a duplicate.")


def _to_english(text: str) -> str:
    text = re.sub(r"\bcloud\s+code\b", "Claude Code", text, flags=re.I)
    return re.sub(r"[A-Za-zÀ-ÿ]+", lambda m: _ES_EN.get(_fold(m.group(0)), m.group(0)), text)


def _prompt_vocab() -> set:
    """Words that name something concrete: Brain map keys and journal name stems."""
    vocab = set()
    c = _conn()
    try:
        for (name,) in c.execute("SELECT name FROM journals").fetchall():
            for w in re.split(r"[^a-z0-9]+", _fold(Path(name).stem)):
                if len(w) >= 4 and w not in _GENERIC_STEMS and w not in ("journal", "full", "user", "juice", "notes",
                                                                         "curriculum", "manual", "system", "company"):
                    vocab.add(w)
    finally:
        c.close()
    return vocab


def _map_keys() -> set:
    keys = set()
    c = _conn()
    try:
        paths = [r[0] for r in c.execute("SELECT DISTINCT path FROM entries_fts WHERE entries_fts MATCH ?",
                                         ('heading : (("memory" OR "brain" OR "owners") AND "map")',)).fetchall()]
    finally:
        c.close()
    for p in paths:
        sec = _find_section(Path(p).read_text(encoding="utf-8", errors="replace"), ("brain map",))
        for ln in (sec[1].splitlines() if sec else []):
            cells = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0].lower() != "piece" and not set(cells[0]) <= set("-: "):
                keys |= {_fold(k.strip()) for k in cells[1].split(",") if len(k.strip()) >= 3}
    return keys


def _all_map_rows() -> list[dict]:
    c = _conn()
    try:
        paths = [r[0] for r in c.execute("SELECT DISTINCT path FROM entries_fts WHERE entries_fts MATCH ?",
                                         ('heading : (("memory" OR "brain" OR "owners") AND "map")',)).fetchall()]
    finally:
        c.close()
    rows = []
    for p in paths:
        sec = _find_section(Path(p).read_text(encoding="utf-8", errors="replace"), ("brain map",))
        for ln in (sec[1].splitlines() if sec else []):
            cells = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0].lower() != "piece" and not set(cells[0]) <= set("-: "):
                rows.append({"piece": cells[0], "now": cells[2], "read": cells[3]})
    return rows


def _journal_by_name(name: str) -> str:
    c = _conn()
    try:
        r = c.execute("SELECT path FROM journals WHERE name = ? ORDER BY mtime DESC LIMIT 1", (name,)).fetchone()
    finally:
        c.close()
    return r[0] if r else ""


def _my_work_text(words: set, company: str = "") -> str:
    """At a session's first message: the Brain map pieces this session works on (its role and company named in the
    message, e.g. "You are BUILDER of Shopsite" matches "Shopsite Builder"), with each piece's pending items and latest
    entries, so pending work reaches whoever does it without anyone forwarding it (owner 2026-10-24)."""
    out = []
    for row in _all_map_rows():
        parts = re.split(r"\band\b|;|,", re.sub(r"\([^)]*\)", "", row["now"]))
        hit = False
        for part in parts:
            sig = [w for w in re.findall(r"[a-z0-9]+", _fold(part)) if len(w) >= 3 and w not in _STOP][:3]
            if len(sig) >= 2 and all(w in words for w in sig):
                hit = True
                break
        if not hit:
            continue
        lines = [f"- {row['piece']} (read first: {row['read']})"]
        for name in re.findall(r"[\w.-]+_JOURNAL\.md", row["read"]):
            p = _journal_by_name(name)
            if not p:
                continue
            text = Path(p).read_text(encoding="utf-8", errors="replace")
            handoff = _find_section(text, ("handoff", "pending"))
            pool = (handoff[1] if handoff else text).splitlines()
            todo = [s.strip()[:170] for s in pool if s.strip().startswith(("- [ ]", "Next:", "Pending:"))][-5:]
            dated = sorted({h for h in re.findall(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2} [^\n]{0,110})", text, re.M)}, reverse=True)[:3]
            for t in todo:
                lines.append(f"  PENDING ({name}): {t}")
            for d in dated:
                lines.append(f"  LATEST ({name}): {d}")
        out.append("\n".join(lines))
    if not out:
        return ""
    head = ("YOUR PIECES (Brain map rows where you work). Context only: follow your own task list first:")
    return head + "\n" + "\n".join(out)


REPEAT_AFTER = 3  # prompts: a word's map comes back when it reappears this many user messages later


def rows_cache_path() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal"))) / "quick_rows.json"


_PIECE_JOURNALS = re.compile(r"[\w.-]+_JOURNAL[\w.-]*\.md")


def _journal_files(read_first: str) -> list[str]:
    """Paths on disk of the journals a Brain map row says to read first (the gate offers them to Read)."""
    return [p for p in (_journal_by_name(n) for n in _PIECE_JOURNALS.findall(read_first or "")) if p]


def _write_rows_cache():
    """Brain map rows with their keys, for quick_hook.py's read path (which must not import server.py)."""
    c = _conn()
    try:
        paths = [r[0] for r in c.execute("SELECT DISTINCT path FROM entries_fts WHERE entries_fts MATCH ?",
                                         ('heading : (("memory" OR "brain" OR "owners") AND "map")',)).fetchall()]
    finally:
        c.close()
    rows = []
    for p in paths:
        sec = _find_section(Path(p).read_text(encoding="utf-8", errors="replace"), ("brain map",))
        for ln in (sec[1].splitlines() if sec else []):
            cells = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0].lower() != "piece" and not set(cells[0]) <= set("-: "):
                rows.append({"piece": cells[0], "read": cells[3],
                             "keys": [_fold(k.strip()) for k in cells[1].split(",") if len(k.strip()) >= 3],
                             "files": _journal_files(cells[3])})
    try:
        rows_cache_path().write_text(json.dumps(rows), encoding="utf-8")
    except Exception:
        pass


def _pair_homes(pairs: list[tuple[str, str]]) -> list[tuple[int, str, str, str]]:
    """Word pairs from one message whose entries sit mostly in one journal: "pack 1 funnel" -> TONE_GARDEN
    (39 entries vs 6 in the next). Each word alone is too common to map (2026-10-24 incident)."""
    out = []
    c = _conn()
    try:
        for a, b in pairs:
            top = c.execute("SELECT path, COUNT(*) AS n FROM entries_fts WHERE entries_fts MATCH ? GROUP BY path "
                            "ORDER BY n DESC LIMIT 2", (_fts_or([a]) + " AND " + _fts_or([b]),)).fetchall()
            if top and top[0][1] >= 3 and (len(top) == 1 or top[0][1] >= 2 * top[1][1]):
                out.append((top[0][1], a, b, top[0][0]))
    finally:
        c.close()
    return sorted(out, reverse=True)


def _compact(text: str) -> str:
    """A map shown again: header, piece, journals and decisions only."""
    # A line marked as a state claim stays: a repeat map is where a stale "inactive" gets repeated as current.
    keep = [ln for ln in text.splitlines()
            if not ln.startswith(("- LATEST", "- PENDING", "- EXISTS")) or " [STATE" in ln]
    return "\n".join(keep) + "\n- (shown earlier in this session; a new topic here still needs its journal read)"


def git_only(cmd: str) -> bool:
    """A command that only records work in git (add, commit, status, log, diff, show). It is not a new action on any
    piece: the files it names were mapped when they were written, and the commit message words only pulled unrelated
    journals (2026-10-30: auditor and visual-engine manuals under "Commit the repeat-map fix")."""
    bare = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", "Q", cmd or "")   # a commit message may hold ; & |
    return bool(re.fullmatch(r"\s*(?:cd\s+\S+\s*&&\s*)?(?:git\s+(?:add|commit|status|log|diff|show)\b"
                             r"[^;&|]*(?:&&\s*|;\s*)?)+\s*", bare))


def quick_hook(call: dict, prompt: bool = False):
    """Claude Code hook. Tool calls: before editing a file (or running a command that writes or reaches a
    server), show its quick map; the first touch of a piece in the Brain map is denied until the session
    really read that piece's journal (quick_hook.gate; a plain retry is denied again, escape on the 3rd attempt
    only when the read is impossible). Prompts: only when the message names something concrete."""
    f, seen = _quick_seen(call.get("session_id", ""))
    if call.get("reports_reads"):
        seen["rr"] = 1  # the mod reports journal reads, so the gate may wait for one
    out = None
    if prompt:
        # The user-message counter: maps re-show after REPEAT_AFTER messages, read reminders are per message.
        n = seen["n"] = int(seen.get("n", 0)) + 1

        def due(key: str) -> bool:
            last = seen.get(key)
            # Values above 1e6 are the old once-per-session timestamps: let those words show again.
            return last is None or last > 1e6 or n - last >= REPEAT_AFTER

        # A path is never a word of the message: "C:\Users\ANNLEE~1\AppData\..." mapped "annlee" (2026-10-26). Any
        # token with a slash, a backslash or a ~1 short-name mark is dropped, and so is a drive path with spaces.
        raw = str(call.get("prompt") or "")[:4000]
        raw = re.sub(r"[A-Za-z]:[\\/][^\n\"'`|<>]*?\.\w{1,5}\b", " ", raw)
        text = _to_english(re.sub(r"\S*(?:[\\/]|~\d)\S*", " ", raw))
        words = {_fold(w).strip("._-") for w in re.findall(r"[A-Za-zÀ-ÿ0-9_.-]{3,}", text)}   # "capaz." is "capaz"
        keys, vocab = _map_keys(), _prompt_vocab()
        _write_rows_cache()
        # A word counts when the Brain map names it, or when it is specific (few journals mention it) and its
        # map has a real home: a journal named after it, or one journal that talks about it a lot.
        # "You are DIRECTOR of Shopsite": the role and the company are who the session is, not a topic to map.
        who = re.search(r"\byou are (?:the )?([A-Za-z][A-Za-z _-]{1,40}?) of (?:the )?([A-Za-zÀ-ÿ0-9]+)", text, re.I)
        company = _fold(who.group(2)) if who else ""
        role_words = {_fold(w) for w in re.findall(r"[A-Za-z]+", who.group(1))} | {company} if who else set()
        content = [w for w in words if len(w) >= 4 and w not in _STOP and w not in role_words
                   and not (w in _ROLE_WORDS and w not in keys) and w not in _CHAT_WORDS]
        # Code tokens ("real_sol", "local-only", "brake.py.") are one-off names: when the Brain map does not key
        # them, their map is just the generic half ("real", "local") with unrelated cards (Memory Team, 2026-10-25:
        # 7-8 unrelated cards each, 0 opens). The plain words of the message still map on their own.
        # A file name whose stem the map keys ("quickmap.py" -> quickmap) is the piece itself: it keeps its map.
        def _keyed_file(w: str) -> bool:
            m = re.fullmatch(r"([a-z0-9_-]+)\.(?:py|ts|js|md|json|sh|sql|toml)\.?", w)
            return bool(m) and m.group(1) in keys

        content = [w for w in content if w in keys or not re.search(r"[_.-]", w.strip("_.-")) or _keyed_file(w)]
        shares = {w: _share(w) for w in content}
        specific = {w for w in content if w in keys or shares[w] <= (0.4 if w in vocab else 0.2)}
        maps = []
        # Names first: a word written with a capital inside a sentence or in mixed case ("Chatbot", "Stella") is
        # a product or a model; "evaluar" is not, even when it is rarer. Then rarest first.
        proper = set()
        # An initial capital at a line start, bullet, bold label ("**Probado**", "**Tiempos:**"), table cell
        # ("| Mensaje |") or before a colon is formatting, not a name; nor is a word the message also writes in
        # lowercase (2026-10-26: Spanish report words mapped as names).
        lower_words = {_fold(w) for w in re.findall(r"\b[a-zà-ÿ][a-zà-ÿ0-9]*\b", text)}
        for mt in re.finditer(r"[A-Za-zÀ-ÿ0-9]+", text):
            tok, before, after = mt.group(0), text[:mt.start()].rstrip(), text[mt.end():mt.end() + 3]
            if any(ch.isupper() for ch in tok[1:]):
                proper.add(_fold(tok))
            elif tok[0].isupper() and before and before[-1] not in ".!?:\n*_|#->([\"'" \
                    and not re.match(r"\**:", after) and _fold(tok) not in lower_words:
                proper.add(_fold(tok))
        # The owner types fast, with typos and slang (2026-10-25: "cloud", "capaz", "mierda" took every slot), so
        # from his message only SURE things map: Brain map pieces and names. The real map comes from what the AI
        # is about to do (_intent_map on its own action descriptions).
        cands = [w for w in specific if due(f"p:{w}") and (w in keys or w in proper)]
        # 3 full maps; names beyond that still get a short one, up to 6 (2026-10-25: "Cloudmodel" was the 4th name of a
        # message and its vault key never showed).
        # Named things (a company, a journal, a product in a card, a Brain map key) map even when typed in
        # lowercase inside a fast message (2026-10-26: "mapleworks en vivo" mapped nothing). A phrase ("venture
        # desk") is mapped as one, not word by word.
        ents = [e["name"] for e in _entities_in(text) if e["name"] not in role_words]
        ent_words = {w for e in ents if " " in e for w in e.split()}
        cands = [w for w in cands if w not in ent_words] + [e for e in ents if e not in cands and due(f"p:{e}")]
        for e in ents:
            shares.setdefault(e, 0.0)
        shown: set = set()
        for w in sorted(cands, key=lambda x: (x not in keys and x not in ents, x not in proper, shares[x])):
            if len(maps) >= (6 if w in proper else 3):
                break
            m = quick_map(w, limit=3, context=text)
            named_cards = [x for x in m.get("decided", []) + m.get("exists", []) if w in _fold(x.get("what") or "")]
            strong = m.get("pieces") or any(w in _name_words(j["journal"]) for j in m.get("journals", [])) \
                or len(named_cards) >= 2 or m.get("about") or m.get("vault") \
                or (w in ents and (m.get("plans") or m.get("decided") or m.get("exists"))) \
                or (m.get("shipped") and (w in proper or w in ents or w in keys))
            if strong and not m.get("pieces"):
                # No piece owns the word: a few cards are enough, the rest is other topics sharing it.
                m = dict(m, latest=m.get("latest", [])[:2], pending=m.get("pending", [])[:1],
                         decided=m.get("decided", [])[:2], exists=m.get("exists", [])[:2])
            if strong:
                # One message, one copy of each card: a card or plan already shown in an earlier map of this
                # message is left out of the next one (2026-10-26: the same cards repeated under five words).
                m = dict(m, decided=[x for x in m.get("decided", []) if ("d", x["what"]) not in shown],
                         exists=[x for x in m.get("exists", []) if ("d", x["what"]) not in shown],
                         plans=[x for x in m.get("plans", []) if ("p", x["journal"], x["line"]) not in shown],
                         about=[x for x in m.get("about", []) if ("a", x["journal"], x["line"]) not in shown])
                shown |= {("d", x["what"]) for x in m["decided"] + m["exists"]}
                shown |= {("p", x["journal"], x["line"]) for x in m["plans"]} | {("a", x["journal"], x["line"]) for x in m["about"]}
            t = quick_map_text(m) if strong else ""
            again = f"p:{w}" in seen
            seen[f"p:{w}"] = n
            if t:
                maps.append(_compact(t) if again or len(maps) >= 3 else t)
        if len(maps) < 3:
            # Common words ("pack", "funnel") never map alone, but two of them close together in the message
            # often point at one journal. Pairs within 3 words, at least one of them common, at most 12 checked.
            seq = [_fold(w) for w in re.findall(r"[A-Za-zÀ-ÿ0-9_-]+", text)]
            pos = [(i, w) for i, w in enumerate(seq) if len(w) >= 4 and w not in _STOP and w not in role_words
                   and not w.isdigit() and w not in _GENERIC_STEMS and w not in _ROLE_WORDS and w not in _CHAT_WORDS]
            pairs = []
            for a in range(len(pos)):
                for b in range(a + 1, len(pos)):
                    if pos[b][0] - pos[a][0] > 3:
                        break
                    wa, wb = sorted((pos[a][1], pos[b][1]))
                    if wa != wb and (wa not in specific or wb not in specific) and (wa, wb) not in pairs \
                            and due(f"p:{wa}+{wb}"):
                        pairs.append((wa, wb))
            homes = set()
            for _, wa, wb, home in _pair_homes(pairs[:12]):
                if len(maps) >= 3:
                    break
                if home in homes:
                    continue  # "pack funnel" already points at AA: "works funnel" would only repeat it
                homes.add(home)
                m = quick_map(f"{wa} {wb}", limit=3)
                again = f"p:{wa}+{wb}" in seen
                seen[f"p:{wa}+{wb}"] = n
                t = quick_map_text(m) if len(m.get("terms", [])) == 2 else ""
                if t:
                    maps.append(_compact(t) if again else t)
        if "start" not in seen:
            seen["start"] = time.time()
            mine = _my_work_text({_fold(w) for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", text)}, company)
            if mine:
                maps.insert(0, mine)
        if maps:
            out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
                   "\n\n".join(maps) + "\n(Quick map from the journals. Open what it points to before acting; "
                   "journal_quick \"<word>\" for anything else.)"}}
    else:
        ti = call.get("tool_input") or {}
        targets = []
        if ti.get("file_path") or ti.get("notebook_path"):
            fp = str(ti.get("file_path") or ti.get("notebook_path"))
            if not re.search(r"journal[^\\/]*\.md$", fp, re.I):
                targets.append(fp)
        else:
            cmd = str(ti.get("command") or "")
            if _WRITE_CMD.search(cmd):
                targets += list(dict.fromkeys(m.group(1) for m in _FILE_TOKEN.finditer(cmd)))[:3]
        deny, notes = [], []
        for tg in targets:
            m = quick_map(tg, limit=3, cards=False)
            nb = m.get("newer") or {}
            rk = "rn:" + _fold(Path(tg.replace("\\", "/")).name)
            if nb and rk not in seen:
                # A newer entry says this piece was replaced or redesigned: shown FIRST and stopped once (the same
                # file passes on retry), before any other map of it.
                seen[rk] = time.time()
                deny.append(newer_text(nb, Path(tg.replace("\\", "/")).name)
                            + "\n(Stopped once: the same file passes on retry, once you checked which file serves the piece now.)")
                continue
            own_journal = any(t in _name_words(j["journal"]) for j in m.get("journals", []) for t in m.get("terms", []))
            if not quick_map_text(m) or not (m.get("pieces") or own_journal):
                continue  # loose word matches are noise, and noise teaches everyone to skip the map
            m = quick_map(tg, limit=3)  # a mapped file: now the cards
            text = quick_map_text(m)
            # The gate: a mapped piece stays closed until its journal was really read (quick_hook.gate), a plain
            # retry is denied again (2026-10-24: "stopped once" let a retry through without reading anything).
            stops, first = [], False
            for o in m.get("pieces", []):
                js = _PIECE_JOURNALS.findall(o.get("path") or "") or [j["journal"] for j in m.get("journals", [])[:1]]
                was = (seen.get("g") or {}).get(f"o:{o['piece']}")
                state, msg = _gate(seen, f"o:{o['piece']}", js, [p for p in map(_journal_by_name, js) if p],
                                   f'the piece "{o["piece"]}"')
                if state == "deny":
                    stops.append(msg)
                    first = first or not isinstance(was, dict)
                elif state == "escape":
                    notes.append(msg)
            # The same piece reached through another file or command (quickmap.py, quick_hook.py, a git commit of
            # both) got its full map again on every call (2026-10-30: the journal-tool map 3 times in one turn).
            pks = [f"ps:{o['piece']}" for o in m.get("pieces", [])]
            piece_seen = bool(pks) and all(k in seen for k in pks)
            if stops:
                deny.append((text + "\n\n" if first else "") + "\n".join(stops))
            elif f"t:{_fold(tg)}" not in seen and not piece_seen:
                notes.append(text)
            for k in pks:
                seen[k] = time.time()
            seen[f"t:{_fold(tg)}"] = time.time()
        tool = str(call.get("tool_name") or "")
        intent = _intent_text(tool, ti)
        cmd_s = str(ti.get("command") or "")
        acts = tool in ("Agent", "Task") or (_WRITE_CMD.search(cmd_s) and not git_only(cmd_s))
        ikey = "i:" + " ".join(sorted(set(re.findall(r"[a-z0-9]{4,}", _fold(intent)))))[:160]
        if intent and acts and ikey not in seen:
            seen[ikey] = time.time()
            try:
                scope = _action_scope(tool, ti, intent, str(call.get("cwd") or ""))
            except Exception:
                scope = {}
            im = _intent_map(intent, scope=scope)
            if im and ("OWNER RULE:" in im or "DECIDED:" in im) and _intent_stops_fresh(im, seen):
                # Stop ONCE, before acting: the map shown after the call came too late (the duplicate order was
                # already filed). The same intent passes on retry, once it has been seen.
                deny.append(im)
            elif im:
                notes.insert(0, im)
        if deny:
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                   "permissionDecisionReason": "\n\n".join(deny) + (
                       "" if all(d.startswith("REPLACED/NEWER") for d in deny) else
                       "\n\nStopped once: the same call passes on retry, and reading the journal named above opens "
                       "every later call on it." if all(d.startswith("JOURNALS FOR WHAT") or d.startswith("REPLACED/NEWER")
                                                        for d in deny) else
                       "\n\nThe call passes once that journal read is recorded (its journal, what was decided, what is "
                       "in flight).")}}
        elif notes:
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\n\n".join(notes)}}
    f.write_text(json.dumps(seen), encoding="utf-8")
    if out:
        print(json.dumps(out, ensure_ascii=False))
