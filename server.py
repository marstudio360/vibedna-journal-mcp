"""
Journal MCP: the library of project journals.

ONE journal per project = ONE source of truth. Inside each journal lives the
project's roadmap, state, decisions, incidents, handoffs, fixes, all as
sections of the same file. Not scattered across HANDOFF/STATE/ROADMAP docs.

Only files matching JOURNAL patterns get indexed. Standard structure:

    # PROJECT_JOURNAL.md
    ## Vision / Why this exists
    ## Current state
    ## Roadmap
    ## Decisions log
    ## Incidents
    ## Recent entries (newest at bottom)
      ## YYYY-MM-DD HH:MM [tag] one-line title
      ... entry ...
      ---

Tools let any AI session: read it, append entries, search across all
journals, render handoff brief for next session, list sections.

Storage:
  ~/.journal/index.sqlite: fast lookup index
  ~/.journal/config.toml:  optional config (additional roots)
  Journal files themselves stay where they live in their project folders.

Standalone: no hardcoded paths. Roots via JOURNAL_ROOTS env var or config.toml.
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import re
import datetime
import urllib.request
import urllib.error
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from mcp.server.fastmcp import FastMCP

_MANUAL = """\
# How to use these journals (read this before touching one)

A journal is ONE markdown file per project (<PROJECT>_JOURNAL.md) and the single source of truth.
Sessions, agents and other AIs come and go; the journal is what lets the next one continue exactly
where the last one stopped. Every rule below exists so nothing important gets lost or skipped.

## 1. Starting
- `journal_handoff_brief("<PROJECT>")` first. It shows, in this order: what is pending now, the
  project's rules (a "How to use" / "Rules" section), what the owner already DECIDED, the current
  state, what ALREADY EXISTS, and the latest entries. Rebuild your task list from it.
- When the owner names a tool, session or file, use exactly that. A risk you see goes in one line
  next to it, never as a silent substitute.
- Before answering "how did we do X", "why did we decide Y", "did another session touch Z":
  `journal_search("<words>")`. It searches every journal at once and also finds synonyms
  (twitter = X = tweet, publicar = post, ig = instagram...). Open every result that could matter;
  a snippet is not the content. `journal_recent_changes(24)` shows what other sessions just did.
- Never say "this is not in the journal" or "this is new" after one search. Search 2-3 other words
  for the same idea and for its mechanism (who does what, who pays whom) first. (A real incident: a
  role the owner had defined as "campaign creator" was called new because the search was "designer".)

## 2. Before building anything
- `journal_before_build("<what you are about to build, in plain words>")`. If something already
  exists for it, EXTEND that; never build a second tool for the same job. (A real incident: a new
  X posting tool was built while a working one was documented in another project's journal.)

## 3. While working (in the same turn, never batched at the end)
- `journal_append("<PROJECT>", entry, tag)` for anything a future session needs: shipped work, a bug
  with its root cause and fix, a decision with its reason, an incident, a number that matters, a trap.
  Tags: feature, fix, decision, incident, data, lesson, release, correction.
- Entries are short and scannable: what happened, why, what to do next time. Write lessons general
  enough to help the next build, not only this one. Absolute dates (2026-10-22), never "yesterday".
- Built or found something reusable (a tool, a script, a working pipeline, an account, an endpoint)?
  `journal_capability_add(...)`: one line in "Already exists", so nobody rebuilds it.
- The owner decided something (a product rule, a role, a money split, a name, a design or copy rule)?
  `journal_decision_add(...)` in the same turn, with EVERY word someone might use for it in `aliases`.
  A decision left only as a dated entry gets lost under later history and gets proposed again as new.
- Wrong entry? Never delete history: append a [correction] that says what was wrong and what is true.

## 4. State that changes
- "Current state", "Pending now" and "Handoff for next session" are REPLACED whole, never appended
  to: `journal_update_section(name, "Current state", text, mode="replace")`. A section that grows
  by appends turns into a pile of stale claims. (The section is created if it does not exist.)
- Decisions log and Incidents grow with mode="append".

## 5. Leaving (end of session, after every big milestone, before a compaction)
- Replace "Handoff for next session" with the full task list: done / in progress / pending /
  blocked by the owner, one line each, plus where you stopped and the next concrete step.
- Next to any "ideas not tried yet", list what WAS tried with the owner's verdict ("Tried: X, owner: \"...\""),
  and write each owner verdict in the entry as "Owner verdict: ..." so the quick map can find it:
  a handoff that lists only open ideas makes the next session re-propose what already failed (2026-10-26).
- Replace "Current state" if anything changed. Check that every pending item still is pending.
- The next session must be able to continue reading only the handoff brief. If it could not, the
  journal is not finished.

## Never
- A second journal for a project that already has one, or a parallel journal for a topic that has one.
- Secrets in a journal (keys, tokens, passwords): store them in a vault and write only where they live.
- Answering from memory when the journal has it written down.
"""

_MANUAL_SHORT = (
    "Project journals: one <PROJECT>_JOURNAL.md per project is the single source of truth. "
    "Start with journal_handoff_brief(project). Search with journal_search before answering how/why/did-someone. "
    "Before building anything call journal_before_build(task) and extend what already exists. "
    "Log work in the same turn with journal_append; record reusable things with journal_capability_add. "
    "Current state, Pending now and Handoff are replaced whole (journal_update_section mode=replace). "
    "Leave the Handoff so the next session can continue from the brief alone. Full manual: journal_how_to()."
)

mcp = FastMCP("journal", instructions=_MANUAL_SHORT)

# ─── Storage ────────────────────────────────────────────────────────────────
_HOME = Path(os.environ.get("JOURNAL_HOME") or str(Path.home() / ".journal"))
_HOME.mkdir(parents=True, exist_ok=True)
_DB = _HOME / "index.sqlite"
_CONFIG = _HOME / "config.toml"

# ─── Marketplace connector (pairs an install to the store) ─
# The Journal MCP IS the connector to vibedna.ai. No separate MCP. Pairing saves
# a connect-token here; the engine never takes payment (checkout is on the site).
_AUTH = _HOME / "auth.json"
_SITE = (os.environ.get("VIBEDNA_SITE") or "https://vibedna.ai").rstrip("/")

# This copy's version. Bump it when packaging; check_for_update compares it against
# what the site currently publishes, so an installed copy can tell it is behind.
VERSION = "1.3.0"
PRODUCT_SLUG = "journal"


def _http_get(path: str, timeout: int = 20, token: str = "") -> dict:
    url = path if path.startswith("http") else f"{_SITE}{path}"
    headers = {"User-Agent": f"journal-mcp/{VERSION}", "Accept": "application/json"}
    if token:
        # In a header, never in the URL: query strings end up in server and proxy logs.
        headers["X-Journal-Token"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


@mcp.tool()
def check_for_update() -> str:
    """Is this copy behind the published version?

    Your copy is a folder on your machine, so it stays exactly as it was the day you
    installed it while fixes keep shipping. This asks what is published now and tells
    you whether to update, and how. It sends nothing about you: just a version number
    comes back."""
    try:
        d = _http_get(f"/api/mcp/latest?slug={PRODUCT_SLUG}", timeout=15) or {}
    except Exception as e:
        return f"could not reach the update check ({type(e).__name__}). Your copy still works; try later."

    latest = str(d.get("version") or "")
    if not latest:
        return "the update service did not report a version. Nothing to do."

    def parts(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)

    if parts(latest) <= parts(VERSION):
        return f"up to date (you have {VERSION}, published is {latest})."

    return "\n".join([
        f"UPDATE AVAILABLE: you have {VERSION}, published is {latest}.",
        "",
        "To update, from the same email you bought with:",
        f"  1. Download: https://vibedna.ai/api/download?slug={PRODUCT_SLUG}&license=<your key>",
        "     (your key is in your purchase email, and in your library at vibedna.ai/library)",
        "  2. Unzip over your current folder, keeping your own files.",
        "  3. Restart your AI so it loads the new tools.",
        "",
        "Your writing is not in this folder: your journal .md files stay in your own",
        f"project folders, and the search index, settings and pairing live in {_HOME}.",
        "An update replaces code only, never a single line you wrote.",
    ])


def _load_auth() -> dict:
    try:
        return json.loads(_AUTH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_auth(d: dict) -> None:
    _AUTH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    try:
        os.chmod(_AUTH, 0o600)  # owner only on macOS/Linux; Windows keeps it in the user profile
    except OSError:
        pass


def _default_roots() -> list[Path]:
    """Roots to scan. Override via JOURNAL_ROOTS env var (semicolon-separated) or config.toml."""
    env_roots = os.environ.get("JOURNAL_ROOTS", "")
    if env_roots:
        return [Path(p.strip()) for p in env_roots.split(";") if p.strip()]
    # Config file
    if _CONFIG.exists():
        try:
            import tomllib
            data = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
            roots = data.get("roots") or []
            if roots:
                return [Path(p) for p in roots]
        except Exception:
            pass
    # Last-resort default: scan ~/Desktop + ~/Documents (cross-platform)
    home = Path.home()
    candidates = [home / "Desktop", home / "Documents"]
    return [p for p in candidates if p.is_dir()]


# Sections every journal can have, matched case-insensitively by substring (English or Spanish).
_SEC_PENDING = ("pending now", "pendientes ahora")
_SEC_HANDOFF = ("handoff",)
_SEC_STATE = ("current state", "estado actual")
_SEC_EXISTS = ("already exists", "ya existe")
_SEC_RULES = ("how to use", "cómo usar", "como usar", "reglas", "rules")
_SEC_DECIDED = ("decided", "ya decidido")
_DATED_H2 = re.compile(r"^## \d{4}-\d{2}-\d{2}")

# Words that mean the same thing for search: a query for one finds the others. Extend with
# config.toml `aliases = [["a", "b"], ...]` or JOURNAL_ALIASES="a,b,c;d,e".
_DEFAULT_ALIASES = [
    ["twitter", "x", "tweet", "tweets", "xcom"],
    ["instagram", "ig", "insta", "reel", "reels"],
    ["tiktok"], ["reddit", "subreddit", "subreddits"], ["linkedin"],
    ["youtube", "yt", "shorts"], ["facebook", "fb"], ["pinterest", "pin", "pins"],
    ["publicar", "publicacion", "postear", "post", "posting", "publish", "posteo"],
    ["comentar", "comentario", "comment", "comments", "reply", "responder", "respuesta"],
    ["mail", "email", "correo", "mails", "emails"],
    ["pago", "pagos", "payment", "payments", "checkout", "cobro", "cobrar"],
    ["buscar", "search", "busqueda"], ["video", "videos", "mp4"],
    ["imagen", "imagenes", "image", "images", "foto", "fotos", "photo", "photos"],
    ["seguir", "follow", "follows", "seguidores", "followers"],
    ["like", "likes", "megusta"], ["navegador", "browser", "chrome"],
    ["cuenta", "cuentas", "account", "accounts"], ["subir", "upload", "uploads"],
    ["herramienta", "tool", "tools"], ["automatizar", "automate", "automation", "automatico", "auto"],
    ["disenador", "disenadores", "designer", "designers", "creador", "creadores", "creator", "creators", "maker", "makers"],
    ["regalia", "regalias", "royalty", "royalties"], ["catalogo", "catalog", "catalogue"],
    ["anuncio", "anuncios", "ad", "ads", "advert", "creative", "creatives", "creativo", "creativos"],
    ["logo", "logos", "logotipo", "logotipos", "isotipo", "isologo"], ["oficial", "official"],
]
_STOP = set("""a an and are as at be by de del el en es for from how i in is it la las los lo me my no o of on or para
por que qué se the to un una y ya we with this that what como cómo con su sus mi tu""".split())


def _alias_groups() -> list[list[str]]:
    groups = [list(g) for g in _DEFAULT_ALIASES]
    env = os.environ.get("JOURNAL_ALIASES", "")
    for g in env.split(";"):
        words = [w.strip().lower() for w in g.split(",") if w.strip()]
        if len(words) > 1:
            groups.append(words)
    if _CONFIG.exists():
        try:
            import tomllib
            for g in tomllib.loads(_CONFIG.read_text(encoding="utf-8")).get("aliases") or []:
                if isinstance(g, list) and len(g) > 1:
                    groups.append([str(w).lower() for w in g])
        except Exception:
            pass
    return groups


def _fold(w: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", w.lower()) if unicodedata.category(ch) != "Mn")


def _core_words(query: str) -> list[str]:
    """Query words, accents folded, stopwords dropped (kept if nothing else is left)."""
    words = [_fold(w) for w in re.findall(r"[A-Za-zÀ-ÿ0-9_.]+", query)]
    words = [w.replace(".", "") for w in words if w.replace(".", "")]
    return [w for w in words if w not in _STOP] or words


def _expand_terms(query: str) -> list[str]:
    """Query words plus their synonyms, accents folded, stopwords dropped (kept if nothing else is left)."""
    out: list[str] = []
    for w in _core_words(query):
        if w not in out:
            out.append(w)
        for g in _alias_groups():
            if w in g:
                for a in g:
                    if a not in out:
                        out.append(a)
    return out


def _extra_doc_paths() -> list[Path]:
    """Capability docs (what each tool can do) searched next to the journals. JOURNAL_EXTRA_DOCS
    (semicolon-separated globs) or config.toml `extra_docs = ["C:/path/*_CAPABILITIES.md"]`."""
    import glob
    pats = [x.strip() for x in os.environ.get("JOURNAL_EXTRA_DOCS", "").split(";") if x.strip()]
    if _CONFIG.exists():
        try:
            import tomllib
            pats += [str(x) for x in (tomllib.loads(_CONFIG.read_text(encoding="utf-8")).get("extra_docs") or [])]
        except Exception:
            pass
    seen, out = set(), []
    for pat in pats:
        for f in glob.glob(pat):
            fp = Path(f)
            key = os.path.normcase(os.path.realpath(fp))
            if fp.suffix.lower() == ".md" and fp.is_file() and key not in seen:
                seen.add(key)
                out.append(fp)
    return out


# Journal-class files ONLY: the single source of truth pattern
_JOURNAL_PATTERNS = [
    re.compile(r".*JOURNAL.*\.md$", re.IGNORECASE),
    re.compile(r".*_journal.*\.md$"),
    re.compile(r"journal\.md$", re.IGNORECASE),
]

# "fixtures": test copies of real journals (tests/fixtures/shapesmith_20261028 held a 10-28 snapshot of CREATIVE_HUB
# and VIBEDNA_FULL) were indexed as live journals, 52 stale entries in every map and reply check (found 2026-10-29).
_SKIP_DIRS = {"node_modules", ".next", ".git", "__pycache__", "_archive", "venv", ".venv", "dist", "build", "fixtures"}
# Throwaway git worktrees of a project ("vibedna-site-wt-audio", "-wt-perf") hold stale copies of its journals: every
# search showed the same journal three times (2026-10-30). They are skipped.
_SKIP_DIR_RX = re.compile(r"-wt-[\w.-]+$", re.I)


def _is_journal_name(name: str) -> bool:
    return any(pat.match(name) for pat in _JOURNAL_PATTERNS)


def _is_journal_path(p: Path) -> bool:
    """What the indexer treats as a journal, plus the folder journal_get installs into."""
    if p.suffix.lower() != ".md":
        return False
    low = str(p).replace("\\", "/").lower()
    # A file a website serves (public/installs/journal.md is the install guide of the journal tool) is never a
    # journal: it was mapped as the journal of a project "installs" and every read of public/installs/connector.md
    # stopped 3 times (JOURNAL_MCP_JOURNAL 2026-10-29 03:12 [bug], again 2026-10-30).
    if "/public/" in low:
        return False
    if _is_journal_name(p.name):
        return True
    if any(d in low for d in ("/journals-drafts/", "/journals-refined/", "/journals-products/")):
        return True
    try:
        return p.resolve().is_relative_to((_HOME / "library").resolve())
    except Exception:
        return False


# ─── Metadata + frontmatter ─────────────────────────────────────────────────
# Product/marketplace metadata columns (additive; the base `journals` table
# predates these). Frontmatter on a journal or skill populates them.
_META_COLS = [
    ("kind", "TEXT DEFAULT 'raw'"),          # raw | refined | skill
    ("title", "TEXT DEFAULT ''"),
    ("domain", "TEXT DEFAULT ''"),
    ("tier", "TEXT DEFAULT ''"),             # utility | playbook | domain-mastery
    ("tools", "TEXT DEFAULT ''"),
    ("tags", "TEXT DEFAULT ''"),
    ("description", "TEXT DEFAULT ''"),
    ("source_projects", "TEXT DEFAULT ''"),
    ("outcome", "TEXT DEFAULT ''"),
    ("version", "TEXT DEFAULT ''"),
    ("word_count", "INTEGER DEFAULT 0"),
]


# Obsidian frontmatter (2026-10-30): a live journal may start with a flat YAML block
#   ---\ntype: journal\nproject: x\ntags: [journal, project/x]\naliases: ["X journal"]\nupdated: ...\nentries: 12\n---
# Everything that reads "the top of the journal" (title, head, brief, aliases) starts after it.
_FM_KEY = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(.*)$")
_FM_ITEM = re.compile(r"^\s+-\s*(.*)$|^-\s+(.*)$")
_FM_INLINE_ITEM = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|([^,]+?))\s*(?:,|$)')


def _frontmatter_span(text: str) -> tuple[int, int]:
    """(first line, end char) of a leading frontmatter block: lines[0:first] are the block (both '---'
    lines included) and text[end:] is the journal after it. (0, 0) when there is none. A leading '---'
    counts only when a closing '---' follows, at least one line is a key and every line between is a key, a
    list item or blank, so a journal that opens with a horizontal rule (or a rule, an H1, a rule) is never cut."""
    lead = 1 if text.startswith("\ufeff") else 0
    if not text.startswith("---", lead):
        return 0, 0
    lines = text[lead:].splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return 0, 0
    pos = lead + len(lines[0])
    keys = 0
    for i, ln in enumerate(lines[1:], 1):
        s = ln.strip()
        pos += len(ln)
        if s in ("---", "..."):
            return (i + 1, pos) if keys else (0, 0)
        if _FM_KEY.match(s):
            keys += 1
        elif s and not _FM_ITEM.match(ln.rstrip("\r\n")):
            return 0, 0
    return 0, 0


def _strip_frontmatter(text: str) -> str:
    """The journal without its leading frontmatter block (the text itself when there is none)."""
    _, end = _frontmatter_span(text)
    return text[end:].lstrip("\r\n") if end else text


def _blank_frontmatter(text: str) -> str:
    """The journal with its frontmatter lines emptied: same line numbers, nothing of the block left to index."""
    n, _ = _frontmatter_span(text)
    if not n:
        return text
    lines = text.splitlines()
    return "\n".join([""] * n + lines[n:]) + ("\n" if text.endswith("\n") else "")


def _fm_unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
        return v.replace('\\"', '"') if v and '"' in v else v
    return v


def parse_frontmatter_lists(text: str) -> dict[str, list[str]]:
    """Every frontmatter key as a list of values: 'tags: [a, "b c"]' and a block list ('tags:' then
    '  - a' lines) give ['a', 'b c']; a scalar gives [value]; an empty key gives []. Keys are lowercased.
    {} when the journal has no frontmatter. Other modules (the quick map) call this for aliases/tags."""
    n, _ = _frontmatter_span(text)
    if not n:
        return {}
    out: dict[str, list[str]] = {}
    key = ""
    for ln in text.lstrip("\ufeff").splitlines()[1:n - 1]:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        it = _FM_ITEM.match(ln)
        if it and key:
            v = _fm_unquote(it.group(1) if it.group(1) is not None else it.group(2) or "")
            if v:
                out[key].append(v)
            continue
        m = _FM_KEY.match(s)
        if not m:
            continue
        key = m.group(1).lower()
        raw = m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            vals = []
            for q, sq, bare in _FM_INLINE_ITEM.findall(raw[1:-1]):
                v = q.replace('\\"', '"') if q else (sq or bare.strip())
                if v:
                    vals.append(v)
            out[key] = vals
        else:
            out[key] = [_fm_unquote(raw)] if raw else []
    return out


def _parse_frontmatter(text: str) -> dict:
    """The frontmatter as a flat dict of strings (lists joined with ', '). {} if none."""
    return {k: ", ".join(v) for k, v in parse_frontmatter_lists(text).items()}


def _first_h1(text: str) -> str:
    for line in _strip_frontmatter(text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _head(text: str) -> str:
    """What the index stores as a journal's head: its first 500 characters after the frontmatter."""
    return _strip_frontmatter(text)[:500]


def _count_entries(text: str) -> int:
    """Dated '## YYYY-MM-DD' headings outside code fences: the frontmatter's entries: value."""
    n, fence = 0, False
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            fence = not fence
        elif not fence and _DATED_H2.match(ln):
            n += 1
    return n


def _refresh_frontmatter(text: str, now: Optional[datetime.datetime] = None) -> str:
    """After a write: when the journal has frontmatter, rewrite only the values of its updated: (local time,
    the clock of entry headings) and entries: lines, in place. Key order, other keys and a journal without
    frontmatter stay exactly as they were (this never adds a block)."""
    n, end = _frontmatter_span(text)
    if not n:
        return text
    now = (now or datetime.datetime.now()).replace(second=0, microsecond=0)
    block, rest = text[:end], text[end:]
    count = _count_entries(rest)

    def fix(m: re.Match) -> str:
        k = m.group(2).lower()
        val = now.isoformat() if k == "updated" else str(count)
        return f"{m.group(1)}{m.group(2)}:{m.group(3)}{val}{m.group(4)}"

    block = re.sub(r"(?m)^()(updated|entries)[ \t]*:([ \t]*)[^\r\n]*?([ \t]*\r?)$", fix, block)
    return block + rest


def _atomic_write(path: Path, text: str) -> None:
    """Write a journal so no reader ever sees half of it: a temp file in the same folder, then os.replace.
    Falls back to an in-place write when the replace is refused (Windows: another process has the file open;
    POSIX: the file belongs to another user, and a replace would change its owner, see the 2026-10-29
    root-owned files lesson). A read-only journal still raises PermissionError for the caller."""
    if path.exists() and not os.access(path, os.W_OK):
        raise PermissionError(f"read-only: {path}")
    same_owner = True
    if hasattr(os, "getuid") and path.exists():
        try:
            same_owner = path.stat().st_uid == os.getuid()
        except OSError:
            same_owner = False
    if same_owner:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:   # same newline handling as write_text
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():
                try:
                    import shutil
                    shutil.copymode(path, tmp)
                except OSError:
                    pass
            for i in range(5):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    time.sleep(0.05 * (i + 1))
        except OSError:
            pass
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    path.write_text(text, encoding="utf-8")


def _classify_kind(path: str, meta: dict) -> str:
    k = (meta.get("kind") or "").lower()
    if k in ("raw", "refined", "skill"):
        return k
    # A live journal's Obsidian block says type: journal; it never turns it into a product or a skill.
    if (meta.get("type") or "").lower() == "journal":
        return "raw"
    low = path.replace("\\", "/").lower()
    if "/skills/" in low:
        return "skill"
    if "/journals-drafts/" in low or "/journals-refined/" in low or "/journals-products/" in low:
        return "refined"
    return "raw"


# ─── Schema ─────────────────────────────────────────────────────────────────
_SCHEMA_READY = False
_READ_CAP_KB = 200   # journal_read with no max_kb returns the section index above this size


def _conn():
    """Open the shared index. Several AI sessions run their own copy of
    this server against the same index.sqlite, so: long busy timeout, WAL
    (readers never wait on a writer), and schema/migrations once per process
    instead of a write transaction on every call. Callers MUST close the
    connection in a finally block: a connection left open mid-write held the
    lock for hours and blocked every session (30/09)."""
    global _SCHEMA_READY
    c = sqlite3.connect(str(_DB), timeout=30)
    try:
        c.execute("PRAGMA busy_timeout=30000")
        if not _SCHEMA_READY:
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            _ensure_schema(c)
            _SCHEMA_READY = True
    except Exception:
        c.close()
        raise
    return c


def _ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS journals (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        project TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0,
        mtime REAL DEFAULT 0,
        indexed_at REAL DEFAULT 0,
        head TEXT DEFAULT ''
    )""")
    # Additive migration: add product/marketplace metadata columns if missing.
    have = {row[1] for row in c.execute("PRAGMA table_info(journals)").fetchall()}
    for col, decl in _META_COLS:
        if col not in have:
            try:
                c.execute(f"ALTER TABLE journals ADD COLUMN {col} {decl}")
            except Exception:
                pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_name ON journals(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_project ON journals(project)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_mtime ON journals(mtime DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_kind ON journals(kind)")
    # When the searchable text was last read, kept apart from mtime: older copies of this server update
    # mtime on append without re-reading the text, so mtime alone can't tell if the text is current.
    try:
        c.execute("ALTER TABLE journals ADD COLUMN fts_mtime REAL DEFAULT 0")
    except Exception:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_domain ON journals(domain)")
    # Full-text search index (content + name + project), porter-stemmed.
    try:
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS journals_fts USING fts5("
                  "path UNINDEXED, name, project, content, tokenize='porter unicode61')")
    except Exception:
        pass
    # Entry-level index: one row per section/entry (split at ## and ### headings), so a matching
    # entry inside a long journal ranks on its own merit instead of being crushed by the length
    # of the whole file. entries_meta records when each journal's entries were last read; it is kept
    # apart from fts_mtime because older copies of this server refresh journals_fts only.
    try:
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5("
                  "path UNINDEXED, line UNINDEXED, heading, body, tokenize='porter unicode61')")
        c.execute("CREATE TABLE IF NOT EXISTS entries_meta (path TEXT PRIMARY KEY, mtime REAL DEFAULT 0)")
    except Exception:
        pass
    c.commit()


_ENTRY_HEAD = re.compile(r"^#{2,3}\s+(.+?)\s*#*\s*$")
_ENTRY_MAX_LINES = 60


def _split_entries(text: str) -> list[tuple[int, str, str]]:
    """(line, heading, body) chunks of a journal: one per ## or ### heading, text before the first heading
    is its own chunk, and a section longer than _ENTRY_MAX_LINES is cut into chunks that keep its heading.
    line is 1-based (the heading line, or where a continuation chunk starts). Headings inside code fences
    do not split. A frontmatter block is never part of a chunk (its lines are emptied, line numbers kept)."""
    lines = _blank_frontmatter(text).splitlines()
    # (line of the chunk, heading, line where its body starts, body lines)
    raw: list[tuple[int, str, int, list[str]]] = [(1, _first_h1(text) or "", 1, [])]
    fence = False
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else _ENTRY_HEAD.match(ln)
        if m:
            raw.append((i, m.group(1).strip(), i + 1, []))
        else:
            raw[-1][3].append(ln)
    out: list[tuple[int, str, str]] = []
    for line, heading, start, body in raw:
        if not any(b.strip() for b in body) and (not heading or line == 1):
            continue
        for k in range(0, max(len(body), 1), _ENTRY_MAX_LINES):
            part = "\n".join(body[k:k + _ENTRY_MAX_LINES])
            if k and not part.strip():
                continue
            out.append((line if k == 0 else start + k, heading, part))
    return out


def _index_entries(c, path: str, text: str, mtime: float) -> None:
    """Replace one journal's rows in the entry index."""
    try:
        c.execute("DELETE FROM entries_fts WHERE path = ?", (path,))
        c.executemany("INSERT INTO entries_fts(path, line, heading, body) VALUES(?,?,?,?)",
                      [(path, ln, h, b) for ln, h, b in _split_entries(text)])
        c.execute("INSERT INTO entries_meta(path, mtime) VALUES(?,?) "
                  "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime", (path, mtime))
    except Exception:
        pass
    # Open plans ("NOT deployed", "requested from", "planned"...) mined from the same text, for the quick map
    # (2026-10-26). Optional: a copy without quickmap.py indexes exactly as before.
    try:
        import quickmap
        quickmap.index_plans(c, path, _blank_frontmatter(text), mtime)
    except Exception:
        pass


def _drop_entries(c, path: str) -> None:
    try:
        c.execute("DELETE FROM entries_fts WHERE path = ?", (path,))
        c.execute("DELETE FROM entries_meta WHERE path = ?", (path,))
    except Exception:
        pass


def _walk_md(root: Path):
    """Every .md file under root, never entering a skipped folder. rglob walked all of node_modules
    before filtering, which made a rescan of a big projects folder take many minutes."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not _SKIP_DIR_RX.search(d)]
        for f in filenames:
            if f.lower().endswith(".md"):
                yield Path(dirpath) / f


def _scan_root(root: Path, results: list):
    """Walk a root dir; index journal-named files, refined products, and skills."""
    try:
        for p in _walk_md(root):
            name = p.name
            low = str(p).replace("\\", "/").lower()
            journal_named = any(pat.match(name) for pat in _JOURNAL_PATTERNS)
            # Product content lives under a journals-drafts/refined/products tree only.
            # (A bare "/skills/" match anywhere over-catches unrelated repo folders.)
            in_product_dir = ("/journals-drafts/" in low or "/journals-refined/" in low
                              or "/journals-products/" in low)
            if not (journal_named or in_product_dir):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                st = p.stat()
            except Exception:
                continue
            results.append({
                "path": str(p),
                "name": name,
                "project": p.parent.name if p.parent != root else "_root",
                "size_bytes": st.st_size,
                "mtime": st.st_mtime,
                **_meta_fields(str(p), text, name),
                "word_count": len(text.split()),
                "content": text,
            })
    except Exception:
        pass


_META_FIELDS = ("kind", "title", "domain", "tier", "tools", "tags", "description", "source_projects", "outcome", "version")


def _meta_fields(path: str, text: str, name: str) -> dict:
    """The metadata columns of one journal, the same for a full rescan and a single-journal reindex."""
    meta = _parse_frontmatter(text)
    out = {k: meta.get(k, "") for k in _META_FIELDS}
    out["kind"] = _classify_kind(path, meta)
    out["title"] = meta.get("title") or _first_h1(text) or name
    return out


def _reindex_path(c, path: str) -> bool:
    """Re-read one journal into the search index (metadata + full text). Returns False if it is gone."""
    # One file can be written two ways on Windows (short 8.3 names, case): match the stored spelling,
    # or the same journal ends up indexed twice.
    real = os.path.normcase(os.path.realpath(path))
    for (stored,) in c.execute("SELECT path FROM journals").fetchall():
        if stored != path and os.path.normcase(os.path.realpath(stored)) == real:
            path = stored
            break
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        st = p.stat()
    except Exception:
        c.execute("DELETE FROM journals WHERE path = ?", (path,))
        try:
            c.execute("DELETE FROM journals_fts WHERE path = ?", (path,))
        except Exception:
            pass
        _drop_entries(c, path)
        return False
    row = c.execute("SELECT name, project, kind FROM journals WHERE path = ?", (path,)).fetchone()
    name, project, kind = (row if row else (p.name, p.parent.name, ""))
    # Same metadata as a full rescan (2026-10-30): a frontmatter edited between rescans showed up in search
    # only 15 minutes later. An extra doc (kind "doc") keeps its kind; only its title follows the file.
    meta = _meta_fields(path, text, name)
    if kind == "doc":
        meta = {**{k: "" for k in _META_FIELDS}, "kind": "doc", "title": _first_h1(text) or name}
    sets = ", ".join(f"{k}=?" for k in _META_FIELDS)
    c.execute(f"UPDATE journals SET size_bytes=?, mtime=?, fts_mtime=?, indexed_at=?, head=?, word_count=?, {sets} WHERE path=?",
              (st.st_size, st.st_mtime, st.st_mtime, time.time(), _head(text), len(text.split()),
               *(meta[k] for k in _META_FIELDS), path))
    try:
        c.execute("DELETE FROM journals_fts WHERE path = ?", (path,))
        c.execute("INSERT INTO journals_fts(path, name, project, content) VALUES(?,?,?,?)", (path, name, project, text))
    except Exception:
        pass
    _index_entries(c, path, text, st.st_mtime)
    return True


def _rescan_due() -> bool:
    stamp = _HOME / "last_full_scan"
    try:
        minutes = float(os.environ.get("JOURNAL_RESCAN_MINUTES", "10"))
    except ValueError:
        minutes = 10.0
    try:
        if not stamp.exists():   # the clock starts at the first sync: a fresh index was just built from the roots
            stamp.write_text(str(int(time.time())), encoding="utf-8")
            return minutes <= 0
        if time.time() - stamp.stat().st_mtime < minutes * 60:
            return False
        stamp.write_text(str(int(time.time())), encoding="utf-8")   # stamped first: parallel callers do not all rescan
    except OSError:
        return False
    return True


def _sync_changed(c) -> int:
    """Search must never answer from an old copy. Every indexed journal whose file changed since it was
    indexed (appends, section updates, edits made outside this server, other sessions) is re-read before
    searching. Only file times are checked, so this stays fast. New journal files in the roots are found by a
    full rescan when the last one is older than JOURNAL_RESCAN_MINUTES (default 10)."""
    if _rescan_due():
        _index_refresh_internal()
        return 1
    changed = 0
    try:
        ent = dict(c.execute("SELECT path, mtime FROM entries_meta").fetchall())
    except Exception:
        ent = {}
    rows = c.execute("SELECT path, fts_mtime FROM journals").fetchall()
    for path, mtime in rows:
        try:
            m = os.path.getmtime(path)
        except OSError:
            _reindex_path(c, path)
            changed += 1
            continue
        # The entry index has its own read time: another (older) server copy may have refreshed the
        # whole-file text without touching the entries.
        if abs(m - (mtime or 0)) > 1e-6 or abs(m - (ent.get(path) or 0)) > 1e-6:
            _reindex_path(c, path)
            c.commit()   # one journal per write transaction (see _index_refresh_internal)
            changed += 1
    live = {p for p, _ in rows}
    for p in ent:
        if p not in live:
            _drop_entries(c, p)
            changed += 1
    if changed:
        c.commit()
    return changed


def _index_refresh_internal() -> dict:
    """Rebuild the index (metadata + FTS) by scanning all roots."""
    roots = _default_roots()
    found = []
    for r in roots:
        if r.is_dir():
            _scan_root(r, found)
    have = {os.path.normcase(os.path.realpath(j["path"])) for j in found}
    for fp in _extra_doc_paths():
        if os.path.normcase(os.path.realpath(fp)) in have:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            st = fp.stat()
        except Exception:
            continue
        found.append({"path": str(fp), "name": fp.name, "project": fp.parent.name, "size_bytes": st.st_size,
                      "mtime": st.st_mtime, "kind": "doc", "title": _first_h1(text) or fp.name, "domain": "", "tier": "",
                      "tools": "", "tags": "", "description": "", "source_projects": "", "outcome": "", "version": "",
                      "word_count": len(text.split()), "content": text})
    c = _conn()
    try:
        now = time.time()
        # Incremental, short write transactions (2026-10-26): the old rebuild deleted every index table and
        # re-inserted 290 journals inside ONE transaction, holding the write lock ~25 s every 15 minutes, so
        # any other writer (the quick map's plans sync, an append) hit busy_timeout: "database is locked".
        # Now only journals whose text changed are re-read, and each is committed on its own.
        try:
            known = dict(c.execute("SELECT path, fts_mtime FROM journals").fetchall())
            ent = dict(c.execute("SELECT path, mtime FROM entries_meta").fetchall())
        except Exception:
            known, ent = {}, {}
        for j in found:
            content = j.get("content", "")
            head = _head(content)
            unchanged = (abs((known.get(j["path"]) or 0) - j["mtime"]) < 1e-6
                         and abs((ent.get(j["path"]) or 0) - j["mtime"]) < 1e-6)
            c.execute(
                "INSERT INTO journals(path, name, project, size_bytes, mtime, indexed_at, head, "
                "kind, title, domain, tier, tools, tags, description, source_projects, outcome, version, word_count) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET name=excluded.name, project=excluded.project, "
                "size_bytes=excluded.size_bytes, mtime=excluded.mtime, indexed_at=excluded.indexed_at, "
                "head=excluded.head, kind=excluded.kind, title=excluded.title, domain=excluded.domain, "
                "tier=excluded.tier, tools=excluded.tools, tags=excluded.tags, description=excluded.description, "
                "source_projects=excluded.source_projects, outcome=excluded.outcome, version=excluded.version, "
                "word_count=excluded.word_count",
                (j["path"], j["name"], j["project"], j["size_bytes"], j["mtime"], now, head,
                 j["kind"], j["title"], j["domain"], j["tier"], j["tools"], j["tags"],
                 j["description"], j["source_projects"], j["outcome"], j["version"], j["word_count"]),
            )
            if unchanged:
                continue
            c.execute("UPDATE journals SET fts_mtime = ? WHERE path = ?", (j["mtime"], j["path"]))
            try:
                c.execute("DELETE FROM journals_fts WHERE path = ?", (j["path"],))
                c.execute("INSERT INTO journals_fts(path, name, project, content) VALUES(?,?,?,?)",
                          (j["path"], j["name"], j["project"], content))
            except Exception:
                pass
            _index_entries(c, j["path"], content, j["mtime"])
            c.commit()   # one journal per write transaction: other writers get in between
        # Prune entries whose files vanished
        existing_paths = {j["path"] for j in found}
        for (p,) in c.execute("SELECT path FROM journals").fetchall():
            if p not in existing_paths:
                c.execute("DELETE FROM journals WHERE path = ?", (p,))
                try:
                    c.execute("DELETE FROM journals_fts WHERE path = ?", (p,))
                except Exception:
                    pass
                _drop_entries(c, p)
        c.commit()
    finally:
        c.close()
    kinds: dict = {}
    for j in found:
        kinds[j["kind"]] = kinds.get(j["kind"], 0) + 1
    return {
        "roots_scanned": [str(r) for r in roots if r.is_dir()],
        "journals_indexed": len(found),
        "by_kind": kinds,
        "db_path": str(_DB),
    }


_RESOLVE_NOTE = {"msg": ""}
_ALIAS_LINE = re.compile(r"^\s*(?:also known as|aka|alias(?:es)?|tambi[eé]n conocido como|nombres? anteriores?)\s*:\s*(.+)$", re.I | re.M)


_NAME_ALIASES = "project, journal, name, path"


def _first(*vals) -> str:
    """First non-empty argument, stripped. AI agents often send the journal or the text under another name."""
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _missing(arg: str, example: str, as_dict: bool = True):
    """One plain line instead of a validation dump: names the missing argument and shows a working call."""
    msg = f"Missing '{arg}'. Example: {example}"
    return {"error": msg} if as_dict else msg


def _need_journal(name_or_path, project, journal, name, path, tool: str, as_dict: bool = True):
    """Resolve the journal argument from name_or_path or its aliases. Returns (value, error-or-None)."""
    val = _first(name_or_path, project, journal, name, path)
    if val:
        return val, None
    return "", _missing("name_or_path", f'{tool}(name_or_path="MYPROJECT_JOURNAL.md", ...) '
                        f"(aliases accepted: {_NAME_ALIASES})", as_dict)


def _not_found(name_or_path: str, hint: str = "") -> str:
    """The error for a journal that could not be picked: says why (none, or several) and what to pass."""
    why = _RESOLVE_NOTE.get("msg") or f"Journal not found: '{name_or_path}'."
    return why + (f" {hint}" if hint and "matches" not in why else "")


def _journal_aliases(path: str, head: str) -> list[str]:
    """Other names of a project, from a line near the top: 'Also known as: NewName, newname.com'."""
    text = head or ""
    if len(text) < 3000:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(3000)
        except OSError:
            pass
    # Obsidian frontmatter: 'aliases: ["X journal", Y]' (or a block list) is a list, never one bracketed name.
    out = list(parse_frontmatter_lists(text).get("aliases", []))
    text = _strip_frontmatter(text)
    for m in _ALIAS_LINE.finditer(text):
        out += [a.strip(" `*_.") for a in re.split(r"[,;/]| y | and ", m.group(1)) if a.strip(" `*_.")]
    # A title that names the project twice counts too: "# OLD PROJECT NAME = NewName (newname.com)"
    h1 = re.search(r"^# (.+)$", text, re.M)
    if h1 and " = " in h1.group(1):
        out += [a.strip(" `*_.:") for a in re.split(r" = |[()]", h1.group(1)) if a.strip(" `*_.:")]
    return out


def _resolve(name_or_path: str) -> Optional[dict]:
    """Find ONE journal by full path, exact name, 'PROJECT/NAME', a project alias, or a fuzzy name.
    It never guesses: when several journals fit equally (several projects can each have a SOCIAL_JOURNAL.md,
    and a fuzzy name once wrote into the wrong project's journal), it returns None and _not_found() lists them."""
    _RESOLVE_NOTE["msg"] = ""
    if not name_or_path:
        return None
    nq = name_or_path.strip()
    # Exact path, journal files only. Read and append take a path, and a path to any
    # file (a key, a .env) is how a misled AI would read or write outside the journals.
    if Path(nq).is_file():
        p = Path(nq).resolve()
        return {"path": str(p)} if _is_journal_path(p) else None
    c = _conn()
    try:
        cols = "path, name, project, size_bytes, mtime, head"
        proj_hint = ""
        if ("/" in nq or "\\" in nq) and not Path(nq).is_absolute():
            proj_hint, nq = re.split(r"[/\\]", nq, maxsplit=1)
        rows = c.execute(f"SELECT {cols} FROM journals WHERE LOWER(name) = LOWER(?)", (nq,)).fetchall()
        stem = re.sub(r"[\s-]+", "_", nq.strip()).upper().removesuffix(".MD")
        if not rows:
            rows = c.execute(f"SELECT {cols} FROM journals WHERE UPPER(name) IN (?, ?)",
                             (stem + ".MD", stem + "_JOURNAL.MD")).fetchall()
        if not rows:
            want = _fold(nq)
            rows = [r for r in c.execute(f"SELECT {cols} FROM journals").fetchall()
                    if any(_fold(a) == want for a in _journal_aliases(r[0], r[5]))]
        if not rows:
            like = f"%{nq}%"
            rows = c.execute(f"SELECT {cols} FROM journals WHERE LOWER(name) LIKE LOWER(?) OR LOWER(project) LIKE LOWER(?) "
                             "OR LOWER(name) LIKE LOWER(?) ORDER BY mtime DESC LIMIT 12",
                             (like, like, f"%{stem}%")).fetchall()
        if proj_hint:
            rows = [r for r in rows if proj_hint.lower() in (r[2] or "").lower() or proj_hint.lower() in r[0].lower()]
        if not rows:
            return None
        if len(rows) > 1:
            # A journal whose project folder is the name asked for, or whose name is exactly <NAME>_JOURNAL.md, wins.
            best = [r for r in rows if (r[2] or "").lower() == nq.lower() or r[1].upper() in (stem + ".MD", stem + "_JOURNAL.MD")]
            if len(best) == 1:
                rows = best
        if len({os.path.normcase(os.path.realpath(r[0])) for r in rows}) > 1:
            opts = "; ".join(f"{r[1]} in {r[2]} ({r[0]})" for r in rows[:8])
            _RESOLVE_NOTE["msg"] = (f"'{name_or_path}' matches {len(rows)} journals, not picking one: {opts}. "
                                    "Pass the full path or PROJECT/NAME (e.g. 'SHOP/SOCIAL_JOURNAL.md').")
            return None
        r = rows[0]
        return {"path": r[0], "name": r[1], "project": r[2], "size_bytes": r[3], "mtime": r[4]}
    finally:
        c.close()


# ─── Tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def journal_index_refresh() -> dict:
    """
    Rescan all configured roots, refresh the journal index.
    Run this when you've created new journals or want fresh state.
    Returns: roots scanned, journals found, DB path.
    """
    return _index_refresh_internal()


@mcp.tool()
def journal_list(project: str = "", last_days: int = 0, limit: int = 50) -> dict:
    """
    List journals in the library.

    project: substring filter on project folder name or journal file name (e.g. 'SHOP', 'BILLING', '').
        Journals directly in a root folder have project "_root"; their file name is matched too.
    last_days: only journals modified in last N days (0 = all)
    limit: max results

    Auto-refreshes index if it's empty.
    """
    c = _conn()
    try:
        if c.execute("SELECT COUNT(*) FROM journals").fetchone()[0] == 0:
            _index_refresh_internal()
        where = []
        params: list = []
        if project:
            c.create_function("pmatch", 3, lambda p, n, q: int(_project_match(p, n, q)), deterministic=True)
            where.append("pmatch(project, name, ?)")
            params.append(project)
        if last_days > 0:
            where.append("mtime >= ?")
            params.append(time.time() - last_days * 86400)
        sql = "SELECT path, name, project, size_bytes, mtime FROM journals"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY mtime DESC LIMIT ?"
        params.append(limit)
        rows = c.execute(sql, params).fetchall()
    finally:
        c.close()
    now = time.time()
    return {
        "count": len(rows),
        "filters": {"project": project, "last_days": last_days},
        "journals": [{
            "name": r[1],
            "project": r[2],
            "kb": round(r[3] / 1024, 1),
            "updated_ago": _ago(now - r[4]),
            "path": r[0],
        } for r in rows],
    }


def _ago(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)}s ago"
    if seconds < 3600: return f"{int(seconds/60)}min ago"
    if seconds < 86400: return f"{int(seconds/3600)}h ago"
    return f"{int(seconds/86400)}d ago"


@mcp.tool()
def journal_read(name_or_path: str = "", max_kb: int = 0, project: str = "", journal: str = "", name: str = "", path: str = "",
                 offset: int = 0, limit: int = 0, start_line: int = 0, end_line: int = 0) -> str:
    """
    Read a journal's full contents.

    name_or_path: full path OR short name (fuzzy). E.g. "SHOP", "SHOP_JOURNAL.md", "BOTS\\SWEEPER_FULL_JOURNAL.md"
    max_kb: if > 0, cap response at this many KB (returns tail). 0 = full file.
    offset / limit (like Read) or start_line / end_line (1-based, inclusive): return only that line range, numbered.
    offset=189, limit=3 returns lines 189-191. A range ignores max_kb and the size cap.

    Returns the raw markdown.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_read", False)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return _not_found(name_or_path, "Try journal_list() to see what's available.")
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading {j['path']}: {e}"
    if offset > 0 or limit > 0 or start_line > 0 or end_line > 0:
        lines = content.splitlines()
        a = start_line if start_line > 0 else (offset if offset > 0 else 1)
        if end_line > 0:
            b = end_line
        elif limit > 0:
            b = a + limit - 1
        else:
            b = a + 199
        b = min(b, len(lines))
        if a > len(lines):
            return f"# Journal: {j.get('name', name_or_path)}\n_Path: {j['path']}_\n\nLine {a} is past the end ({len(lines)} lines)."
        body = "\n".join(f"{n}\t{lines[n - 1]}" for n in range(a, b + 1))
        return f"# Journal: {j.get('name', name_or_path)}\n_Path: {j['path']}_ (lines {a}-{b} of {len(lines)})\n\n{body}"
    if max_kb > 0 and len(content) > max_kb * 1024:
        content = "... [TRUNCATED: older content above] ...\n\n" + content[-max_kb * 1024:]
    elif max_kb <= 0 and len(content) > _READ_CAP_KB * 1024:
        # No size asked and the journal is big (one reached 2.1M characters in a single reply, 2026-10-26):
        # return its index, not its text. journal_read_section / max_kb read the part you need.
        heads = [(n, ln.strip()[:120]) for n, ln in enumerate(content.splitlines(), 1) if ln.startswith("## ")]
        keep = heads[:60] + ([("...", f"[{len(heads) - 120} sections not listed: journal_list_sections]")] if len(heads) > 120 else []) + heads[-60:] if len(heads) > 120 else heads
        index = "\n".join(f"- line {n}: {h}" for n, h in keep)
        return (f"# Journal: {j.get('name', name_or_path)}\n_Path: {j['path']}_\n\n"
                f"This journal is {len(content) // 1024} KB, too long to return whole (cap {_READ_CAP_KB} KB). "
                f"Section index ({len(heads)} sections); read one with journal_read_section(name, section), "
                f"the newest part with journal_read(name, max_kb=N), or search with journal_search.\n\n{index}")
    return f"# Journal: {j.get('name', name_or_path)}\n_Path: {j['path']}_\n\n{content}"


def _outbox_dir() -> Path:
    return Path(os.environ.get("JOURNAL_OUTBOX", "").strip() or str(Path.home() / "journal-outbox")).expanduser()


def _queue_for_master(path: Path, entry: str, tag: str, section_header: str) -> dict:
    """The journal is a read-only copy (a mirror some sync overwrites): queue the entry as one JSON line in
    $JOURNAL_OUTBOX/<journal file name>.jsonl instead of failing, so whoever owns the master copy can merge it."""
    import uuid
    rec = {"id": uuid.uuid4().hex, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "journal": path.name, "path": str(path), "tag": tag.strip(), "entry": entry.strip(),
           "section_header": section_header.strip(),
           "from_role": os.environ.get("JOURNAL_FROM", "").strip()}
    box = _outbox_dir()
    try:
        box.mkdir(parents=True, exist_ok=True)
        target = box / (path.name + ".jsonl")
        with target.open("a", encoding="utf-8") as f:
            try:
                import fcntl  # the merger rewrites this file under the same lock
                fcntl.flock(f, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"error": f"The journal is read-only and the outbox write failed: {e}"}
    return {"ok": True, "queued": True, "outbox": str(target), "id": rec["id"],
            "message": "queued for the master journal (it lands on the next sync)"}


# State claims without evidence (real case 2026-10-30): a 2026-10-29 AI_TEAM_JOURNAL entry said the Launch Desk
# Whop business had "payouts INACTIVE until the owner verifies identity once: https://whop.com/...?verify=true";
# identity had been approved since July and nobody checked. journal_append still writes such an entry and returns
# a warning when a line states an external STATE of an account, payment, service or bot and neither that line nor
# the next one says how it was checked. That real line carried a URL (the fix-it link) and the entry carried UTC
# times, so a bare URL or a time anywhere in the entry is not evidence: a URL counts only as a source ("read from",
# "per", "GET ..."), and the evidence must sit next to the claim.
_STATE_SUBJECT = re.compile(
    r"\b(?:accounts?|payouts?|payments?|checkout|billing|invoices?|balances?|wallets?|bank|merchant|stripe|whop|"
    r"gumroad|paypal|payoneer|lemon\s?squeezy|kyc|identity|verification|subscriptions?|stores?|shops?|listings?|"
    r"orders?|sales|services?|servers?|api|endpoints?|webhooks?|domains?|dns|websites?|site|bots?|workers?|"
    r"crons?|daemons?|campaigns?|cuentas?|pagos?|cobros?)\b", re.I)
_COPULA = (r"(?:is|are|was|were|be|been|being|now|still|stays?|stayed|remains?|remained|went|goes|gone|became|"
           r"becomes|currently|back|got|gets)")
_STATE_CLAIM = re.compile(
    r"\binactive\b|\bdeactivated\b"
    rf"|\b{_COPULA}\s+(?:not\s+|now\s+|still\s+|already\s+|fully\s+)?active\b"
    r"|\bunverified\b|\bnot\s+(?:yet\s+)?verified\b"
    r"|\b(?:is|are|was|were|been|got|now|still|already|fully|identity|account)\s+verified\b"
    r"|\b(?:suspended|paused)\b(?!\s+nothing\b)"
    rf"|\b{_COPULA}\s+(?:not\s+|now\s+|still\s+|already\s+)?live\b"
    rf"|\b{_COPULA}\s+(?:not\s+|still\s+)?down\b"
    r"|\b(?:pending|awaiting)\s+(?:approval|review|verification|kyc)\b|\b(?:under|in)\s+review\b"
    r"|\bbalances?\s*(?:is|was|of|at|:|=)?\s*[$€£]?\s*\d|[$€£]\s?\d[\d.,]*\s+balance\b"
    r"|\b(?:0|zero)\s+(?:orders|sales|payouts|purchases|sign-?ups|subscribers|customers)\b"
    r"|\b(?:not\s+(?:yet\s+)?|never\s+)created\b"
    r"|\bblocked\b(?!\s+(?:on|nothing)\b|\s+by\s+(?:the\s+)?(?:owner|you|me|us)\b)", re.I)
# "Paused my 2 crons", "Done: suspended the old key", "we blocked the IP": the writer's own action (the verb opens
# the clause and has an object), not a claim about someone else's state. "Reddit blocked the server" still is one.
_OWN_VERBS = ("paused", "suspended", "blocked")
_OBJECT_AFTER = re.compile(r"\s+(?:the|my|our|its|their|his|her|all|both|every|each|it|them|\d+)\b", re.I)
_OWN_ACTION_PREFIX = re.compile(r"^\s*(?:[^:]{0,24}:\s*)?(?:(?:i|we|and|then|also|just|so)\s+)*$", re.I)
# Words before the state that make the sentence a plan, a condition, a question or a decision, not a fact.
_NOT_A_FACT = re.compile(r"\b(?:will|would|should|must|could|might|may|can|if|when|whenever|once|unless|plan|plans|"
                         r"planned|proposal|propose[sd]?|going\s+to|keep|leave|decide[sd]?|decision|want|wants|"
                         r"needs?\s+to|todo|next|what|why|how\s+to)\b", re.I)
_EVIDENCE = re.compile(
    r"\b(?:re-?)?(?:checked|measured)\b|\bread\s+live\b|\b(?:verified|confirmed)\s+(?:via|with|by|on|in|at|through|from)\b"
    r"|\bcurl\b|\bdate\s+-u\b|\bsystemctl\b|\bstatus:[^\n]*?\b\d{1,2}:\d{2}\b"
    r"|\b(?:read|from|per|source|via|checked|according\s+to|shows?|showed|says|said|returned|opened|fetched)\W+"
    r"(?:[\w-]+\W+){0,2}?https?://\S"
    r"|\b(?:via|from|through|per)\s+(?:the\s+)?(?:[\w-]+\s+)?API\b|\bAPI\s+(?:call|response|returned|says|said|shows|"
    r"showed|reports|reported|check)\b", re.I)
_EVIDENCE_CS = re.compile(r"\bGET\s+(?:/|https?:)")   # case-sensitive: an HTTP GET, not the verb "get"
_EVIDENCE_NEGATED = re.compile(r"(?:\bnot|\bnever|\bnobody|\bno\s+one|\bwithout|n't)\s+(?:\w+\s+){0,2}$", re.I)
STATE_CLAIM_WARNING = ("WARNING (the entry was written): it states an external state without saying how it was "
                       "checked: \"{claim}\". Add how and when it was checked (the command, API call or URL, and the "
                       "time), or mark the claim UNVERIFIED.")


def _has_evidence(text: str) -> bool:
    if _EVIDENCE_CS.search(text):
        return True
    for m in _EVIDENCE.finditer(text):
        if not _EVIDENCE_NEGATED.search(text[max(0, m.start() - 30):m.start()]):
            return True
    return False


def state_claim_warning(entry: str) -> str:
    """'' or the warning for an entry with a line that states an account / payment / service / bot STATE
    (inactive, verified, suspended, live, down, pending review, a balance, 0 orders, not created, blocked) and no
    evidence of how it was checked on that line or the next one. An UNVERIFIED tag (uppercase) silences it."""
    if not entry or "UNVERIFIED" in entry:
        return ""
    lines = entry.splitlines()
    for i, line in enumerate(lines):
        for sent in re.split(r"(?<=[.!?;])\s+", line):
            for m in _STATE_CLAIM.finditer(sent):
                if _NOT_A_FACT.search(sent[:m.start()]) or not _STATE_SUBJECT.search(sent):
                    continue
                if (m.group(0).lower() in _OWN_VERBS and _OBJECT_AFTER.match(sent, m.end())
                        and _OWN_ACTION_PREFIX.match(sent[:m.start()])):
                    continue
                if _has_evidence(line + "\n" + (lines[i + 1] if i + 1 < len(lines) else "")):
                    break
                claim = " ".join(sent.split()).strip(" -*#>").rstrip(".;:")
                return STATE_CLAIM_WARNING.format(claim=claim if len(claim) <= 140 else claim[:137] + "...")
    return ""


def _with_warning(res: dict, warning: str) -> dict:
    if warning and isinstance(res, dict) and "error" not in res:
        res["warning"] = warning
    return res


@mcp.tool()
def journal_append(name_or_path: str = "", entry: str = "", tag: str = "", section_header: str = "",
                   text: str = "", content: str = "", body: str = "", project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Append a timestamped entry to a journal. Most common operation.

    name_or_path: which journal (short name or path)
    entry: markdown content of the new entry
    tag: optional tag prefix (e.g. 'fix', 'incident', 'feature', 'decision')
    section_header: if set, wraps the entry under '## <section_header>' (creates section if not present)

    Format appended:
        ## <timestamp> [<tag>] <first-line-of-entry>
        <entry>
        ---

    A read-only journal (a mirror that a sync overwrites) is not an error: the entry is queued as one JSON line in
    $JOURNAL_OUTBOX (default ~/journal-outbox)/<journal file name>.jsonl for the master copy's owner to merge.

    An entry that states an external state (an account inactive or verified, a service down, a balance, 0 orders)
    with no word on how it was checked is still written, and the result carries a "warning": say how and when it
    was checked, or mark it UNVERIFIED. A frontmatter block keeps its keys; only updated: and entries: change.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_append", True)
    if err:
        return err
    entry = entry if entry.strip() else _first(text, content, body)
    if not entry:
        return _missing("entry", 'journal_append(name_or_path="MYPROJECT_JOURNAL.md", entry="what happened", tag="fix") (aliases accepted: text, content, body)')
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path, "Use journal_create to make a new one.")}
    warning = state_claim_warning(entry)
    path = Path(j["path"])
    if path.is_file() and not os.access(path, os.W_OK):
        return _with_warning(_queue_for_master(path, entry, tag, section_header), warning)
    try:
        existing = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    now = datetime.datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M")
    tag_part = f"[{tag.strip()}] " if tag.strip() else ""
    first_line = (entry.strip().split("\n", 1)[0])[:80]
    header = f"\n\n## {ts} {tag_part}{first_line}\n\n"
    body = entry.strip() + "\n\n---\n"
    new_content = _refresh_frontmatter(existing.rstrip() + header + body, now)
    try:
        _atomic_write(path, new_content)
    except PermissionError:
        return _with_warning(_queue_for_master(path, entry, tag, section_header), warning)
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    # Refresh this journal's index entry
    try:
        c = _conn()
        try:
            _reindex_path(c, str(path))
            c.commit()
        finally:
            c.close()
    except Exception:
        pass
    return _with_warning({"ok": True, "path": str(path), "appended_bytes": len(header) + len(body),
                          "new_size_kb": round(path.stat().st_size / 1024, 1)}, warning)


def _new_frontmatter(name: str, body: str = "") -> str:
    """The Obsidian block a new journal starts with (one fixed flat format, see _frontmatter_span)."""
    stem = re.sub(r"[_\s-]*JOURNAL$", "", Path(name).stem, flags=re.I) or Path(name).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "journal"
    label = " ".join(w.capitalize() for w in re.split(r"[_\s-]+", stem) if w).replace('"', "'")
    now = datetime.datetime.now().replace(second=0, microsecond=0).isoformat()
    return (f"---\ntype: journal\nproject: {slug}\nstatus: live\ntags: [journal, project/{slug}]\n"
            f'aliases: ["{label} journal"]\nupdated: {now}\nentries: {_count_entries(body)}\n---\n')


@mcp.tool()
def journal_create(name: str, project_dir: str, body: str = "") -> dict:
    """
    Create a new project journal. ONE journal per project = single source of truth.

    name: filename (e.g. 'CRYPTOMIND_JOURNAL.md'). Auto-appends .md if missing,
          auto-uppercases convention.
    project_dir: absolute path to the folder where it should live (usually the project root)
    body: initial markdown (optional, defaults to a scaffold with all standard sections)

    Default scaffold includes sections: Vision · Current state · Roadmap ·
    Decisions log · Incidents · Handoff for next session · Recent entries.
    Every new journal starts with an Obsidian frontmatter block (type, project, status, tags, aliases,
    updated, entries); journal_append and journal_update_section keep updated: and entries: current.
    """
    name = name.strip()
    if not name.endswith(".md"):
        name += ".md"
    if Path(name).name != name or not _is_journal_name(name):
        return {"error": f"name must be a plain journal file name like 'MYPROJECT_JOURNAL.md', got: {name}"}
    project = Path(project_dir).expanduser().resolve()
    if not project.is_dir():
        return {"error": f"project_dir does not exist: {project}"}
    target = project / name
    if target.exists():
        return {"error": f"Already exists: {target}. Use journal_append instead."}
    if not body.strip():
        title = name.replace(".md", "").replace("_", " ").title()
        body = f"""# {title}

_Created {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}_

The single source of truth for this project. Every decision, incident, fix,
roadmap update, and handoff lives here, not scattered across docs.

## Vision / Why this exists

_What this project is, what it's solving, who it's for._

## Current state

_Where the project is RIGHT NOW. Updated as state changes._

## Roadmap

_What's next, in priority order._

## Decisions log

_Architectural / strategic decisions with reasoning._

## Incidents

_Things that went wrong + root cause + fix._

## Already exists

_Built and working: extend these, never rebuild them. One line each (journal_capability_add)._

## Decided

_What the owner decided (product rules, names, prices, design and copy rules, "never X"): follow these, never re-propose them as new. One line each (journal_decision_add)._

## Handoff for next session

_Replaced whole at the end of every session: the task list (done / in progress / pending / blocked) and where it stopped._

## Recent entries

_Append-only timeline, newest at bottom. Use `journal_append` to add._

"""
    if not _frontmatter_span(body)[0]:
        body = _new_frontmatter(name, body) + body
    target.write_text(body, encoding="utf-8")
    try:
        st = target.stat()
        c = _conn()
        try:
            c.execute(
                "INSERT OR REPLACE INTO journals(path, name, project, size_bytes, mtime, indexed_at, head) "
                "VALUES(?,?,?,?,?,?,?)",
                (str(target), name, project.name, st.st_size, st.st_mtime, time.time(), _head(body)),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        pass
    return {"ok": True, "path": str(target), "size_kb": round(target.stat().st_size / 1024, 1)}


def _term_groups(query: str) -> list[list[str]]:
    """One group per query word: the word plus its synonyms, FTS-safe tokens only. Words that are
    synonyms of each other collapse into one group, so 'post publish' counts as one idea.
    Explicit groups: when the query has a "|", "a b|c d" is ONE idea whose alternatives are the phrases "a b" and
    "c d" (each alternative must appear as written, so a lone word from it does not count); separate ideas
    with ";" or ",". A part without "|" is read the usual way."""
    if "|" not in query:
        return _word_groups(query)
    groups: list[list[str]] = []
    for part in re.split(r"[;,]", query):
        if "|" in part:
            g: list[str] = []
            for alt in part.split("|"):
                words = [_fold(w).replace(".", "") for w in re.findall(r"[A-Za-zÀ-ÿ0-9_.]+", alt)]
                phrase = " ".join(w for w in words if w)
                if phrase and phrase not in g:
                    g.append(phrase)
            new = [t for t in g if re.fullmatch(r"[a-z0-9_ ]+", t)]
        else:
            new = None
        for grp in ([new] if new is not None else _word_groups(part)):
            if grp and not any(set(grp) == set(x) for x in groups):
                groups.append(grp)
    return groups


def _word_groups(query: str) -> list[list[str]]:
    groups: list[list[str]] = []
    for w in _core_words(query):
        g = [t for t in _expand_terms(w) if re.fullmatch(r"[a-z0-9_]+", t)]
        if g and not any(set(g) == set(x) for x in groups):
            groups.append(g)
    return groups


def _fts_or(terms: list[str]) -> str:
    return "(" + " OR ".join(f'"{t}"' for t in terms) + ")"


def _norm_label(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (s or "").lower()).strip()


def _project_match(project_label: str, file_name: str, needle: str) -> bool:
    """The project filter. Journals that sit directly in a root folder all carry the project label "_root",
    so a filter such as FORECAST_MARKETS matched nothing; it now also matches the journal's file name
    (FORECAST_MARKETS_JOURNAL.md). Case, "_", "-" and spaces are ignored."""
    n = _norm_label(needle)
    return not n or n in _norm_label(project_label) or n in _norm_label(file_name)


def _entry_search(c, groups: list[list[str]], project: str, kind: str, limit: int) -> list[dict]:
    """Rank journals by their best entries. An entry (section between ## / ### headings, long ones cut
    into ~60-line chunks) is scored on its own, so a perfect entry inside a 5,000-line journal is not
    buried by the length of the file. Order: how many query words the entry covers (words in the
    journal's name or project count too), then bm25 with the heading weighted far above the body.
    Recall stays OR + synonyms; entries that hit every word are fetched separately so they always
    make the candidate set."""
    filt, fargs = "", []
    if project or kind:
        conds = []
        if project:
            c.create_function("pmatch", 3, lambda p, n, q: int(_project_match(p, n, q)), deterministic=True)
            conds.append("pmatch(project, name, ?)")
            fargs.append(project)
        if kind:
            conds.append("LOWER(kind) = ?")
            fargs.append(kind.lower())
        filt = " AND path IN (SELECT path FROM journals WHERE " + " AND ".join(conds) + ")"
    meta = {}
    for path, name, proj, mt in c.execute("SELECT path, name, project, mtime FROM journals").fetchall():
        meta[path] = (name, proj or "", mt)
    # Query words found in the journal's own name or project (e.g. "shop" in SHOP_FULL_JOURNAL.md).
    name_hits: dict[str, set] = {}
    for path, (name, proj, _m) in meta.items():
        label = _fold(f"{name} {proj}")
        toks = set(re.split(r"[^a-z0-9]+", label))
        hit = {i for i, g in enumerate(groups) if any(t in toks or (len(t) >= 4 and t in label) for t in g)}
        if hit:
            name_hits[path] = hit
    any_expr = " OR ".join(_fts_or(g) for g in groups)
    all_expr = " AND ".join(_fts_or(g) for g in groups)
    sel = ("SELECT rowid, path, line, heading, bm25(entries_fts, 0.0, 0.0, 8.0, 1.0) AS score, "
           "snippet(entries_fts, -1, '[', ']', ' ... ', 12) AS snip FROM entries_fts WHERE entries_fts MATCH ?")
    queries = [(all_expr, "", [], 300), (any_expr, "", [], max(400, limit * 40))]
    if len(groups) > 1:
        for g in groups:
            queries.append((_fts_or(g), "", [], 150))
        named = [p for p, h in name_hits.items() if len(h) < len(groups)]
        if named:
            queries.append((any_expr, f" AND path IN ({','.join('?' * len(named))})", named, 300))
    cand: dict[int, tuple] = {}
    for expr, extra, xargs, k in queries:
        for row in c.execute(sel + filt + extra + " ORDER BY score LIMIT ?", (expr, *fargs, *xargs, k)).fetchall():
            cand.setdefault(row[0], row)
    if not cand:
        return []
    # Which query words each candidate entry covers, decided by FTS itself (same tokenizer and stemming).
    # Words found in the heading itself break ties, so the entry titled with the query comes first.
    cover: dict[int, set] = {rid: set() for rid in cand}
    head_cover: dict[int, set] = {rid: set() for rid in cand}
    ids = list(cand)
    for gi, g in enumerate(groups):
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT rowid FROM entries_fts WHERE entries_fts MATCH ? AND rowid IN ({','.join('?' * len(chunk))})"
            for (rid,) in c.execute(q, (_fts_or(g), *chunk)).fetchall():
                cover[rid].add(gi)
            for (rid,) in c.execute(q, ("heading : " + _fts_or(g), *chunk)).fetchall():
                head_cover[rid].add(gi)
    ranked = []
    for rid, (_r, path, line, heading, score, snip) in cand.items():
        if path not in meta:
            continue
        own = len(cover[rid])
        total = len(cover[rid] | name_hits.get(path, set()))
        ranked.append(((-total, -own, -len(head_cover[rid]), score), path, line, heading, score, snip, total))
    ranked.sort(key=lambda r: r[0])
    by_path: dict[str, dict] = {}
    order: list[str] = []
    for _key, path, line, heading, score, snip, total in ranked:
        snip = (snip or "").replace("\n", " ").strip() or heading
        if path not in by_path:
            name, proj, mt = meta[path]
            by_path[path] = {
                "name": name, "project": proj, "path": path,
                "score": round(-float(score), 2),
                "terms_matched": f"{total}/{len(groups)}",
                "snippet": snip,
                "updated_ago": _ago(time.time() - mt),
                "entries": [],
            }
            order.append(path)
        ents = by_path[path]["entries"]
        if len(ents) < 3:
            ents.append({"heading": heading, "line": int(line), "snippet": snip})
    return [by_path[p] for p in order[:limit]]


def _journal_search_impl(query: str, project: str = "", kind: str = "", limit: int = 10, _retry: bool = False) -> dict:
    if not query:
        return {"error": "query required"}
    c = _conn()
    try:
        # Refresh if the index is empty OR the FTS table is empty (e.g. right after
        # the v1.1.0 upgrade, when `journals` already had rows but FTS was just added).
        need_refresh = c.execute("SELECT COUNT(*) FROM journals").fetchone()[0] == 0
        if not need_refresh:
            try:
                if c.execute("SELECT COUNT(*) FROM journals_fts").fetchone()[0] == 0:
                    need_refresh = True
                elif c.execute("SELECT COUNT(*) FROM entries_meta").fetchone()[0] == 0:
                    need_refresh = True
            except Exception:
                pass
        if need_refresh:
            _index_refresh_internal()
        else:
            _sync_changed(c)
        results = []
        used_fts = False
        try:
            groups = _term_groups(query)
            if groups:
                results = _entry_search(c, groups, project, kind, limit)
                used_fts = True
        except Exception:
            used_fts = False
        if not used_fts:
            rows = c.execute("SELECT path, name, project, mtime FROM journals ORDER BY mtime DESC").fetchall()
            q_lower = query.lower()
            for path, name, proj, mtime in rows:
                if project and not _project_match(proj, name, project):
                    continue
                try:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                pos = content.lower().find(q_lower)
                if pos < 0:
                    continue
                s = max(0, pos - 100); e = min(len(content), pos + 200)
                results.append({
                    "name": name, "project": proj, "path": path,
                    "match_position": pos,
                    "snippet": f"...{content[s:e]}...".replace("\n", " "),
                    "updated_ago": _ago(time.time() - mtime),
                })
                if len(results) >= limit:
                    break
    finally:
        c.close()
    # Nothing found: a journal may have been created by hand since the last scan. Rescan once and retry.
    if not results and not _retry:
        _index_refresh_internal()
        return _journal_search_impl(query, project, kind, limit, _retry=True)
    out = {"query": query, "count": len(results), "ranked": used_fts}
    # A snippet can come from an old entry that a later one corrected. The journal's "Current state"
    # lines that match the query travel with each result, so today's truth sits next to the old text.
    cur_terms = [t for t in _expand_terms(query) if len(t) > 2]
    for r in results[:5]:
        try:
            text = Path(r["path"]).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sec = _find_section(text, ("current state", "estado actual"))
        if not sec:
            continue
        hits = [ln.strip() for ln in sec[1].splitlines() if ln.strip() and any(t in ln.lower() for t in cur_terms)]
        if hits:
            r["current_state"] = hits[:6]
            st = state_staleness(text)
            if st:
                r["current_state_stale"] = state_stale_note(st).lstrip("> ").strip()
    if any("current_state" in r for r in results):
        out["current_state_note"] = ("current_state = matching lines of the journal's Current state section: they win over "
                                     "any older entry in the snippet, unless current_state_stale says newer work "
                                     "shipped after it. Entries marked SUPERSEDED are history.")
    exists = _match_capabilities(query, project)
    if exists:
        out["already_exists"] = exists
        out["note"] = "already_exists = things that are built and working: extend them, do not rebuild. Open every match that could matter."
    decided = _match_capabilities(query, project, sections=_SEC_DECIDED)
    if decided:
        out["already_decided"] = decided
        out["decided_note"] = ("already_decided = what the owner already decided: follow it, do not re-propose it "
                               "or present it as new. Open the 'see' entry for the full reasoning.")
    if len(results) < 3 and not exists and not decided:
        out["hint"] = ("Few matches. Before saying this does not exist or is new, search again with 2-3 other words "
                       "for the same idea (both languages) and for its mechanism (who does what, who pays whom).")
    out["matches"] = results
    return out


@mcp.tool()
def journal_search(query: str, project: str = "", kind: str = "", limit: int = 10) -> dict:
    """
    Full-text search across journal contents, ranked best-first (FTS5 + bm25).

    query: words or a phrase to find inside the markdown. Each word is one idea (with its synonyms); an entry
        that covers more ideas ranks higher. To make several words or languages ONE idea, join them with "|":
        "lone legs|pierna sola" is one idea (both phrases must appear as written); separate ideas with ";":
        "lone legs|pierna sola; hedge|cobertura".
    project: filter by project substring. It matches the project folder name OR the journal's file name
        (case, "_", "-" and spaces ignored): journals that sit directly in a root folder have project "_root",
        so use the project name as written in the file, e.g. project="FORECAST_MARKETS" finds
        FORECAST_MARKETS_JOURNAL.md. Leave it empty to search everything.
    kind: filter by kind (raw | refined | skill), empty = all
    limit: max results

    Returns matched journals ranked by their best matching entry (a section between headings, scored on
    its own, so a long journal is not penalized for its length), one result per journal with a snippet,
    terms_matched, and "entries": its top 3 entries (heading, line, snippet). An entry that hits every
    query word ranks above one that hits some.
    """
    res = _journal_search_impl(query, project, kind, limit)
    # Meaning layer (2026-10-30): entries that say the same thing, whatever the words or language. Always shown
    # next to the word ranking, so a phrasing the words miss still surfaces (month archives included).
    try:
        import meaning
        hits = meaning.query(query, k=8, path_like=project)
        if hits and isinstance(res, dict):
            res["same_meaning"] = hits
            res["same_meaning_note"] = "same_meaning = entries whose meaning matches the query (any language); open the top ones even when the word ranking missed them."
    except Exception:
        pass
    return res


# ─── "Already exists": one line per working capability, found before anyone rebuilds it ─────────
_CAP_LINE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*\s*(.*)$")


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """(title, body lines) for every H2 that is a section, not a dated entry. Text before the first H2 is ("", lines)."""
    out: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            out.append((line[3:].strip(), []))
        else:
            out[-1][1].append(line)
    return out


def _find_section(text: str, names: tuple) -> Optional[tuple[str, str]]:
    for title, body in _sections(text):
        if title and not _DATED_H2.match("## " + title) and any(n in title.lower() for n in names):
            return title, "\n".join(body).strip("\n")
    return None


_CARD_KEYS = ("status", "estado", "since", "desde", "see", "ver", "keys", "claves", "how", "cómo", "como",
              "why", "porque", "date", "fecha", "aliases", "alias", "updated", "actualizado")


def _parse_capabilities(text: str, sections: tuple = _SEC_EXISTS) -> list[dict]:
    caps = []
    for title, body in _sections(text):
        if not title or _DATED_H2.match("## " + title) or not any(n in title.lower() for n in sections):
            continue
        for line in body:
            m = _CAP_LINE.match(line)
            if m:
                rest = m.group(2).lstrip(" ·:-")
                fields = {"what": m.group(1).strip(), "detail": rest}
                for part in re.split(r"\s+·\s+", rest):
                    k, _, v = part.partition(":")
                    if k.strip().lower() in _CARD_KEYS:
                        fields[_fold(k.strip())] = v.strip()
                caps.append(fields)
    return caps


def _all_capabilities(sections: tuple = _SEC_EXISTS) -> list[dict]:
    c = _conn()
    try:
        _sync_changed(c)
        like = " OR ".join("LOWER(content) LIKE ?" for _ in sections)
        rows = c.execute(f"SELECT path, name, project, content FROM journals_fts WHERE {like}",
                         [f"%## {n}%" for n in sections]).fetchall()
    except Exception:
        rows = []
    finally:
        c.close()
    out = []
    for path, name, project, content in rows:
        for cap in _parse_capabilities(content or "", sections):
            cap.update({"journal": name, "project": project, "path": path})
            out.append(cap)
    return out


# A Decided card can be overtaken by a later decision written as a plain entry while the card still states the
# old rule. Real case 2026-10-30: the 2026-10-27 card said "Business Review 97 USD", the 2026-10-28 entry said
# "the Business Review becomes FREE (replaces the 97 USD paid review)", and the map kept serving the old card as
# current, so the session repeated it to the owner.
_CHANGE_WORD = re.compile(r"\b(?:supersed\w*|replac\w*|overrid\w*|no longer|instead of|revert\w*|becomes|became|"
                          r"reemplaz\w*|ya no|en lugar de|deja de)\b", re.I)
# Ship and fix logs say "replaced" and "no longer" about files all day; only a decision, or an entry that says it
# supersedes, changes a rule. A scan of the real Decided cards with any entry counted gave mostly false alarms.
_DECISION_HEAD = re.compile(r"\[(?:decision|decided|decisi\w*|owner|correction|rule|pivot|direction)[^\]]*\]", re.I)
_SUPERSEDES = re.compile(r"\bsupersed\w*", re.I)
_ENTRY_DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b[^\n]*$", re.M)
# A card that already opens with "SUPERSEDED <date> by ..." says it itself (the convention for history kept in Decided).
_MARKED_SUPERSEDED = re.compile(r"\s*\[?(?:SUPERSEDED|REEMPLAZAD[AO])\b", re.I)


def _card_terms(cap: dict) -> list[str]:
    raw = str(cap.get("aliases") or cap.get("alias") or cap.get("keys") or cap.get("claves") or "")
    out = []
    for a in raw.split(","):
        f = _fold(a.strip())
        if (len(f) >= 3 or (f.isdigit() and len(f) >= 2)) and f not in out:
            out.append(f)
    return out


def newer_change(cap: dict, text: str) -> Optional[dict]:
    """The newest entry, dated after the card (or after its `updated:`), with a sentence that changes it: a
    change word ("replaces", "becomes", "no longer"...) plus the card named by its date or by two of its aliases."""
    if _MARKED_SUPERSEDED.match(str(cap.get("what", ""))):
        return None
    dates = {str(cap.get(k) or "")[:10] for k in ("date", "fecha", "updated", "actualizado")}
    dates = {d for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)}
    if not dates:
        return None
    since = max(dates)
    terms = _card_terms(cap)
    heads = list(_ENTRY_DATE.finditer(text))
    found = None
    for i, h in enumerate(heads):
        if h.group(1) <= since:
            continue
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        decision = bool(_DECISION_HEAD.search(h.group(0)))
        for sent in re.split(r"(?<=[.;!?])\s+|\n+", body):
            if not _CHANGE_WORD.search(sent):
                continue
            # "Supersedes the 2026-10-22 model and the 2026-10-23 line" speaks only to cards of those dates.
            named_dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", sent)) - {h.group(1)}
            if not (decision or (_SUPERSEDES.search(sent) and named_dates)):
                continue
            if named_dates and not named_dates & dates:
                continue
            f = _fold(sent)
            hit = [t for t in terms if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", f)]
            # Two loose words ("owner", "cards"; "studios", "mcp") match half the cards; a phrase or a number names one.
            specific = any(" " in t or t.isdigit() for t in hit)
            if len(hit) >= 3 or (len(hit) >= 2 and specific) or (named_dates and hit):
                if not found or h.group(1) >= found["date"]:
                    found = {"date": h.group(1), "heading": h.group(0)[3:].strip()[:120], "sentence": sent.strip()}
                break
    # A later card can replace this one too ("mapleworks.dev/live is a looping DEMO ... Replaces the earlier plan",
    # see: "previous card (2026-10-24 plan)"): it names this card's date and uses a change word somewhere in it.
    for other in _parse_capabilities(text, _SEC_DECIDED):
        od = str(other.get("date") or other.get("fecha") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", od) or od <= since or other.get("what") == cap.get("what"):
            continue
        full = f'{other.get("what", "")} {other.get("detail", "")}'
        if not _CHANGE_WORD.search(full):
            continue
        # The date must sit next to the change ("replaces the 2026-10-22 build prices card") or name a card
        # ("previous card (2026-10-24 plan)"); a date in the card's list of sources says nothing.
        segs = re.split(r"(?<=[.!?])\s+|\s+·\s+|;\s*", full)
        if not any(set(re.findall(r"\d{4}-\d{2}-\d{2}", g)) & dates
                   and (_CHANGE_WORD.search(g) or re.search(r"\bcard\b", g, re.I)) for g in segs):
            continue
        f = _fold(full)
        hit = [t for t in terms if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", f)]
        if len(hit) >= 2 and (not found or od >= found["date"]):
            found = {"date": od, "heading": "a later Decided card", "sentence": other.get("what", "")}
    return found


# A card can also be overtaken silently: a later ship entry just states a new value ("Precio: $27 como todos los
# journals en la tienda") with no change word and no [decision] tag. Real case 2026-11-01: the 2026-08-04 card "Sold
# journal prices stay high ($99 ...)" was served as the owner's rule while every journal had sold at $27 since
# 2026-08-20; the session quoted $99 to the owner. Measured on the 280 real Decided cards with bge-m3: 0 false
# alarms and the real case caught at a meaning floor of 0.62 (real 0.63; nearest false ones 0.60 and 0.61).
_VALUE = re.compile(r"(?:US\$|\$)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:usd|dolares|dólares)\b", re.I)
_VALUE_FLOOR = 0.62
_VALUE_GENERIC = set("""price prices precio precios cost costs cuesta value valor dollars dolares month year once only
plus with this that from have each every""".split())


def _values(t: str) -> set:
    out = set()
    for m in _VALUE.finditer(t):
        try:
            out.add(float((m.group(1) or m.group(2)).replace(",", "")))
        except ValueError:
            pass
    return out


def _value_neighbors(t: str, w: int = 6) -> set:
    """Word stems within w words of each money value: what the number is the price OF ("$99 for the flagship journals")."""
    toks = re.findall(r"\$?[\w$.,/-]+", _fold(t))
    out = set()
    for i, tk in enumerate(toks):
        if "$" in tk and re.search(r"\d", tk) or (re.fullmatch(r"[\d,.]+", tk) and i + 1 < len(toks)
                                                   and toks[i + 1] in ("usd", "dolares")):
            for x in toks[max(0, i - w): i + w + 1]:
                x = re.sub(r"[^a-z]", "", x)
                if len(x) >= 4 and x not in _STOP and x not in _VALUE_GENERIC:
                    out.add(x[:6])
    return out


def newer_value(cap: dict, text: str, timeout: float = 2.5) -> Optional[dict]:
    """The newest later entry that states a DIFFERENT value for the thing a one- or two-value card fixes (the same
    word next to both numbers, and the sentence means the same as the card). Needs the meaning service: without it
    nothing is claimed. Table rows are skipped: a price table lists other items of the same family."""
    what = str(cap.get("what", ""))
    if _MARKED_SUPERSEDED.match(what):
        return None
    cv = _values(what)
    if not cv or len(cv) > 2:   # a card with many prices is a catalog: a new number is usually another item
        return None
    d = str(cap.get("date") or cap.get("fecha") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return None
    cn = _value_neighbors(what)
    if not cn:
        return None
    heads = list(_ENTRY_DATE.finditer(text))
    cands = []
    for i, h in enumerate(heads):
        if h.group(1) <= d:
            continue
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        for sent in re.split(r"(?<=[.;!?])\s+|\n+", h.group(0)[3:] + "\n" + body):
            if sent.lstrip().startswith("|"):
                continue
            sv = _values(sent)
            if not sv or sv & cv or not (_value_neighbors(sent) & cn):
                continue
            cands.append((h.group(1), h.group(0)[3:].strip()[:120], sent.strip()))
    if not cands:
        return None
    cands = cands[-40:]   # the newest ones: the latest word is the one that counts
    try:
        import meaning
        scores = meaning.score(what, [c[2][:400] for c in cands], timeout=timeout)
    except Exception:
        scores = []
    best = None
    for sc, (date, heading, sent) in zip(scores, cands):
        if sc >= _VALUE_FLOOR and (not best or date >= best["date"]):
            best = {"date": date, "heading": heading, "sentence": sent, "score": round(float(sc), 2)}
    return best


def _mark_changed(cards: list[dict]) -> list[dict]:
    texts: dict = {}
    out = []
    for c in cards:
        p = c.get("path")
        if p and p not in texts:
            try:
                texts[p] = Path(p).read_text(encoding="utf-8", errors="replace")
            except Exception:
                texts[p] = ""
        ch = newer_change(c, texts.get(p, "")) if p else None
        if ch:
            s = ch["sentence"] if len(ch["sentence"]) <= 130 else ch["sentence"][:127] + "..."
            c = {**c, "changed_later": ch,
                 "what": f'[CHANGED LATER {ch["date"]}: "{s}" Follow the newer entry and fix this card] ' + c["what"]}
        else:
            nv = newer_value(c, texts.get(p, "")) if p else None
            if nv:
                s = nv["sentence"] if len(nv["sentence"]) <= 130 else nv["sentence"][:127] + "..."
                c = {**c, "changed_later": nv,
                     "what": (f'[NEWER VALUE {nv["date"]}: "{s}" The latest entry wins: check the live source (site, '
                              f'code, data) and, if it changed, mark this card SUPERSEDED now, without asking] ') + c["what"]}
        out.append(c)
    return out


# Words too generic to say two things are the same job (they appear in almost any task or card).
_CAP_STOP = set("""journal journals studio mcp file files script scripts test tests check live copy version code
new add build make use using tool tools herramienta herramientas thing things one two
not never always only must see who each any all every also can will should would more most other same very
nunca siempre solo cada todo todos otro otra""".split())


def _match_capabilities(query: str, project: str = "", limit: int = 6, min_cover: int = 1,
                        sections: tuple = _SEC_EXISTS) -> list[dict]:
    """Cards whose job matches the query. min_cover: how many of the query's own ideas (a word or a
    synonym of it) must appear in the card; the hook asks for 2 so a passing word does not fire it."""
    query = query.replace("_", " ")  # snake_case names (post_to_x, x_poster) -> separate words
    short_ok = {w for g in _alias_groups() for w in g if len(w) < 3}  # x, ig, yt, fb are real words here
    core = []
    for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", query):
        f = _fold(w)
        if f in _STOP or f in _CAP_STOP or f.isdigit() or (len(f) < 3 and f not in short_ok):
            continue
        if f not in core:
            core.append(f)
    terms = _expand_terms(" ".join(core))
    if not terms or not core:
        return []
    cards = []
    for cap in _all_capabilities(sections):
        if project and not _project_match(cap.get("project"), cap.get("journal"), project):
            continue
        # Only what it does, how, where and its keys: status words ("local", "built") are not the job.
        # A decision also matches by its reason and its aliases (every word someone might use for it).
        hay = _fold(" ".join(str(cap.get(k, "")) for k in ("what", "how", "keys", "como", "claves", "why", "porque", "aliases", "alias"))
                    or cap.get("detail", ""))
        cards.append((cap, set(re.findall(r"[a-z0-9_]+", hay.replace("_", " "))) | set(re.findall(r"[a-z0-9_]+", hay))))
    if min_cover >= 2 and len(cards) >= 8:
        # The hook reads long prompts: a word found in a quarter of all cards (the owner's name, the
        # product's own nouns) says nothing about which card fits, so it stops counting there.
        common = {t for t in terms if sum(1 for _, w in cards if t in w) > len(cards) / 4}
        core = [w for w in core if w not in common]
        terms = [t for t in terms if t not in common]
    scored = []
    for cap, words in cards:
        hits = {t for t in terms if t in words}
        if not hits:
            continue
        # how many of the query's own ideas are covered (a word or one of its synonyms)
        covered = sum(1 for w in core if w in hits or any(w in g and hits & set(g) for g in _alias_groups()))
        if covered >= min_cover:
            working = 1 if _fold(str(cap.get("status", ""))).startswith("working") else 0
            scored.append((covered + working, len(hits), cap))
    # A working tool outranks one that is built but unused or partial, at the same match.
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0][0] if scored else 0
    # Decisions get more slack: showing one extra rule is cheap, missing the one that applies is not.
    slack = 2 if sections == _SEC_DECIDED else 1
    keep = [c for cov, _, c in scored if cov >= max(1, best - slack)][:limit]
    if sections == _SEC_DECIDED:
        keep = _mark_changed(keep)
    return [{k: v for k, v in c.items() if v} for c in keep]


@mcp.tool()
def journal_capability_add(name_or_path: str = "", what: str = "", how: str = "", status: str = "working", see: str = "",
                           keys: str = "", project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Record something that is BUILT AND WORKING so nobody rebuilds it: one line in the journal's
    "Already exists" section (created if missing). Every journal_search and journal_before_build
    shows these lines first.

    what:   the job in plain words ("Post on X from a logged-in browser, no paid API")
    how:    the tool / script / command that does it ("BrowserTool post_to_x(session, text, media_path)")
    status: working | partial | broken (+ a few words: "working, image and video since 0.3.24")
    see:    where the details live (journal + section, file path, doc)
    keys:   extra search words, comma-separated, any language ("twitter, tweet, publicar")
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_capability_add", True)
    if err:
        return err
    if not (what.strip() and how.strip()):
        return _missing("what/how", 'journal_capability_add(name_or_path="MYPROJECT_JOURNAL.md", what="what it does", how="how to call it")')
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    path = Path(j["path"])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    today = datetime.date.today().isoformat()
    line = f"- **{what.strip()}** · how: {how.strip()} · status: {status.strip()} · since: {today}"
    if see.strip():
        line += f" · see: {see.strip()}"
    if keys.strip():
        line += f" · keys: {keys.strip()}"
    found = _find_section(text, _SEC_EXISTS)
    body = found[1] if found else ""
    kept = [l for l in body.splitlines() if not (_CAP_LINE.match(l) and _CAP_LINE.match(l).group(1).strip().lower() == what.strip().lower())]
    replaced = len(kept) != len(body.splitlines())
    if not found:
        kept = ["Built and working: extend these, never rebuild them. One line each (journal_capability_add)."]
    new_body = "\n".join([l for l in kept if l.strip() or kept.index(l) == 0] + [line]).strip()
    res = _write_section(path, text, found[0] if found else "Already exists", new_body)
    if "error" in res:
        return res
    return {"ok": True, "path": str(path), "line": line, "replaced_existing": replaced}


@mcp.tool()
def journal_decision_add(name_or_path: str = "", decision: str = "", why: str = "", aliases: str = "", see: str = "",
                         date: str = "", project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Record something the OWNER DECIDED (a product rule, a role, a money split, a name, a design or copy
    rule, "never X") as one line in the journal's "Decided" section (created if missing), so no session
    re-proposes it or calls it new. Every journal_search, journal_before_build and the start brief show it.

    decision: the decision in one plain sentence ("Ad creators get paid when another campaign runs their ad")
    why:      the reason, short
    aliases:  EVERY other word someone might use for it, comma-separated, any language
              ("designer, creator, ad market, catalog, royalty")
    see:      where the full reasoning lives (journal + entry date)
    date:     when it was decided (YYYY-MM-DD), today if empty
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_decision_add", True)
    if err:
        return err
    if not decision.strip():
        return _missing("decision", 'journal_decision_add(name_or_path="MYPROJECT_JOURNAL.md", decision="what was decided", why="reason")')
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    path = Path(j["path"])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    line = f"- **{decision.strip()}** · date: {(date or datetime.date.today().isoformat()).strip()}"
    if why.strip():
        line += f" · why: {why.strip()}"
    if aliases.strip():
        line += f" · aliases: {aliases.strip()}"
    if see.strip():
        line += f" · see: {see.strip()}"
    found = _find_section(text, _SEC_DECIDED)
    body = found[1] if found else ""
    kept = [l for l in body.splitlines() if not (_CAP_LINE.match(l) and _CAP_LINE.match(l).group(1).strip().lower() == decision.strip().lower())]
    replaced = len(kept) != len(body.splitlines())
    if not found:
        kept = ["Decided by the owner: follow these, never re-propose them as new. One line each (journal_decision_add)."]
    new_body = "\n".join([l for l in kept if l.strip() or kept.index(l) == 0] + [line]).strip()
    res = _write_section(path, text, found[0] if found else "Decided", new_body)
    if "error" in res:
        return res
    return {"ok": True, "path": str(path), "line": line, "replaced_existing": replaced}


@mcp.tool()
def journal_before_build(task: str, project: str = "", limit: int = 6) -> dict:
    """
    Call BEFORE building anything (a tool, a script, a feature, an agent task). Describe it in plain
    words. Returns what already exists for that job (extend it instead of building a second one) and
    the journal passages most related to it (past attempts, failures, decisions). Open them.
    """
    caps = _match_capabilities(task, project, limit)
    decided = _match_capabilities(task, project, limit, sections=_SEC_DECIDED)
    related = _journal_search_impl(task, project=project, limit=limit).get("matches", [])
    verdict = ("STOP: something already exists for this. Read it and extend it instead of building new."
               if caps else "Nothing recorded as existing for this. Still read the related passages before building; "
                             "when you finish, record it with journal_capability_add.")
    if decided:
        verdict += " The owner already decided how parts of this work (already_decided): build to those decisions."
    return {"task": task, "verdict": verdict, "already_exists": caps, "already_decided": decided,
            "related": [{k: r[k] for k in ("name", "project", "snippet", "path") if k in r} for r in related]}


def _before_build_text(task: str) -> str:
    """Plain text for a hook: empty when nothing relevant exists."""
    caps = _match_capabilities(task, limit=5, min_cover=2)
    decided = _match_capabilities(task, limit=5, min_cover=2, sections=_SEC_DECIDED)
    lines = []
    if caps:
        lines.append("JOURNAL: things that ALREADY EXIST for what you are about to build. Extend them; do not build a second one:")
        for c in caps:
            lines.append(f"- {c.get('what')}: {c.get('how') or c.get('detail', '')} [{c.get('status', '')}] "
                         f"(journal {c.get('journal')}" + (f", see {c['see']}" if c.get("see") else "") + ")")
    if decided:
        lines.append("JOURNAL: the owner ALREADY DECIDED these. Build to them; never present them as new:")
        for c in decided:
            lines.append(f"- {c.get('what')}" + (f" (why: {c['why']})" if c.get("why") else "")
                         + f" (journal {c.get('journal')}" + (f", see {c['see']}" if c.get("see") else "") + ")")
    return "\n".join(lines)


@mcp.tool()
def journal_quick(query: str, limit: int = 5) -> dict:
    """
    The fast first look at anything: a word ("localmodel"), a file path, a tool or a topic. Returns in a few
    lines the Brain map row (which journal to read first, who is working on it now), the journals where it
    lives, what the owner already decided, what already exists, the latest dated entries and what is pending.
    Call it before touching, building or answering about anything; then open what it points to.
    """
    import quickmap
    m = quickmap.quick_map(query, limit)
    m["text"] = quickmap.quick_map_text(m)
    # Meaning layer (2026-10-30): entries that say the same thing in other words or the other language.
    mb = quickmap._meaning_block(query, "SAME MEANING (entries that say the same thing in any words or language):",
                                 set(re.findall(r"[\w.-]+\.md:\d+", m["text"] or "")))
    m["text"] = "\n".join(x for x in (mb, m["text"]) if x) or "Nothing recorded for this in any journal."
    return m


@mcp.tool()
def journal_how_to() -> str:
    """The manual: exactly how to start with, write in, and leave a journal so any other session or AI
    continues it perfectly. Read it once per session if you have not."""
    return _MANUAL


@mcp.tool()
def journal_list_sections(name_or_path: str = "", contains: str = "", offset: int = 0,
                          limit: int = 150, newest_first: bool = False, project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    List the H2 sections of a journal so you know where to append or what to read.

    Big journals have thousands of dated entries, so the list is paged:
    contains: only titles that include this text (case-insensitive), e.g. "mail" or "2026-10"
    offset / limit: page through the list; the reply says total and next_offset
    newest_first: start from the end of the file (latest entries first)
    Titles longer than 120 characters are cut.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_list_sections", True)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    needle = contains.lower().strip()
    sections = []
    for line in content.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            if needle and needle not in title.lower():
                continue
            sections.append(title if len(title) <= 120 else title[:117] + "...")
    if newest_first:
        sections.reverse()
    total = len(sections)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    page = sections[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else None
    return {"path": j["path"], "total": total, "offset": offset,
            "next_offset": nxt, "sections": page}


STALE_DAYS = int(os.environ.get("JOURNAL_STALE_DAYS", "14"))
_CHECK_RE = re.compile(r"^(\s*[-*]?\s*)check:\s*(url|file)\s+(\"[^\"]+\"|\S+)(?:\s+(not\s+)?contains\s+\"([^\"]+)\")?(.*)$", re.I)


# 2026-10-28 (Dreamfield): a session stopped when a paid account ran dry and never replaced its Handoff; the next
# session got the 01:50 Handoff (an ad run) first, while 20 entries written after it held the day's real thread (a
# [decision] to redo every release, 7 tries and their verdicts). The day-based FRESHNESS note stays quiet inside the
# same day, and LATEST ENTRIES showed only the last 4 (a cleanup incident). A Handoff / Pending block now carries the
# time it was written, and the brief lists every entry written after it.
_STAMP_RX = re.compile(r"^<!-- written (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) -->\s*\n?", re.M)
_WHEN_IN_TEXT = re.compile(r"(20\d\d-\d\d-\d\d)(?:[ T]~?(\d{1,2}):(\d\d)(?::\d\d)?(\s*UTC)?)?")
_HEAD_WHEN = re.compile(r"^## (\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})")
_OWNER_TAG = re.compile(r"^\[(?:decision|verdict|owner[-\w]*|correction)\]", re.I)


def _stamp(body: str) -> str:
    """The clock of journal_append headings (local time), so a Handoff compares with the entries around it."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"<!-- written {now} -->\n" + _STAMP_RX.sub("", body.strip(), count=1)


def _section_when(body: str) -> str:
    """When a Handoff / Pending block was written: its stamp; for an older block without one, the newest date-time
    it names (a time marked UTC moved to local, the clock of the headings), a bare date counting from its start."""
    m = _STAMP_RX.search(body)
    if m:
        return m.group(1)
    best = ""
    for d, h, mi, utc in _WHEN_IN_TEXT.findall(body):
        try:
            dt = datetime.datetime.fromisoformat(f"{d} {int(h or 0):02d}:{mi or '00'}")
        except ValueError:
            continue
        if h and utc:
            dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        best = max(best, dt.strftime("%Y-%m-%d %H:%M"))
    return best


def _behind_note(content: str, block: str, cap: int = 20) -> str:
    """Every dated entry written after the block, owner decisions and verdicts first: the Handoff does not know them."""
    when = _section_when(block)
    if not when:
        return ""
    after = []
    for ln in content.splitlines():
        m = _HEAD_WHEN.match(ln)
        if m and f"{m.group(1)} {m.group(2)}" > when:
            title = ln[3:].strip()
            after.append((not _OWNER_TAG.match(title[17:].strip()), title))
    if not after:
        return ""
    # owner entries first, then the NEWEST of the rest in order (where things stopped matters more than the morning)
    owner = [t for rest, t in after if not rest]
    others = [t for rest, t in after if rest]
    keep = max(cap - len(owner), 5)
    shown = owner + others[-keep:]
    cut = len(others) - min(keep, len(others))
    more = f"\n- ... and {cut} older (journal_read)" if cut > 0 else ""
    return (f"> HANDOFF IS BEHIND: it was written {when}, and {len(after)} entr{'y' if len(after) == 1 else 'ies'} "
            f"came after it. It does not know them: read them before trusting it or telling anyone where things stand "
            f"(owner decisions and verdicts first):\n" + "\n".join(f"- {t[:150]}" for t in shown) + more + "\n\n")


def _freshness_note(block: str) -> str:
    """Warn when a block has open items but its newest date is old: the claim may no longer be true."""
    open_items = len(re.findall(r"^\s*[-*]\s*\[ \]", block, re.M))
    dates = []
    for d in re.findall(r"20\d\d-\d\d-\d\d", block):
        try:
            dates.append(datetime.date.fromisoformat(d))
        except ValueError:
            pass
    failed = len(re.findall(r"· FAILED 20\d\d-\d\d-\d\d", block))
    if failed:
        return (f"> FRESHNESS: {failed} check(s) here FAILED the last time they ran. "
                f"Those claims are not true anymore: fix them before repeating them.\n\n")
    if not open_items:
        return ""
    checks =sum(1 for ln in block.splitlines() if _CHECK_RE.match(ln))
    hint = (f" Run journal_verify to re-run its {checks} check: line(s)." if checks
            else " Verify each against reality (live page, file, command) before saying it is still open.")
    if not dates:
        return f"> FRESHNESS: {open_items} open item(s), no date anywhere.{hint}\n\n"
    age = (datetime.date.today() - max(dates)).days
    if age <= STALE_DAYS:
        return ""
    return (f"> FRESHNESS: newest date here is {max(dates)} ({age} days ago) and it lists "
            f"{open_items} open item(s). Some may already be done.{hint}\n\n")


# A ship entry: tagged [ship], or a title that says the thing went live / was built (not "NOT built").
_SHIP_TAG = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?\s*\[(?:ship|shipped|live|deploy)\]", re.I)


def state_staleness(content: str, slack_days: int = 1) -> dict:
    """2026-10-28: CREATIVE_HUB "Current state" said "State at 2026-10-25 ... Built? NOT built" while the same
    journal had [ship] entries of 2026-10-27, and journal_search told the session that Current state wins over
    entries. A Current state whose own date is older than the journal's newest [ship] entry by more than
    slack_days is marked stale. {"state_date", "ship_when", "ship_title"} or {}."""
    sec = _find_section(content, _SEC_STATE)
    if not sec:
        return {}
    ds = re.findall(r"20\d\d-\d\d-\d\d", sec[1])
    if not ds:
        return {}
    try:
        state = max(datetime.date.fromisoformat(d) for d in ds)
    except ValueError:
        return {}
    best = None
    for ln in content.splitlines():
        m = _SHIP_TAG.match(ln)
        if m and (best is None or (m.group(1), m.group(2) or "") > best[:2]):
            best = (m.group(1), m.group(2) or "", ln[3:].strip())
    if not best:
        return {}
    try:
        ship = datetime.date.fromisoformat(best[0])
    except ValueError:
        return {}
    if (ship - state).days <= slack_days:
        return {}
    return {"state_date": str(state), "ship_when": (best[0] + " " + best[1]).strip(), "ship_title": best[2][:160]}


def state_stale_note(st: dict) -> str:
    return (f"> CURRENT STATE MAY BE STALE: it is dated {st['state_date']}, but this journal shipped newer work on "
            f"{st['ship_when']} ({st['ship_title']}). Trust the newer entries over it, and replace it.\n")


_READ_CAP = 2_000_000


def _run_check(kind: str, target: str, needle: str, base: Path, negate: bool = False) -> tuple[bool, str]:
    target = target.strip('"')  # check: file "C:/path with spaces/x.md"
    if kind.lower() == "file":
        if negate:  # never a silent pass: this check kind cannot read text
            return (False, "not contains works on url checks only")
        p = Path(target)
        if not p.is_absolute():
            p = base / target
        return (p.exists(), "exists" if p.exists() else "missing")
    try:
        req = urllib.request.Request(target, headers={"User-Agent": "journal-verify"})
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
            raw = r.read(_READ_CAP + 1) if needle else b""
            cut = len(raw) > _READ_CAP
            raw = raw[:_READ_CAP]
            enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
            body = raw.decode(enc, errors="replace")
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}")
    except Exception as e:
        return (False, str(e)[:80])
    if negate:
        if needle.lower() in body.lower():
            return (False, f"HTTP {status}, text found but must be absent")
        if cut:
            return (False, f"HTTP {status}, page larger than the read limit, cannot prove the text is absent")
        if not raw:
            return (False, f"HTTP {status}, empty page, cannot prove the text is absent")
        return (True, f"HTTP {status}, text absent")
    if needle and needle.lower() not in body.lower():
        return (False, f"HTTP {status}, text not found")
    return (True, f"HTTP {status}" + (", text found" if needle else ""))


@mcp.tool()
def journal_verify(name_or_path: str = "", section: str = "", stamp: bool = True, project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Re-run the 'check:' lines of a journal (or one section) against reality.

    Write a check under any claim that can go stale, so the next session proves it
    in one call instead of trusting an old note:
        - [ ] Listed on the store page
          check: url https://example.com/store contains "My Product"
        - [x] Build artifact exists
          check: file dist/app.zip
    Kinds: 'url <URL> [contains "text"]' (GET, optional text match) and
    'file <path>' (exists; relative to the journal's folder). No shell commands run.
    Each result prints the text it looked for ("contains" or "not_contains") so a failed line says which word was wrong.
    'url <URL> not contains "text"' passes only when the page answers 200 and the text is absent (a 404 or an
    unreachable page fails, never passes); it works on url checks only.
    section: part of a heading of any level (# to ######); it covers that heading and what is under it.
    A section that matches no heading returns an error instead of 0 checks.

    stamp=True writes the result back on each check line ('verified 2026-10-19 OK'
    or 'FAILED ...'), so the date of the last proof lives next to the claim.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_verify", True)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    path = Path(j["path"])
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    target = section.lower().strip()
    in_scope = not target
    scope_level = 0
    found = not target
    today = datetime.date.today().isoformat()
    results, changed = [], False
    fence = None  # (char, length) of the open code fence: "#" lines inside it are code, not headings
    for i, ln in enumerate(lines):
        fm = re.match(r"^\s*(`{3,}|~{3,})(.*)$", ln)
        if fm:
            mk = fm.group(1)
            if fence is None:
                fence = (mk[0], len(mk))
            elif mk[0] == fence[0] and len(mk) >= fence[1] and not fm.group(2).strip():
                fence = None  # closes only on the same character, at least as long, nothing after it
        hm = re.match(r"^(#{1,6})\s+(.*)$", ln) if target and fence is None else None
        if hm:
            level = len(hm.group(1))
            if target in hm.group(2).lower():
                in_scope, scope_level, found = True, level, True
            elif in_scope and level <= scope_level:
                in_scope = False
        if not in_scope:
            continue
        m = _CHECK_RE.match(ln)
        if not m:
            continue
        indent, kind, tgt, neg, needle, rest = m.groups()
        loose = re.split(r"\s·\s", rest, maxsplit=1)[0]  # text before the verified/FAILED stamp
        if re.search(r"\bcontains\b", loose, re.I):
            ok, detail = False, 'text must be in double quotes: contains "text" or not contains "text"'
        else:
            ok, detail = _run_check(kind, tgt, needle or "", path.parent, bool(neg))
        claim = next((lines[k].strip() for k in range(i - 1, -1, -1)
                      if lines[k].strip() and not _CHECK_RE.match(lines[k])), "")
        results.append({"claim": claim[:160], "check": f"{kind} {tgt}", "ok": ok, "detail": detail,
                        **(({"not_contains": needle} if neg else {"contains": needle}) if needle else {})})
        if stamp:
            mark = f"verified {today} OK" if ok else f"FAILED {today}: {detail}"
            base = (f'{indent}check: {kind} {tgt}' + (f' {"not " if neg else ""}contains "{needle}"' if needle else "")
                    if not re.search(r"\bcontains\b", loose, re.I) else ln.split(" · ")[0])
            lines[i] = f"{base} · {mark}"
            changed = True
    if changed:
        _atomic_write(path, "\n".join(lines).rstrip() + "\n")
    if not found:
        return {"error": f'section not found: "{section}". Use a part of a heading (any level, # to ######), case ignored.',
                "journal": path.name}
    if not results:
        return {"journal": path.name, "checks": 0,
                "next": "No check: lines here. Add one under each claim that can go stale (see tool docs)."}
    failed = [r for r in results if not r["ok"]]
    return {"journal": path.name, "checks": len(results), "passed": len(results) - len(failed),
            "failed": failed, "results": results,
            "next": "Fix the journal where a check failed: the claim is no longer true."
                    if failed else "All claims re-proven today."}


def _living_journals(kind: str = "raw") -> list[tuple[str, str]]:
    c = _conn()
    try:
        rows = c.execute("SELECT path, name FROM journals WHERE (?='' OR kind=?)", (kind, kind)).fetchall()
    finally:
        c.close()
    out = []
    for p, n in rows:
        try:
            out.append((n, Path(p).read_text(encoding="utf-8", errors="replace")))
        except Exception:
            pass
    return out


def _norm_title(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


@mcp.tool()
def journal_contradictions(kind: str = "raw", limit: int = 30) -> dict:
    """
    Find places where the journals disagree with each other or with reality.

    - the same checklist item ('- [ ] **Title**' vs '- [x] **Title**') open in one
      journal and done in another (or in two places of the same journal)
    - 'check:' lines whose last run FAILED (the claim next to them is no longer true)

    It reports, it never edits. Fix the stale side, then journal what changed.
    kind: 'raw' (living journals, default) | 'refined' | '' (all)
    """
    items: dict = {}
    failed: list = []
    for name, text in _living_journals(kind):
        for ln in text.splitlines():
            m = re.match(r"^\s*[-*]\s*\[( |x|X)\]\s*(?:\S+\s+)?\*\*(.+?)\*\*", ln)
            if m:
                key = _norm_title(m.group(2))
                if len(key) >= 6:
                    items.setdefault(key, []).append(
                        {"journal": name, "done": m.group(1) != " ", "line": ln.strip()[:160]})
            if "· FAILED 20" in ln:
                failed.append({"journal": name, "line": ln.strip()[:200]})
    def _detail(line: str) -> set:
        rest = line.split("**", 2)[-1]
        return {w for w in _norm_title(rest).split() if len(w) > 3}

    def _same_task(a: dict, b: dict) -> bool:
        # Same title is not enough: "Content Studio: new panel" and "Content Studio: fixed
        # the music bug" are two tasks on one product. Require the details to overlap too.
        da, db = _detail(a["line"]), _detail(b["line"])
        if not da or not db:
            return True
        return len(da & db) / min(len(da), len(db)) >= 0.5

    conflicts = []
    for key, occ in items.items():
        opened = [o for o in occ if not o["done"]]
        done = [o for o in occ if o["done"]]
        pairs_open = [o for o in opened if any(_same_task(o, d) for d in done)]
        if pairs_open:
            conflicts.append({"item": key, "open_in": pairs_open,
                              "done_in": [d for d in done if any(_same_task(o, d) for o in pairs_open)]})
    return {
        "open_vs_done": conflicts[:limit],
        "failed_checks": failed[:limit],
        "count": len(conflicts) + len(failed),
        "next": "Each hit is a question, not a verdict: check reality, then fix the stale side."
                if conflicts or failed else "No contradictions found.",
    }


_ENTITY_PATTERNS = [
    ("domain", r"\b(?:[a-z0-9-]+\.)+(?:com|ai|io|dev|run|net|org|app|sh|co)\b"),
    ("env_var", r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b"),
    ("port", r"(?<![\w.]):(?:[1-9]\d{3,4})\b"),
    ("journal", r"\b[A-Z][A-Z0-9_]*_JOURNAL(?:_[A-Z]+)?\.md\b"),
]


@mcp.tool()
def journal_map(entity: str = "", kind: str = "raw", min_journals: int = 2, limit: int = 40) -> dict:
    """
    The dependency map hidden in the journals: which things (domains, env vars,
    ports, other journals, or any term you pass) are shared across which journals.

    entity="" -> the most shared things, i.e. what would ripple across projects if
                 it changed (a token, a domain, a server port).
    entity="X" -> every journal and line that mentions X: the blast radius of
                  changing X, before you change it.
    """
    docs = _living_journals(kind)
    if entity:
        needle = entity.lower()
        hits = []
        for name, text in docs:
            lines = [ln.strip()[:180] for ln in text.splitlines() if needle in ln.lower()]
            if lines:
                hits.append({"journal": name, "mentions": len(lines), "lines": lines[:5]})
        hits.sort(key=lambda h: -h["mentions"])
        return {"entity": entity, "journals": len(hits), "touches": hits[:limit],
                "next": "Everything listed here may need a look (or an update) if X changes."}
    seen: dict = {}
    for name, text in docs:
        for etype, pat in _ENTITY_PATTERNS:
            for e in set(re.findall(pat, text)):
                if etype == "journal" and e == name:
                    continue
                if etype == "env_var" and "JOURNAL" in e:
                    continue
                seen.setdefault((etype, e), set()).add(name)
    shared = [{"entity": e, "type": t, "journals": len(js), "in": sorted(js)[:8]}
              for (t, e), js in seen.items() if len(js) >= min_journals]
    shared.sort(key=lambda x: -x["journals"])
    return {"shared_entities": shared[:limit], "total_shared": len(shared),
            "next": "Pass one as entity= to see its full blast radius line by line."}


@mcp.tool()
def journal_read_section(name_or_path: str = "", section: str = "", project: str = "", journal: str = "", name: str = "", path: str = "") -> str:
    """
    Read just one section of a journal by name (case-insensitive substring match).
    Returns the content between '## <section>' and the next '##'.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_read_section", False)
    if err:
        return err
    if not section.strip():
        return _missing("section", 'journal_read_section(name_or_path="MYPROJECT_JOURNAL.md", section="Current state")', False)
    j = _resolve(name_or_path)
    if not j:
        return _not_found(name_or_path)
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Read error: {e}"
    lines = content.splitlines()
    target = section.lower().strip()
    capturing = False
    captured: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            if target in line[3:].lower():
                capturing = True
                captured.append(line)
                continue
        if capturing:
            captured.append(line)
    if not captured:
        return f"Section '{section}' not found. Sections available: see journal_list_sections."
    out = "\n".join(captured)
    return _freshness_note(out) + out


@mcp.tool()
def journal_update_section(name_or_path: str = "", section: str = "", new_content: Optional[str] = None, mode: str = "replace",
                           content: str = "", text: str = "", body: str = "", project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Update a specific section of the journal.

    section: section title (case-insensitive substring match, e.g. 'roadmap', 'current state')
    new_content: the new section body (without the '## ...' header, that's preserved)
    mode: 'replace' (default, rewrites the section body)
        | 'append' (adds new_content to the end of the section)
        | 'prepend' (inserts new_content at the top of the section body)

    Use for: keeping Current state / Roadmap fresh, logging Decisions, recording Incidents.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_update_section", True)
    if err:
        return err
    if new_content is None:
        new_content = _first(content, text, body) or None
    if not section.strip() or new_content is None:
        return _missing("section/new_content", 'journal_update_section(name_or_path="MYPROJECT_JOURNAL.md", section="Current state", new_content="full new body") (aliases accepted for new_content: content, text, body)')
    if mode not in ("replace", "append", "prepend"):
        return {"error": f"mode must be replace/append/prepend, got {mode}"}
    if mode != "replace" and any(n in section.lower() for n in _SEC_HANDOFF + _SEC_STATE + _SEC_PENDING):
        return {"error": f"'{section}' is replaced whole, never stacked: a section that grows by {mode} turns into a pile "
                         "of stale claims. Read it, write the full current version, and call again with mode='replace'."}
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    try:
        path = Path(j["path"])
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    if any(n in section.lower() for n in _SEC_HANDOFF + _SEC_PENDING):
        new_content = _stamp(new_content)
    lines = content.splitlines()
    target = section.lower().strip()
    start_idx = -1
    end_idx = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if start_idx >= 0:
                end_idx = i
                break
            if target in line[3:].lower():
                start_idx = i
    if start_idx < 0:
        # A missing section is created (Pending now, Already exists, a Handoff in an old journal...)
        # instead of failing, right before the dated entries so it reads as part of the structure.
        res = _write_section(path, content, section.strip(), new_content.strip())
        if "error" in res:
            return res
        return {"ok": True, "section": section, "mode": mode, "created": True,
                "new_size_kb": round(path.stat().st_size / 1024, 1)}
    header = lines[start_idx]
    body_lines = lines[start_idx + 1:end_idx]
    body = "\n".join(body_lines).strip("\n")
    new_content = new_content.strip()
    if mode == "replace":
        new_body = new_content
    elif mode == "append":
        new_body = (body + "\n\n" + new_content).strip("\n")
    else:  # prepend
        new_body = (new_content + "\n\n" + body).strip("\n")
    new_lines = lines[:start_idx] + [header, "", new_body, ""] + lines[end_idx:]
    new_full = _refresh_frontmatter("\n".join(new_lines).rstrip() + "\n")
    try:
        _atomic_write(path, new_full)
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    return {"ok": True, "section": section, "mode": mode, "new_size_kb": round(path.stat().st_size / 1024, 1)}


def _write_section(path: Path, text: str, title: str, body: str) -> dict:
    """Replace the body of section `title` (exact title as found), or create it before the first dated
    entry / 'Recent entries' when it does not exist. Re-indexes the journal."""
    lines = text.splitlines()
    start = end = -1
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if start >= 0:
                end = i
                break
            if line[3:].strip() == title:
                start = i
    if start >= 0:
        end = end if end >= 0 else len(lines)
        new_lines = lines[:start + 1] + ["", body.strip(), ""] + lines[end:]
    else:
        at = len(lines)
        # "Pending now" goes above everything (the first thing anyone reads); other sections go
        # right before the dated entries.
        top = any(n in title.lower() for n in _SEC_PENDING)
        for i, line in enumerate(lines):
            if (top and line.startswith("## ")) or _DATED_H2.match(line) or line.lower().startswith("## recent entries"):
                at = i
                break
        new_lines = lines[:at] + [f"## {title}", "", body.strip(), ""] + lines[at:]
    try:
        _atomic_write(path, _refresh_frontmatter("\n".join(new_lines).rstrip() + "\n"))
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    try:
        c = _conn()
        try:
            _reindex_path(c, str(path))
            c.commit()
        finally:
            c.close()
    except Exception:
        pass
    return {"ok": True}


_LEAVING_FOOTER = ("--- LEAVING THIS JOURNAL --- Log work in the same turn (journal_append). Record reusable things "
                   "(journal_capability_add). Before building: journal_before_build. At the end, REPLACE \"Handoff for next "
                   "session\" with the full task list, what was already tried with the owner's verdict, and where you stopped, "
                   "and \"Current state\" if it changed. "
                   "Manual: journal_how_to().")


@mcp.tool()
def journal_handoff_brief(name_or_path: str = "", max_lines: int = 80, project: str = "", journal: str = "", name: str = "", path: str = "") -> str:
    """
    The brief a new session reads first. In this order: what is pending now (or the Handoff), the
    project's rules, what the owner already decided, the current state, what already exists, then the
    latest entries, and how to leave the journal. Those first parts are never cut; the rest fits in max_lines.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_handoff_brief", False)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return _not_found(name_or_path)
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Read error: {e}"
    secs = _sections(content)
    # The head is the journal's own top lines, never its Obsidian frontmatter block.
    head = [ln for ln in _sections(_strip_frontmatter(content))[0][1] if ln.strip()][:8]
    parts = [("\n".join(head), False)]
    pending = _find_section(content, _SEC_PENDING)
    handoff = _find_section(content, _SEC_HANDOFF)
    for found in (pending, handoff if not pending or (handoff and handoff[0] != pending[0]) else None):
        if found:
            parts.append((_behind_note(content, found[1]) + _freshness_note(found[1]) + f"## {found[0]}\n{found[1]}", True))
    rules = _find_section(content, _SEC_RULES)
    if rules:
        # How this project wants things done (which session, which tool): read before acting.
        parts.append((f"## {rules[0]}\n{rules[1]}", True))
    decided = _find_section(content, _SEC_DECIDED)
    if decided:
        # What the owner already decided: never re-proposed, never cut.
        parts.append((f"## {decided[0]}\n{decided[1]}", True))
    state = _find_section(content, _SEC_STATE)
    if state:
        st = state_staleness(content)
        parts.append(((state_stale_note(st) if st else "") + f"## {state[0]}\n{state[1]}", True))
    caps = _parse_capabilities(content)
    if caps:
        parts.append(("## Already exists (extend, never rebuild)\n" + "\n".join(
            f"- {c['what']}: {c.get('how') or c.get('detail', '')}" for c in caps), False))
    dated = [(t, b) for t, b in secs if t and _DATED_H2.match("## " + t)]
    if dated:
        recent = []
        for t, b in dated[-4:]:
            body = [ln for ln in b if ln.strip() and ln.strip() != "---"][:3]
            recent.append(f"## {t}\n" + "\n".join(body))
        parts.append(("--- LATEST ENTRIES (newest last) ---\n" + "\n\n".join(recent), False))
    if not (pending or handoff or state):
        parts.append(("NOTE: this journal has no Handoff / Current state section yet. Add them with "
                      "journal_update_section (mode=replace creates them).", True))
    must = sum(len(t.splitlines()) for t, keep in parts if keep)
    budget = max(max_lines - must - 2, 10)
    out = []
    for text, keep in parts:
        lines = text.splitlines()
        if not keep:
            lines = lines[:budget]
            budget -= len(lines)
            if not lines:
                continue
        out.append("\n".join(lines))
    return "\n\n".join(out) + f"\n\n{_LEAVING_FOOTER}\n(full file: {j['path']})"


@mcp.tool()
def journal_recent_changes(last_hours: int = 24, limit: int = 20) -> dict:
    """
    What journals have been updated lately. Use to see cross-session activity:
    'What did the FLASHARB tab journal in the last 12h?'
    """
    c = _conn()
    try:
        cutoff = time.time() - last_hours * 3600
        rows = c.execute(
            "SELECT path, name, project, size_bytes, mtime FROM journals "
            "WHERE mtime >= ? ORDER BY mtime DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    finally:
        c.close()
    now = time.time()
    return {
        "last_hours": last_hours,
        "count": len(rows),
        "journals": [{
            "name": r[1], "project": r[2],
            "kb": round(r[3] / 1024, 1),
            "updated_ago": _ago(now - r[4]),
        } for r in rows],
    }


@mcp.tool()
def journal_stats() -> dict:
    """Library snapshot: total journals, by project, biggest, freshest."""
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*), SUM(size_bytes) FROM journals").fetchone()
        by_project = c.execute("SELECT project, COUNT(*), SUM(size_bytes) FROM journals "
                               "GROUP BY project ORDER BY COUNT(*) DESC LIMIT 10").fetchall()
        biggest = c.execute("SELECT name, project, size_bytes FROM journals "
                            "ORDER BY size_bytes DESC LIMIT 5").fetchall()
        freshest = c.execute("SELECT name, project, mtime FROM journals "
                             "ORDER BY mtime DESC LIMIT 5").fetchall()
    finally:
        c.close()
    return {
        "total_journals": total[0] or 0,
        "total_size_kb": round((total[1] or 0) / 1024, 1),
        "top_projects": [{"project": p, "count": c, "kb": round(s / 1024, 1)} for p, c, s in by_project],
        "biggest": [{"name": n, "project": p, "kb": round(s / 1024, 1)} for n, p, s in biggest],
        "freshest": [{"name": n, "project": p, "updated_ago": _ago(time.time() - m)} for n, p, m in freshest],
    }


@mcp.tool()
def journal_browse(domain: str = "", tier: str = "", kind: str = "", tag: str = "", limit: int = 40) -> dict:
    """
    Structured browse of the library by product metadata (for the marketplace).

    domain / tier / kind: filters (kind = raw | refined | skill)
    tag: substring match against the tags field
    Returns journals with their product metadata (title, domain, tier, tools, tags, description).
    """
    c = _conn()
    try:
        if c.execute("SELECT COUNT(*) FROM journals").fetchone()[0] == 0:
            _index_refresh_internal()
        where = []; params: list = []
        if domain: where.append("LOWER(domain) = LOWER(?)"); params.append(domain)
        if tier: where.append("LOWER(tier) = LOWER(?)"); params.append(tier)
        if kind: where.append("LOWER(kind) = LOWER(?)"); params.append(kind)
        if tag: where.append("LOWER(tags) LIKE LOWER(?)"); params.append(f"%{tag}%")
        sql = ("SELECT name, project, path, kind, title, domain, tier, tools, tags, description, "
               "word_count, mtime FROM journals")
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY mtime DESC LIMIT ?"; params.append(limit)
        rows = c.execute(sql, params).fetchall()
    finally:
        c.close()
    now = time.time()
    return {
        "filters": {"domain": domain, "tier": tier, "kind": kind, "tag": tag},
        "count": len(rows),
        "journals": [{
            "name": r[0], "project": r[1], "path": r[2], "kind": r[3], "title": r[4],
            "domain": r[5], "tier": r[6], "tools": r[7], "tags": r[8], "description": r[9],
            "word_count": r[10], "updated_ago": _ago(now - r[11]),
        } for r in rows],
    }


@mcp.tool()
def journal_market_index(kind: str = "refined") -> dict:
    """
    The marketplace feed: every product of a kind (default 'refined') with full
    metadata, for a Catalog API or storefront to consume. Commerce fields (price,
    payouts) live in the Catalog layer, not here. This is content + metadata only.
    """
    c = _conn()
    try:
        if c.execute("SELECT COUNT(*) FROM journals").fetchone()[0] == 0:
            _index_refresh_internal()
        rows = c.execute(
            "SELECT name, path, kind, title, domain, tier, tools, tags, description, "
            "source_projects, outcome, version, word_count, mtime FROM journals "
            "WHERE LOWER(kind) = LOWER(?) ORDER BY domain, title",
            (kind,),
        ).fetchall()
    finally:
        c.close()
    now = time.time()
    return {
        "kind": kind,
        "count": len(rows),
        "products": [{
            "name": r[0], "path": r[1], "kind": r[2], "title": r[3], "domain": r[4],
            "tier": r[5], "tools": [t.strip() for t in (r[6] or "").split(",") if t.strip()],
            "tags": [t.strip() for t in (r[7] or "").split(",") if t.strip()],
            "description": r[8], "source_projects": r[9], "outcome": r[10],
            "version": r[11], "word_count": r[12], "updated_ago": _ago(now - r[13]),
        } for r in rows],
    }


@mcp.tool()
def journal_overlap_check(name_or_path: str = "", min_shared: int = 3, limit: int = 10, project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Dedup helper: find other journals that overlap this one, by shared H2 section
    headings and shared significant terms. Use before pricing to catch two journals
    that teach the same skill (the Refinery dedup step).
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_overlap_check", True)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path)}
    try:
        base = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}

    def _headings(t):
        return {ln.lstrip("# ").strip().lower() for ln in t.splitlines() if ln.startswith("## ")}

    def _terms(t):
        return set(re.findall(r"[a-z]{5,}", t.lower()))

    base_h = _headings(base); base_t = _terms(base)
    c = _conn()
    try:
        rows = c.execute("SELECT path, name, project FROM journals WHERE path != ?", (j["path"],)).fetchall()
    finally:
        c.close()
    hits = []
    for path, name, proj in rows:
        try:
            other = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sh = base_h & _headings(other)
        if len(sh) < min_shared:
            continue
        ot = _terms(other)
        overlap = round(len(base_t & ot) / max(1, len(base_t)), 2)
        hits.append({"name": name, "project": proj, "path": path,
                     "shared_sections": sorted(sh)[:8], "shared_section_count": len(sh),
                     "term_overlap": overlap})
    hits.sort(key=lambda h: (h["shared_section_count"], h["term_overlap"]), reverse=True)
    return {"journal": j.get("name", name_or_path), "candidate_count": len(hits), "candidates": hits[:limit]}


@mcp.tool()
def journal_audit(name_or_path: str = "", max_age_days: int = 14, check_urls: bool = False, project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Audit a journal against reality: the mechanical half of memory consolidation.

    A journal is only as good as its claims. This extracts every claim a script can
    verify and checks it, so a session can spend its judgment on what's flagged
    instead of re-reading everything:

      - file paths mentioned in backticks -> exist on disk, missing, or server-side
        (host:/... and /opt/-style paths are listed as not checkable from this machine)
      - journal names mentioned -> exist in the index or not
      - state-bearing sections ("current state", "wiring", "se reemplaza", "hoy")
        -> flagged when their newest date is older than max_age_days, or undated;
        sections marked historical/archived are exempt
      - open items ("pendiente", "queda abierto", "TODO", "sin aplicar") -> surfaced
      - http(s) URLs -> optionally HEAD-checked (check_urls=True, slower)

    It reports, it never edits. The workflow: run it, verify the flagged claims with
    judgment (a stale flag is a question, not a verdict), fix the journal, and log
    the audit as an entry so the next session knows when reality was last checked.
    """
    name_or_path, err = _need_journal(name_or_path, project, journal, name, path, "journal_audit", True)
    if err:
        return err
    j = _resolve(name_or_path)
    if not j:
        return {"error": _not_found(name_or_path, "Try journal_list().")}
    jpath = Path(j["path"])
    try:
        text = jpath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Cannot read {jpath}: {e}"}

    bases = [jpath.parent, jpath.parent.parent] + _default_roots()
    remote_prefixes = ("/opt/", "/root/", "/etc/", "/var/", "/usr/", "/tmp/", "/data/", "/home/", "~")

    files_ok: list = []
    files_missing: list = []
    files_remote: list = []
    urls: set = set(re.findall(r"https?://[^\s)\"'`<>\]]+", text))
    seen: set = set()
    for m in re.finditer(r"`([^`\n]{3,220})`", text):
        tok = m.group(1).strip()
        if tok in seen:
            continue
        seen.add(tok)
        if re.match(r"https?://", tok):
            urls.add(tok)
            continue
        # Not a path: code snippets, key:value pairs, globs, templates
        if any(ch in tok for ch in "<>*?\"|=&;") or ": " in tok or "(" in tok or tok.startswith(". "):
            continue
        low = tok.replace("\\", "/")
        if re.match(r"^[\w.-]+\.[a-z]{2,6}/", low):
            urls.add(tok)                     # domain-like: instagram.com/...
            continue
        if re.match(r"^\w[\w.@-]*:/", low) and not re.match(r"^[A-Za-z]:/", low):
            files_remote.append(tok)          # host:/path or user@host:/path
            continue
        if low.startswith(remote_prefixes) or (low.startswith("/") and os.name == "nt"):
            files_remote.append(tok)          # POSIX absolute path: not this machine
            continue
        if "/" not in low:
            continue                          # bare names are too ambiguous to verdict
        if "." not in low.rsplit("/", 1)[-1] and not low.endswith("/"):
            continue                          # no extension and not a dir: code idiom, not a path
        p = Path(tok)
        if p.is_absolute():
            found = p.exists()
        else:
            found = any((b / tok).exists() for b in bases)
            if not found:
                # One level deeper: `journals-drafts/x.md` written from inside a project
                found = any(True for b in bases for _ in b.glob("*/" + low))
        (files_ok if found else files_missing).append(tok)

    # Journal cross-references, against the index by exact name
    ref_ok: list = []
    ref_missing: list = []
    names = {Path(x.replace("\\", "/")).name
             for x in re.findall(r"[\w /\\.-]*JOURNAL[\w-]*\.md", text)}
    names.discard(jpath.name)
    c = _conn()
    try:
        for n in sorted(names):
            row = c.execute("SELECT 1 FROM journals WHERE LOWER(name)=LOWER(?)", (n,)).fetchone()
            (ref_ok if row else ref_missing).append(n)
    finally:
        c.close()

    # State-bearing sections vs their newest date
    state_markers = ("current state", "estado", "actual", "cableado", "wiring",
                     "prendido", "donde vive", "dónde vive", "se reemplaza", "hoy",
                     "vivo", "roadmap", "handoff")
    exempt_markers = ("historic", "históric", "archivado", "archived", "deprecad", "foto ")
    stale: list = []
    undated: list = []
    sections = list(re.finditer(r"^#{2,3} +(.+)$", text, re.M))
    today = datetime.date.today()
    for i, h in enumerate(sections):
        title = h.group(1).strip()
        tl = title.lower()
        if not any(k in tl for k in state_markers):
            continue
        if re.match(r"20\d\d-\d\d-\d\d", tl):
            continue                          # dated log entry, not a living section
        body_end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[h.start():body_end]
        head = body[:400].lower()
        if any(k in tl or k in head for k in exempt_markers):
            continue
        dates = []
        for d in re.findall(r"20\d\d-\d\d-\d\d", body):
            try:
                dates.append(datetime.date.fromisoformat(d))
            except ValueError:
                pass
        if not dates:
            undated.append(title)
        else:
            age = (today - max(dates)).days
            if age > max_age_days:
                stale.append({"section": title, "newest_date": str(max(dates)), "age_days": age})

    # Open items surfaced for judgment
    open_items: list = []
    for ln in text.splitlines():
        if re.search(r"(?i)\b(pendiente|queda abierto|sin aplicar|por hacer|TODO:)", ln):
            s = ln.strip().lstrip("#*->• ").strip()
            if len(s) > 10:
                open_items.append(s[:160])

    report: dict = {
        "journal": jpath.name,
        "path": str(jpath),
        "files": {
            "ok": len(files_ok),
            "missing": files_missing[:30],
            "server_side_not_checked": files_remote[:30],
        },
        "journal_refs": {"ok": ref_ok, "missing": ref_missing},
        "state_sections_stale": stale[:20],
        "state_sections_undated": undated[:20],
        "open_items": {"count": len(open_items), "lines": open_items[:25]},
        "next": "Verify flagged claims with judgment, fix the journal, then log the audit as an entry.",
    }

    if check_urls:
        checked = {}
        for u in sorted(urls)[:20]:
            try:
                req = urllib.request.Request(u, method="HEAD",
                                             headers={"User-Agent": "journal-audit"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    checked[u] = r.status
            except Exception as e:
                checked[u] = str(e)[:80]
        report["urls"] = checked
    else:
        report["urls_found"] = len(urls)

    return report


@mcp.tool()
def journal_config_add_root(path: str) -> dict:
    """Add a root directory to scan (writes to ~/.journal/config.toml)."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return {"error": f"Not a directory: {p}"}
    roots = []
    if _CONFIG.exists():
        try:
            import tomllib
            data = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
            roots = list(data.get("roots") or [])
        except Exception:
            pass
    if str(p) in roots:
        return {"ok": True, "note": "Already configured"}
    roots.append(str(p))
    # Write TOML manually (tomllib is read-only)
    body = "# Journal MCP config\n\nroots = [\n"
    for r in roots:
        body += f'  "{r.replace(chr(92), "/")}",\n'
    body += "]\n"
    _CONFIG.write_text(body, encoding="utf-8")
    return {"ok": True, "config_path": str(_CONFIG), "total_roots": len(roots)}


_CLAUDE_RULE = "# Project Journals: HARD RULE\n\n" + _MANUAL


@mcp.tool()
def journal_get_claude_rule() -> str:
    """
    Return the recommended CLAUDE.md rule that makes your AI AUTO-MAINTAIN your
    journals: read at session start, append after every shipped piece of
    work, update state/roadmap/handoff sections as things change.

    Without this rule, Journal MCP tools sit unused. WITH this rule, every
    AI session opens cold, reads the project journal, and is up to speed
    in 30 seconds, no re-explaining.

    Paste this into your `~/.claude/CLAUDE.md` (global) OR a project's
    `CLAUDE.md` (per-project). Or use `journal_install_rule()` to do it
    automatically.
    """
    return _CLAUDE_RULE


@mcp.tool()
def journal_install_rule(scope: str = "global", confirm: bool = False) -> dict:
    """
    Install the Journal CLAUDE.md rule so your AI actually USES the journals.

    scope: "global" → appends to `~/.claude/CLAUDE.md` (applies to all sessions on this machine)
           "project" → appends to `./CLAUDE.md` in current working directory (per-project)
    confirm: must be True to actually write. Default False = preview only.

    The rule is idempotent: if it's already in the file, this is a no-op.
    Returns: what would be (or was) written and where.
    """
    if scope not in ("global", "project"):
        return {"error": "scope must be 'global' or 'project'"}
    if scope == "global":
        target = Path.home() / ".claude" / "CLAUDE.md"
    else:
        target = Path.cwd() / "CLAUDE.md"
    existing = ""
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Could not read {target}: {e}"}
    # The heading doubles as the "already installed" marker. It changed when the
    # dash went, so both forms count: a buyer who installed the old one must not
    # get the rule appended a second time.
    markers = ("# Project Journals: HARD RULE", "# Project Journals \u2014 HARD RULE")
    if any(m in existing for m in markers):
        return {"ok": True, "already_installed": True, "path": str(target)}
    if not confirm:
        return {
            "preview": True,
            "would_write_to": str(target),
            "would_append": _CLAUDE_RULE,
            "instruction": "Call again with confirm=True to actually write.",
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n\n" if existing.strip() else ""
    try:
        with target.open("a", encoding="utf-8") as f:
            f.write(separator + _CLAUDE_RULE)
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    return {
        "ok": True,
        "installed_to": str(target),
        "bytes_appended": len(separator) + len(_CLAUDE_RULE),
        "next_step": "Restart any open Claude Code tabs so they re-read CLAUDE.md.",
    }


_HOOK_FLAG = "--hook-before-build"


@mcp.tool()
def journal_install_build_check(confirm: bool = False) -> dict:
    """
    Install the before-build check in Claude Code (~/.claude/settings.json, a PreToolUse hook).
    From then on, whenever your AI is about to launch an agent or create a NEW file, it is shown what
    the journals record as already existing for that job, so nobody builds a second tool for the
    same thing. Nothing is blocked: the matches are put in front of your AI as context.

    confirm: False (default) = preview only. True = write it. Idempotent.
    """
    target = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except Exception as e:
        return {"error": f"Could not read {target}: {e}"}
    command = f'"{Path(sys.executable).as_posix()}" "{Path(__file__).resolve().as_posix()}" {_HOOK_FLAG}'
    hooks = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for blk in hooks:
        if any(_HOOK_FLAG in (h.get("command") or "") for h in blk.get("hooks", [])):
            return {"ok": True, "already_installed": True, "path": str(target)}
    entry = {"matcher": "Agent|Task|Write", "hooks": [{"type": "command", "command": command, "timeout": 15}]}
    if not confirm:
        return {"preview": True, "would_write_to": str(target), "would_add_to_hooks.PreToolUse": entry,
                "instruction": "Call again with confirm=True to write it."}
    hooks.append(entry)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    return {"ok": True, "installed_to": str(target), "hook": entry,
            "next_step": "New Claude Code sessions pick it up; open tabs after a restart."}


@mcp.tool()
def journal_backup_to_drive(name_or_path: str = "", remote: str = "gdrive", remote_folder: str = "Journals", project: str = "", journal: str = "", name: str = "", path: str = "") -> dict:
    """
    Upload journal(s) to Google Drive via rclone.

    name_or_path: which journal (empty = ALL indexed journals)
    remote: rclone remote name (default 'gdrive', must be configured: `rclone config create gdrive drive`)
    remote_folder: subfolder on the remote (default 'Journals')

    Each journal uploads to <remote>:<remote_folder>/<project>/<name>.
    Requires rclone installed + 'gdrive' (or your chosen remote) configured.
    """
    name_or_path = _first(name_or_path, project, journal, name, path)
    import shutil
    import subprocess
    if not shutil.which("rclone"):
        return {"error": "rclone not installed. Install: https://rclone.org/install/ then run `rclone config create gdrive drive`"}
    # Both end up in rclone's destination argument: a remote name and a plain folder path.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", remote or ""):
        return {"error": f"remote must be an rclone remote name (letters, digits, _ or -), got: {remote}"}
    if not re.fullmatch(r"[A-Za-z0-9 _./-]+", remote_folder or "") or ".." in remote_folder.split("/"):
        return {"error": f"remote_folder must be a plain folder path, got: {remote_folder}"}
    targets: list[dict] = []
    if name_or_path.strip():
        j = _resolve(name_or_path)
        if not j:
            return {"error": _not_found(name_or_path)}
        targets.append(j)
    else:
        c = _conn()
        try:
            rows = c.execute("SELECT path, name, project FROM journals").fetchall()
        finally:
            c.close()
        targets = [{"path": r[0], "name": r[1], "project": r[2]} for r in rows]
    if not targets:
        return {"error": "No journals to back up. Run journal_index_refresh first."}
    uploaded: list[dict] = []
    failed: list[dict] = []
    for j in targets:
        proj = j.get("project") or "_root"
        dest = f"{remote}:{remote_folder}/{proj}/"
        try:
            result = subprocess.run(
                ["rclone", "copy", j["path"], dest, "--quiet"],
                capture_output=True, text=True, timeout=60,
                stdin=subprocess.DEVNULL,  # an MCP stdio server: a child must never read the protocol stream
            )
            if result.returncode == 0:
                uploaded.append({"name": j["name"], "project": proj, "dest": dest})
            else:
                failed.append({"name": j["name"], "error": result.stderr.strip()[:200]})
        except subprocess.TimeoutExpired:
            failed.append({"name": j["name"], "error": "timeout after 60s"})
        except Exception as e:
            failed.append({"name": j["name"], "error": str(e)[:200]})
    return {
        "ok": len(failed) == 0,
        "uploaded": len(uploaded),
        "failed": len(failed),
        "remote": f"{remote}:{remote_folder}/",
        "details": {"uploaded": uploaded[:10], "failed": failed[:10]},
    }


# ─── Marketplace connector tools ─────────────────────────────────────────────
# Four moves connect an install to the store: pair, browse, get
# (free/owned -> write file; not owned -> checkout link), library. The engine
# NEVER takes payment; checkout always happens on vibedna.ai / Polar.

@mcp.tool()
def journal_pair(token: str = "") -> dict:
    """
    Pair this install to a Vibedna account so you can browse, buy, and re-download
    journals from the chat. Get the connect-token from vibedna.ai/library
    ("Connect your AI"), then call journal_pair(token="vbd_conn_..."). Idempotent:
    with no token it reports the current pairing. The engine never takes payment.
    """
    token = (token or "").strip()
    if not token:
        a = _load_auth()
        if a.get("token"):
            return {"paired": True, "paired_as": a.get("email"), "site": _SITE}
        return {"paired": False,
                "how": f"Log in at {_SITE}/library, copy your token under 'Connect your AI', then journal_pair(token=...)"}
    try:
        res = _http_get("/api/journals/library", token=token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "invalid_token", "how": f"Copy a fresh token from {_SITE}/library"}
        return {"error": f"pair failed: HTTP {e.code}"}
    except Exception as e:
        return {"error": f"pair failed: {e}"}
    email = res.get("paired_as")
    _save_auth({"token": token, "email": email, "site": _SITE})
    return {"paired": True, "paired_as": email, "owns": res.get("count", 0), "site": _SITE}


@mcp.tool()
def journal_market(query: str = "", domain: str = "", limit: int = 20) -> dict:
    """
    Browse the live Vibedna journal shelf (vibedna.ai). Returns each journal with
    its price and a checkout link. No pairing needed to browse. Filter by free-text
    query (title/description/tools/tags) or domain (web, creative-tools, publishing,
    audio-tools).
    """
    try:
        feed = _http_get("/api/journals")
    except Exception as e:
        return {"error": f"could not reach the shelf: {e}", "site": _SITE}
    q = query.lower().strip()
    out = []
    for p in feed.get("products", []):
        if domain and (p.get("domain", "").lower() != domain.lower()):
            continue
        if q:
            hay = " ".join([
                p.get("title", ""), p.get("description", ""),
                " ".join(p.get("tags", []) or []), " ".join(p.get("tools", []) or []),
            ]).lower()
            if q not in hay:
                continue
        out.append({
            "slug": p.get("slug"), "title": p.get("title"), "domain": p.get("domain"),
            "tier": p.get("tier"), "price": p.get("price"), "description": p.get("description"),
            "tools": p.get("tools", []), "status": p.get("status"), "checkout_url": p.get("checkout_url"),
        })
        if len(out) >= max(1, limit):
            break
    return {
        "site": _SITE, "count": len(out), "journals": out,
        "note": "To buy: open a checkout_url and pay on vibedna.ai. "
                "After buying, pair with journal_pair(token) and run journal_get(slug) to install it.",
    }


@mcp.tool()
def journal_get(slug: str, dest_dir: str = "", confirm: bool = False) -> dict:
    """
    Get a journal by slug. If you own it (paired) it writes the .md into dest_dir
    (default ~/.journal/library). If you do NOT own it, returns {price, checkout_url}:
    show the user; if they agree, they pay on vibedna.ai. Pass confirm=True to also open the checkout in the browser. After
    paying, call journal_get again to install. The engine never takes payment.
    """
    slug = (slug or "").strip()
    if not slug:
        return {"error": "slug required", "hint": "run journal_market() to list slugs"}
    # The slug becomes a file name: shelf slugs only, so it cannot climb out of dest_dir.
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", slug):
        return {"error": f"not a journal slug: {slug}", "hint": "run journal_market() to list slugs"}
    auth = _load_auth()
    token = auth.get("token")

    if token:
        dest = Path(dest_dir).expanduser() if dest_dir else (_HOME / "library")
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{slug}.md"
        url = f"{_SITE}/api/journals/download?slug={urllib.parse.quote(slug)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"journal-mcp/{VERSION}", "X-Journal-Token": token})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            target.write_bytes(data)
            return {"status": "owned", "installed_to": str(target), "bytes": len(data)}
        except urllib.error.HTTPError as e:
            if e.code != 402:
                return {"error": f"download failed: HTTP {e.code}"}
            # 402 = not owned yet → fall through to the paywall reply
        except Exception as e:
            return {"error": f"download failed: {e}"}

    try:
        feed = _http_get("/api/journals")
        prod = next((p for p in feed.get("products", []) if p.get("slug") == slug), None)
    except Exception as e:
        return {"error": f"could not reach the shelf: {e}"}
    if not prod:
        return {"error": f"unknown journal: {slug}", "hint": "run journal_market() to list slugs"}

    checkout = prod.get("checkout_url")
    if confirm and checkout:
        try:
            webbrowser.open(checkout)
        except Exception:
            pass
    return {
        "status": "paywall",
        "slug": slug, "title": prod.get("title"), "price": prod.get("price"),
        "checkout_url": checkout,
        "how_to_buy": "Open checkout_url and pay on vibedna.ai. "
                      f"Then pair once (get the token at {_SITE}/library, journal_pair(token)) and call "
                      "journal_get(slug) again to install it.",
        "paired": bool(token),
    }


@mcp.tool()
def journal_library() -> dict:
    """
    List every journal the paired user owns, each with a ready download. Re-install
    free on any machine. Requires pairing (journal_pair). Mirrors your vibedna.ai library.
    """
    auth = _load_auth()
    token = auth.get("token")
    if not token:
        return {"error": "not paired", "how": f"journal_pair(token) with your token from {_SITE}/library"}
    try:
        res = _http_get("/api/journals/library", token=token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "token expired or invalid", "how": f"re-pair from {_SITE}/library"}
        return {"error": f"library failed: HTTP {e.code}"}
    except Exception as e:
        return {"error": f"library failed: {e}"}
    return {"paired_as": res.get("paired_as"), "count": res.get("count", 0), "journals": res.get("journals", [])}


@mcp.tool()
def vibedna_info() -> dict:
    """Product info."""
    return {
        "product": "journal",
        "display_name": "Journals DNA",
        "vendor": "Vibedna",
        "version": VERSION,
        "tagline": "Your AI cannot skip your journal.",
        "site": "https://vibedna.ai/journals",
        "connector": "journal_pair · journal_market · journal_get · journal_library",
        "support": "admin@vibedna.ai",
    }


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] in ("--before-build", "--quick"):
        sys.stdout.reconfigure(encoding="utf-8")   # a Windows console is cp1252: an emoji in a card crashed the print
    if len(sys.argv) > 2 and sys.argv[1] == "--before-build":
        print(_before_build_text(" ".join(sys.argv[2:])))
        sys.exit(0)
    if len(sys.argv) > 2 and sys.argv[1] == "--quick":
        import quickmap
        print(quickmap.quick_map_text(quickmap.quick_map(" ".join(sys.argv[2:]))) or "Nothing recorded for this in any journal.")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] in ("--hook-quick", "--hook-quick-prompt"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            import quickmap
            quickmap.quick_hook(json.loads(sys.stdin.read() or "{}"), prompt=sys.argv[1].endswith("prompt"))
        except Exception:
            pass
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--hook-before-build":
        # Claude Code PreToolUse hook: reads the tool call from stdin, answers with extra context.
        try:
            call = json.loads(sys.stdin.read() or "{}")
            ti = call.get("tool_input") or {}
            if call.get("tool_name") == "Write" and Path(ti.get("file_path") or "").exists():
                sys.exit(0)  # editing an existing file is not building something new
            name = Path(str(ti.get("file_path") or "")).stem.replace("-", " ").replace("_", " ")
            # The file's content is left out on purpose: docstrings and code words matched unrelated
            # cards on a hook file, and noise gets ignored.
            task = " ".join([str(ti.get("description") or ""), str(ti.get("prompt") or ""), name])[:1500]
            text = _before_build_text(task) if task.strip() else ""
            if text:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}))
        except Exception:
            pass
        sys.exit(0)

    # Transport selection:
    #   Default: stdio (for local installs, the only mode that can access
    #     your real project folders)
    #   JOURNAL_TRANSPORT=http: streamable-http on PORT (for cloud hosts like
    #     MCPize). Cloud instances cannot read your local files, so the cloud
    #     listing is primarily for discovery. Install locally from vibedna.ai
    #     for the real thing.
    transport = os.environ.get("JOURNAL_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        port = int(os.environ.get("PORT", "8080"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
