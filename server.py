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

Tools let any Claude session: read it, append entries, search across all
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

mcp = FastMCP("journal")

# ─── Storage ────────────────────────────────────────────────────────────────
_HOME = Path(os.environ.get("JOURNAL_HOME") or str(Path.home() / ".journal"))
_HOME.mkdir(parents=True, exist_ok=True)
_DB = _HOME / "index.sqlite"
_CONFIG = _HOME / "config.toml"

# ─── Marketplace connector (optional: pairs this install with a vibedna.ai account) ─
# The Journal MCP IS the connector to vibedna.ai. No separate MCP. Pairing saves
# a connect-token here; the engine never takes payment (checkout is on the site).
_AUTH = _HOME / "auth.json"
_SITE = (os.environ.get("VIBEDNA_SITE") or "https://vibedna.ai").rstrip("/")

# This copy's version. Bump it when packaging; check_for_update compares it against
# what the site currently publishes, so an installed copy can tell it is behind.
VERSION = "1.0.3"
PRODUCT_SLUG = "journal"


def _http_get(path: str, timeout: int = 20, token: str = "") -> dict:
    url = path if path.startswith("http") else f"{_SITE}{path}"
    headers = {"User-Agent": "journal-mcp/1.2", "Accept": "application/json"}
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


# Journal-class files ONLY: the single source of truth pattern
_JOURNAL_PATTERNS = [
    re.compile(r".*JOURNAL.*\.md$", re.IGNORECASE),
    re.compile(r".*_journal.*\.md$"),
    re.compile(r"journal\.md$", re.IGNORECASE),
]

_SKIP_DIRS = {"node_modules", ".next", ".git", "__pycache__", "_archive", "venv", ".venv", "dist", "build"}


def _is_journal_name(name: str) -> bool:
    return any(pat.match(name) for pat in _JOURNAL_PATTERNS)


def _is_journal_path(p: Path) -> bool:
    """What the indexer treats as a journal, plus the folder journal_get installs into."""
    if p.suffix.lower() != ".md":
        return False
    if _is_journal_name(p.name):
        return True
    low = str(p).replace("\\", "/").lower()
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


def _parse_frontmatter(text: str) -> dict:
    """Parse a leading '--- ... ---' YAML-ish block into a flat dict. {} if none."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta


def _first_h1(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _classify_kind(path: str, meta: dict) -> str:
    k = (meta.get("kind") or "").lower()
    if k in ("raw", "refined", "skill"):
        return k
    low = path.replace("\\", "/").lower()
    if "/skills/" in low:
        return "skill"
    if "/journals-drafts/" in low or "/journals-refined/" in low or "/journals-products/" in low:
        return "refined"
    return "raw"


# ─── Schema ─────────────────────────────────────────────────────────────────
def _conn():
    c = sqlite3.connect(str(_DB))
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_domain ON journals(domain)")
    # Full-text search index (content + name + project), porter-stemmed.
    try:
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS journals_fts USING fts5("
                  "path UNINDEXED, name, project, content, tokenize='porter unicode61')")
    except Exception:
        pass
    c.commit()
    return c


def _scan_root(root: Path, results: list):
    """Walk a root dir; index journal-named files, refined products, and skills."""
    try:
        for p in root.rglob("*.md"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
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
            meta = _parse_frontmatter(text)
            results.append({
                "path": str(p),
                "name": name,
                "project": p.parent.name if p.parent != root else "_root",
                "size_bytes": st.st_size,
                "mtime": st.st_mtime,
                "kind": _classify_kind(str(p), meta),
                "title": meta.get("title") or _first_h1(text) or name,
                "domain": meta.get("domain", ""),
                "tier": meta.get("tier", ""),
                "tools": meta.get("tools", ""),
                "tags": meta.get("tags", ""),
                "description": meta.get("description", ""),
                "source_projects": meta.get("source_projects", ""),
                "outcome": meta.get("outcome", ""),
                "version": meta.get("version", ""),
                "word_count": len(text.split()),
                "content": text,
            })
    except Exception:
        pass


def _index_refresh_internal() -> dict:
    """Rebuild the index (metadata + FTS) by scanning all roots."""
    roots = _default_roots()
    found = []
    for r in roots:
        if r.is_dir():
            _scan_root(r, found)
    c = _conn()
    try:
        now = time.time()
        try:
            c.execute("DELETE FROM journals_fts")
        except Exception:
            pass
        for j in found:
            content = j.get("content", "")
            head = content[:500]
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
            try:
                c.execute("INSERT INTO journals_fts(path, name, project, content) VALUES(?,?,?,?)",
                          (j["path"], j["name"], j["project"], content))
            except Exception:
                pass
        # Prune entries whose files vanished
        existing_paths = {j["path"] for j in found}
        for (p,) in c.execute("SELECT path FROM journals").fetchall():
            if p not in existing_paths:
                c.execute("DELETE FROM journals WHERE path = ?", (p,))
                try:
                    c.execute("DELETE FROM journals_fts WHERE path = ?", (p,))
                except Exception:
                    pass
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


def _resolve(name_or_path: str) -> Optional[dict]:
    """Find a journal by full path OR short name (fuzzy)."""
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
        rows = c.execute(
            "SELECT path, name, project, size_bytes, mtime FROM journals WHERE name = ? OR LOWER(name) = LOWER(?)",
            (nq, nq),
        ).fetchall()
        if not rows:
            like = f"%{nq}%"
            rows = c.execute(
                "SELECT path, name, project, size_bytes, mtime FROM journals "
                "WHERE LOWER(name) LIKE LOWER(?) OR LOWER(project) LIKE LOWER(?) "
                "ORDER BY mtime DESC LIMIT 5",
                (like, like),
            ).fetchall()
        if not rows:
            return None
        r = rows[0]
        return {"path": r[0], "name": r[1], "project": r[2],
                "size_bytes": r[3], "mtime": r[4]}
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

    project: substring filter on project folder name (e.g. 'MYAPP', '')
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
            where.append("LOWER(project) LIKE LOWER(?)")
            params.append(f"%{project}%")
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
def journal_read(name_or_path: str, max_kb: int = 0) -> str:
    """
    Read a journal's full contents.

    name_or_path: full path OR short name (fuzzy). E.g. "MYAPP", "MYAPP_JOURNAL.md", "myapp\\MYAPP_JOURNAL.md"
    max_kb: if > 0, cap response at this many KB (returns tail). 0 = full file.

    Returns the raw markdown.
    """
    j = _resolve(name_or_path)
    if not j:
        return f"Journal not found: '{name_or_path}'. Try journal_list() to see what's available."
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading {j['path']}: {e}"
    if max_kb > 0 and len(content) > max_kb * 1024:
        content = "... [TRUNCATED: older content above] ...\n\n" + content[-max_kb * 1024:]
    return f"# Journal: {j.get('name', name_or_path)}\n_Path: {j['path']}_\n\n{content}"


@mcp.tool()
def journal_append(name_or_path: str, entry: str, tag: str = "", section_header: str = "") -> dict:
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
    """
    j = _resolve(name_or_path)
    if not j:
        return {"error": f"Journal not found: '{name_or_path}'. Use journal_create to make a new one."}
    try:
        path = Path(j["path"])
        existing = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    tag_part = f"[{tag.strip()}] " if tag.strip() else ""
    first_line = (entry.strip().split("\n", 1)[0])[:80]
    header = f"\n\n## {ts} {tag_part}{first_line}\n\n"
    body = entry.strip() + "\n\n---\n"
    new_content = existing.rstrip() + header + body
    try:
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    # Refresh this journal's index entry
    try:
        c = _conn()
        st = path.stat()
        c.execute("UPDATE journals SET size_bytes=?, mtime=?, indexed_at=? WHERE path=?",
                  (st.st_size, st.st_mtime, time.time(), str(path)))
        c.commit()
        c.close()
    except Exception:
        pass
    return {"ok": True, "path": str(path), "appended_bytes": len(header) + len(body), "new_size_kb": round(path.stat().st_size / 1024, 1)}


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

## Handoff for next session

_The first paragraph any new Claude session should read._

## Recent entries

_Append-only timeline, newest at bottom. Use `journal_append` to add._

"""
    target.write_text(body, encoding="utf-8")
    try:
        st = target.stat()
        c = _conn()
        c.execute(
            "INSERT OR REPLACE INTO journals(path, name, project, size_bytes, mtime, indexed_at, head) "
            "VALUES(?,?,?,?,?,?,?)",
            (str(target), name, project.name, st.st_size, st.st_mtime, time.time(), body[:500]),
        )
        c.commit()
        c.close()
    except Exception:
        pass
    return {"ok": True, "path": str(target), "size_kb": round(target.stat().st_size / 1024, 1)}


@mcp.tool()
def journal_search(query: str, project: str = "", kind: str = "", limit: int = 10) -> dict:
    """
    Full-text search across journal contents, ranked best-first (FTS5 + bm25).

    query: words or a phrase to find inside the markdown
    project: filter by project substring
    kind: filter by kind (raw | refined | skill), empty = all
    limit: max results

    Returns matched journals ranked by relevance, each with a context snippet.
    """
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
            except Exception:
                pass
        if need_refresh:
            _index_refresh_internal()
        results = []
        used_fts = False
        try:
            terms = re.findall(r"[A-Za-z0-9_]+", query)
            if terms:
                # OR the terms so recall stays high; bm25 floats the best matches
                # (most terms hit) to the top. Implicit-AND was too strict for
                # casual multi-word queries.
                match = " OR ".join(terms)
                rows = c.execute(
                    "SELECT f.path, f.name, f.project, bm25(journals_fts) AS score, "
                    "snippet(journals_fts, 3, '[', ']', ' ... ', 12) AS snip "
                    "FROM journals_fts f WHERE journals_fts MATCH ? ORDER BY score LIMIT ?",
                    (match, limit * 4),
                ).fetchall()
                used_fts = True
                for path, name, proj, score, snip in rows:
                    meta = c.execute("SELECT kind, project, mtime FROM journals WHERE path=?", (path,)).fetchone()
                    if meta:
                        if kind and (meta[0] or "").lower() != kind.lower():
                            continue
                        if project and project.lower() not in (meta[1] or "").lower():
                            continue
                        mt = meta[2]
                    else:
                        mt = time.time()
                    results.append({
                        "name": name, "project": proj, "path": path,
                        "score": round(-float(score), 2),
                        "snippet": snip.replace("\n", " "),
                        "updated_ago": _ago(time.time() - mt),
                    })
                    if len(results) >= limit:
                        break
        except Exception:
            used_fts = False
        if not used_fts:
            rows = c.execute("SELECT path, name, project, mtime FROM journals ORDER BY mtime DESC").fetchall()
            q_lower = query.lower()
            for path, name, proj, mtime in rows:
                if project and project.lower() not in (proj or "").lower():
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
    return {"query": query, "count": len(results), "ranked": used_fts, "matches": results}


@mcp.tool()
def journal_list_sections(name_or_path: str) -> dict:
    """List the H2 sections of a journal so you know where to append."""
    j = _resolve(name_or_path)
    if not j:
        return {"error": f"Journal not found: '{name_or_path}'"}
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    sections = []
    for line in content.splitlines():
        if line.startswith("## "):
            sections.append(line[3:].strip())
    return {"path": j["path"], "sections": sections}


@mcp.tool()
def journal_read_section(name_or_path: str, section: str) -> str:
    """
    Read just one section of a journal by name (case-insensitive substring match).
    Returns the content between '## <section>' and the next '##'.
    """
    j = _resolve(name_or_path)
    if not j:
        return f"Journal not found: '{name_or_path}'"
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
    return "\n".join(captured)


@mcp.tool()
def journal_update_section(name_or_path: str, section: str, new_content: str, mode: str = "replace") -> dict:
    """
    Update a specific section of the journal.

    section: section title (case-insensitive substring match, e.g. 'roadmap', 'current state')
    new_content: the new section body (without the '## ...' header, that's preserved)
    mode: 'replace' (default, rewrites the section body)
        | 'append' (adds new_content to the end of the section)
        | 'prepend' (inserts new_content at the top of the section body)

    Use for: keeping Current state / Roadmap fresh, logging Decisions, recording Incidents.
    """
    if mode not in ("replace", "append", "prepend"):
        return {"error": f"mode must be replace/append/prepend, got {mode}"}
    j = _resolve(name_or_path)
    if not j:
        return {"error": f"Journal not found: '{name_or_path}'"}
    try:
        path = Path(j["path"])
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
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
        return {"error": f"Section '{section}' not found"}
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
    new_full = "\n".join(new_lines).rstrip() + "\n"
    try:
        path.write_text(new_full, encoding="utf-8")
    except Exception as e:
        return {"error": f"Write failed: {e}"}
    return {"ok": True, "section": section, "mode": mode, "new_size_kb": round(path.stat().st_size / 1024, 1)}


@mcp.tool()
def journal_handoff_brief(name_or_path: str, max_lines: int = 50) -> str:
    """
    Render a journal as a concise handoff brief for a new session to read.
    Pulls: file header + most recent N entries (separated by --- dividers).

    name_or_path: which journal
    max_lines: total line cap of the brief (default 50)
    """
    j = _resolve(name_or_path)
    if not j:
        return f"Journal not found: '{name_or_path}'"
    try:
        content = Path(j["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Read error: {e}"
    # Take first 10 lines (header) + last N entries
    lines = content.splitlines()
    header_lines = []
    for ln in lines[:15]:
        header_lines.append(ln)
        if ln.startswith("##"):
            break
    # Walk from end, gather last N entries (split by ---)
    entries = content.split("\n---\n")
    recent = entries[-5:]  # last 5 entries
    brief = "\n".join(header_lines)
    brief += "\n\n--- RECENT ENTRIES (newest last) ---\n\n"
    brief += "\n---\n".join(recent)
    out_lines = brief.splitlines()
    if len(out_lines) > max_lines:
        out_lines = out_lines[:max_lines] + ["", f"_... [truncated, full file: {j['path']}]_"]
    return "\n".join(out_lines)


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
def journal_overlap_check(name_or_path: str, min_shared: int = 3, limit: int = 10) -> dict:
    """
    Dedup helper: find other journals that overlap this one, by shared H2 section
    headings and shared significant terms. Use before pricing to catch two journals
    that teach the same skill (the Refinery dedup step).
    """
    j = _resolve(name_or_path)
    if not j:
        return {"error": f"Journal not found: '{name_or_path}'"}
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


_CLAUDE_RULE = """\
# Project Journals: HARD RULE

Every project has ONE `<PROJECT>_JOURNAL.md` = the single source of truth.
It survives session compaction, account switches, and machine wipes.

**Session start:**
1. If you can guess the project from the current working directory:
   call `mcp__journal__journal_handoff_brief("<PROJECT>")` to catch up on
   where the last session stopped. Read it before you do anything else.

**While working:**
- Anything that future-you (or another agent) would want to know (a shipped
  feature, a non-obvious fix, a decision with reasoning, an incident, a
  pivot): `mcp__journal__journal_append("<PROJECT>", entry, tag)` THAT TURN.
  Don't batch. Don't trust memory.

**State changes:**
- Current state shifts → `mcp__journal__journal_update_section("<PROJECT>",
  "Current state", new_content, mode="replace")`
- Roadmap shifts → same tool, section="Roadmap"
- New decision → section="Decisions log", mode="append"

**End of session:**
- Update the `Handoff for next session` section so the next agent knows
  what to read first.

**No journal yet?**
- `mcp__journal__journal_create("<PROJECT>_JOURNAL.md", project_dir="<abs path>")`
  Scaffolds with Vision / Current state / Roadmap / Decisions / Incidents /
  Handoff / Recent entries sections.

The journal is how context survives. Treat it as a load-bearing surface,
not an optional log.
"""


@mcp.tool()
def journal_get_claude_rule() -> str:
    """
    Return the recommended CLAUDE.md rule that makes Claude AUTO-MAINTAIN your
    journals: read at session start, append after every shipped piece of
    work, update state/roadmap/handoff sections as things change.

    Without this rule, Journal MCP tools sit unused. WITH this rule, every
    Claude session opens cold, reads the project journal, and is up to speed
    in 30 seconds, no re-explaining.

    Paste this into your `~/.claude/CLAUDE.md` (global) OR a project's
    `CLAUDE.md` (per-project). Or use `journal_install_rule()` to do it
    automatically.
    """
    return _CLAUDE_RULE


@mcp.tool()
def journal_install_rule(scope: str = "global", confirm: bool = False) -> dict:
    """
    Install the Journal CLAUDE.md rule so Claude actually USES the journals.

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


@mcp.tool()
def journal_backup_to_drive(name_or_path: str = "", remote: str = "gdrive", remote_folder: str = "Journals") -> dict:
    """
    Upload journal(s) to Google Drive via rclone.

    name_or_path: which journal (empty = ALL indexed journals)
    remote: rclone remote name (default 'gdrive', must be configured: `rclone config create gdrive drive`)
    remote_folder: subfolder on the remote (default 'Journals')

    Each journal uploads to <remote>:<remote_folder>/<project>/<name>.
    Requires rclone installed + 'gdrive' (or your chosen remote) configured.
    """
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
            return {"error": f"Journal not found: '{name_or_path}'"}
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
# Four moves: pair, browse, get
# (free/owned -> write file; not owned -> checkout link), library. The engine
# NEVER takes payment; checkout always happens on vibedna.ai / Polar.

@mcp.tool()
def journal_pair(token: str = "") -> dict:
    """
    Pair this install to a VibeDNA account so you can browse, buy, and re-download
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
    Browse the live VibeDNA journal shelf (vibedna.ai). Returns each journal with
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
            req = urllib.request.Request(url, headers={"User-Agent": "journal-mcp/1.2", "X-Journal-Token": token})
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
        "display_name": "Journal",
        "vendor": "VibeDNA",
        "version": VERSION,
        "tagline": "Every session keeps a journal. Browse, buy, and own journals from the chat.",
        "site": "https://vibedna.ai/journals",
        "connector": "journal_pair · journal_market · journal_get · journal_library",
        "support": "admin@vibedna.ai",
        "source": "https://github.com/marstudio360/vibedna-journal-mcp",
    }


if __name__ == "__main__":
    # Transport selection:
    #   Default: stdio (for local installs, the only mode that can access
    #     your real project folders)
    #   JOURNAL_TRANSPORT=http: streamable-http on PORT (for cloud hosts).
    #     Cloud instances cannot read your local files, so the cloud
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
