#!/usr/bin/env python3
"""Open your journals in Obsidian.

Two commands, both a dry run unless --apply is given:

  python obsidian.py add-frontmatter --root <dir> [--root <dir>...] [--apply]
      Gives every live journal (found the way the journal server finds them) an Obsidian
      Properties block, so the vault can filter, sort and group journals:
          ---
          type: journal
          project: <slug>
          status: live
          tags: [journal, project/<slug>]
          aliases: ["<Project> journal"]
          updated: 2026-10-30T00:26:00
          entries: 1259
          ---
      Only files with no frontmatter get it. The body is kept byte for byte, the write is
      atomic (temp file + os.replace) and a file that changed while we worked is left alone.

  python obsidian.py vault --root <dir> [--apply]
      Writes a map of the journals into <dir>/_obsidian (START HERE.md, Journals.base,
      Journals map.canvas) and a minimal <dir>/.obsidian config (app.json, core-plugins.json).
      Never writes workspace.json.

Stdlib only. Importable: the store vault builder reuses make_base, make_canvas and friends.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024  # bigger files can freeze Obsidian on Windows
OUT_DIR = "_obsidian"
STALE_DAYS = 14
NEWEST_ENTRIES = 20

_DATED_H2 = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)
_DATED_PARSE = re.compile(r"^## (\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?\s*(.*)$")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
# A heading link [[Note#Heading]] breaks on these characters, so only clean headings are linked.
_BAD_HEADING_CHARS = set(":|#^[]%")
# A wikilink target (the path part) breaks on these.
_BAD_PATH_CHARS = set("#|^[]")
_CODE_DIRS = ["node_modules", ".next", ".git", "venv", ".venv", "dist", "build", "__pycache__"]
_STATE_HEADING = "Current state"
_HANDOFF_HEADING = "Handoff for next session"
_ACRONYMS = {"ai", "ia", "mcp", "api", "gpu", "pc", "ui", "ux", "ig", "yt", "seo", "rpg", "tg",
             "asmr", "mvp", "sdk", "cli", "url", "nft", "dj", "ugc", "llm", "kdp", "sa3"}
_YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off", "~"}


# ─── Journal rules (same as the journal server) ───────────────────────────────

_FALLBACK_PATTERNS = [
    re.compile(r".*JOURNAL.*\.md$", re.IGNORECASE),
    re.compile(r".*_journal.*\.md$"),
    re.compile(r"journal\.md$", re.IGNORECASE),
]
_FALLBACK_SKIP = {"node_modules", ".next", ".git", "__pycache__", "_archive", "venv", ".venv",
                  "dist", "build", "fixtures"}
_PRODUCT_DIRS = ("/journals-drafts/", "/journals-refined/", "/journals-products/")


def _fallback_is_journal_path(p: Path) -> bool:
    if p.suffix.lower() != ".md":
        return False
    if any(pat.match(p.name) for pat in _FALLBACK_PATTERNS):
        return True
    low = str(p).replace("\\", "/").lower()
    return any(d in low for d in _PRODUCT_DIRS)


def _fallback_classify(path: str, meta: dict) -> str:
    k = (meta.get("kind") or "").lower()
    if k in ("raw", "refined", "skill"):
        return k
    low = path.replace("\\", "/").lower()
    if "/skills/" in low:
        return "skill"
    if any(d in low for d in _PRODUCT_DIRS):
        return "refined"
    return "raw"


def _fallback_parse_frontmatter(text: str) -> dict:
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


_RULES = None


def rules():
    """(skip_dirs, is_journal_path, classify_kind, parse_frontmatter, default_roots).
    Taken from server.py when it imports, so both always agree on what a journal is."""
    global _RULES
    if _RULES is None:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        try:
            import server as srv
            _RULES = (set(srv._SKIP_DIRS), srv._is_journal_path, srv._classify_kind,
                      srv._parse_frontmatter, srv._default_roots)
        except Exception:
            _RULES = (set(_FALLBACK_SKIP), _fallback_is_journal_path, _fallback_classify,
                      _fallback_parse_frontmatter, lambda: [])
    return _RULES


# ─── Reading one journal ──────────────────────────────────────────────────────

def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def _no_dashes(s: str) -> str:
    return s.replace(chr(0x2014), ", ").replace(chr(0x2013), "-")


def has_frontmatter(text: str) -> bool:
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return False
    return any(ln.rstrip() in ("---", "...") for ln in lines[1:])


def project_slug(path: Path) -> tuple[str, str]:
    """(slug, display name). WEBWEAVE_JOURNAL.md -> webweave; JOURNAL_MCP_JOURNAL.md -> journal-mcp;
    journal.md -> its folder name."""
    def tokens(s: str) -> list[str]:
        return [t for t in re.split(r"[^0-9A-Za-z]+", _fold(s)) if t]

    toks = tokens(path.stem)
    low = [t.lower() for t in toks]
    if "journal" in low:
        del toks[len(low) - 1 - low[::-1].index("journal")]
    if not toks:
        toks = tokens(path.parent.name)
    slug = "-".join(t.lower() for t in toks) or "journal"
    if slug.replace("-", "").isdigit():
        slug = "p-" + slug
    words = [t.upper() if t.lower() in _ACRONYMS else t.lower() for t in toks] or [slug]
    words[0] = words[0][:1].upper() + words[0][1:]
    return slug, " ".join(words)


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./ -]*", s) and s.lower() not in _YAML_WORDS
            and not s.endswith(" ") and ": " not in s and " #" not in s):
        return s
    return "'" + s.replace("'", "''") + "'"


@dataclass
class Journal:
    path: Path
    rel: str                 # vault-relative, forward slashes
    size: int
    too_big: bool = False
    has_fm: bool = False
    meta: dict = field(default_factory=dict)
    slug: str = ""
    display: str = ""
    entries: int = 0
    updated: str = ""        # ISO, seconds
    headings: dict = field(default_factory=dict)   # lowercased text -> (text as written, line)
    dated: list = field(default_factory=list)      # (datetime, line, rest of heading)
    mentions: set = field(default_factory=set)     # lowercased journal-like tokens in the text
    newline: str = "\n"
    raw: bytes = b""


_MENTION = re.compile(r"[\w\-]*journal[\w\-]*", re.IGNORECASE)


def read_journal(path: Path, root: Path | None = None, keep_raw: bool = False) -> Journal:
    st = path.stat()
    rel = path.name
    if root is not None:
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.name
    j = Journal(path=path, rel=rel, size=st.st_size)
    j.slug, j.display = project_slug(path)
    if st.st_size > MAX_BYTES:
        j.too_big = True
        return j
    raw = path.read_bytes()
    if keep_raw:
        j.raw = raw
    text = raw.decode("utf-8", errors="replace")
    j.newline = "\r\n" if "\r\n" in text[:20000] else "\n"
    body = text.lstrip("﻿")
    j.has_fm = has_frontmatter(body)
    j.meta = rules()[3](body) if j.has_fm else {}
    j.entries = len(_DATED_H2.findall(body))
    in_fence = False
    for i, line in enumerate(body.splitlines(), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            t = m.group(2).strip()
            j.headings.setdefault(t.lower(), (t, i))
        d = _DATED_PARSE.match(line)
        if d:
            y, mo, da, hh, mi, rest = d.groups()
            try:
                dt = datetime(int(y), int(mo), int(da), int(hh or 0), int(mi or 0))
            except ValueError:
                continue
            j.dated.append((dt, i, rest.strip()))
    if j.dated:
        j.updated = max(d[0] for d in j.dated).strftime("%Y-%m-%dT%H:%M:%S")
    else:
        j.updated = datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    j.mentions = {t.lower().removesuffix(".md") for t in _MENTION.findall(body)}
    return j


def frontmatter_block(j: Journal) -> str:
    alias = f"{j.display} journal"
    lines = [
        "---",
        "type: journal",
        f"project: {_yaml_scalar(j.slug)}",
        "status: live",
        f"tags: [journal, project/{j.slug}]",
        f"aliases: [{json.dumps(alias, ensure_ascii=False)}]",
        f"updated: {j.updated}",
        f"entries: {j.entries}",
        "---",
    ]
    return j.newline.join(lines) + j.newline


# ─── Finding live journals ────────────────────────────────────────────────────

def find_journals(roots: list[Path]) -> list[tuple[Path, Path]]:
    """(root, path) for every live (raw) journal under the roots, never entering skipped folders."""
    skip, is_jp, classify, parse_fm, _ = rules()
    skip = set(skip) | {OUT_DIR, ".obsidian"}
    seen, out = set(), []
    for root in roots:
        root = Path(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in skip)
            for f in sorted(filenames):
                if not f.lower().endswith(".md"):
                    continue
                p = Path(dirpath) / f
                try:
                    if not is_jp(p):
                        continue
                    with open(p, "rb") as fh:
                        head = fh.read(8192).decode("utf-8", errors="replace").lstrip("﻿")
                except OSError:
                    continue
                if classify(str(p), parse_fm(head) if has_frontmatter(head) else {}) != "raw":
                    continue
                key = os.path.normcase(os.path.realpath(p))
                if key in seen:
                    continue
                seen.add(key)
                out.append((root, p))
    return out


# ─── add-frontmatter ──────────────────────────────────────────────────────────

def _prepend_atomic(j: Journal, block: str) -> str:
    """'added' | 'changed' (file moved under us, left alone) | 'error: ...'."""
    raw = j.raw
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    new = bom + block.encode("utf-8") + raw[len(bom):]
    fd, tmp = tempfile.mkstemp(prefix="." + j.path.name + ".", suffix=".obsidian-tmp", dir=str(j.path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(new)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, os.stat(j.path).st_mode & 0o777)
        except OSError:
            pass
        st = j.path.stat()
        if st.st_size != len(raw) or j.path.read_bytes() != raw:
            os.unlink(tmp)
            return "changed"
        os.replace(tmp, j.path)
        return "added"
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return f"error: {type(e).__name__}: {e}"


def add_frontmatter(roots: list[Path], apply: bool = False) -> dict:
    rep = {"journals": 0, "would_add": [], "added": [], "has_frontmatter": [], "too_big": [],
           "read_only": [], "changed": [], "errors": []}
    for root, p in find_journals(roots):
        rep["journals"] += 1
        try:
            j = read_journal(p, root, keep_raw=True)
        except OSError as e:
            rep["errors"].append((str(p), f"{type(e).__name__}: {e}"))
            continue
        if j.too_big:
            rep["too_big"].append((str(p), j.size))
            continue
        if j.has_fm:
            rep["has_frontmatter"].append(str(p))
            continue
        if not os.access(p, os.W_OK):
            # A read-only journal is a mirror some sync overwrites: the block belongs in the master copy.
            rep["read_only"].append(str(p))
            continue
        rep["would_add"].append(str(p))
        if apply:
            r = _prepend_atomic(j, frontmatter_block(j))
            if r == "added":
                rep["added"].append(str(p))
            elif r == "changed":
                rep["changed"].append(str(p))
            else:
                rep["errors"].append((str(p), r))
    return rep


# ─── YAML (tiny emitter, enough for a .base file) ─────────────────────────────

def to_yaml(obj, indent: int = 0) -> str:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out.append(to_yaml(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(v) if not isinstance(v, (dict, list)) else ('{}' if isinstance(v, dict) else '[]')}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and v:
                inner = to_yaml(v, indent + 1).splitlines()
                out.append(f"{pad}- {inner[0].lstrip()}")
                out.extend(inner[1:])
            elif isinstance(v, list) and v:
                out.append(f"{pad}-")
                out.append(to_yaml(v, indent + 1))
            else:
                out.append(f"{pad}- {_yaml_scalar(v)}")
    else:
        out.append(f"{pad}{_yaml_scalar(obj)}")
    return "\n".join(out)


# ─── Vault pieces ─────────────────────────────────────────────────────────────

def make_base(views: list[dict] | None = None, properties: dict | None = None) -> str:
    """An Obsidian Bases file over every note tagged #journal: one row per journal."""
    order = ["file.name", "project", "status", "updated", "entries"]
    if properties is None:
        properties = {
            "file.name": {"displayName": "Journal"},
            "note.project": {"displayName": "Project"},
            "note.status": {"displayName": "Status"},
            "note.updated": {"displayName": "Updated"},
            "note.entries": {"displayName": "Entries"},
        }
    if views is None:
        views = [
            {"type": "table", "name": "By updated", "order": order,
             "sort": [{"property": "note.updated", "direction": "DESC"}]},
            {"type": "kanban", "name": "By status", "groupBy": {"property": "note.status", "direction": "ASC"},
             "order": order},
            {"type": "table", "name": "Stale",
             "filters": {"and": [f'note.updated < now() - "{STALE_DAYS}d"']},
             "order": order, "sort": [{"property": "note.updated", "direction": "ASC"}]},
        ]
    filters = {"and": ['file.hasTag("journal")']}
    return to_yaml({"filters": filters, "properties": properties, "views": views}) + "\n"


def make_live_base() -> str:
    """Bases over journals WITHOUT frontmatter, from file properties only. Journals that other tools sync or append
    to are better left without a prepended block (8 more lines at the top would shift every FILE.md:line citation);
    Obsidian already knows each file's name, folder, mtime and size."""
    order = ["file.name", "file.folder", "file.mtime", "file.size"]
    properties = {"file.name": {"displayName": "Journal"}, "file.folder": {"displayName": "Folder"},
                  "file.mtime": {"displayName": "Updated"}, "file.size": {"displayName": "Size"}}
    views = [
        {"type": "table", "name": "By updated", "order": order,
         "sort": [{"property": "file.mtime", "direction": "DESC"}]},
        {"type": "table", "name": "Stale", "filters": {"and": [f'file.mtime < now() - "{STALE_DAYS}d"']},
         "order": order, "sort": [{"property": "file.mtime", "direction": "ASC"}]},
        {"type": "table", "name": "Biggest", "order": order,
         "sort": [{"property": "file.size", "direction": "DESC"}]},
    ]
    filters = {"and": ['file.name.lower().contains("journal")', 'file.ext == "md"', 'file.folder != "_obsidian"']}
    return to_yaml({"filters": filters, "properties": properties, "views": views}) + "\n"


def _node_id(*parts: str) -> str:
    return hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()[:16]


def make_canvas(groups: dict[str, list[dict]], edges: list[tuple[str, str]] | None = None,
                extra_nodes: list[dict] | None = None) -> dict:
    """JSON Canvas 1.0. groups: label -> [{"file": rel, "subpath": "#Heading" or ""}].
    edges: (from file, to file). Groups are laid out on shelves, files in a grid inside each."""
    W, H, GAP, PAD, TOP = 400, 260, 40, 40, 60
    COLS, SHELF = 3, 4200
    nodes: list[dict] = list(extra_nodes or [])
    children: list[dict] = []
    by_file: dict[str, str] = {}
    x = y = 0
    shelf_h = 0
    if nodes:
        y = max(n["y"] + n["height"] for n in nodes) + 2 * GAP
    for gi, (label, files) in enumerate(sorted(groups.items(), key=lambda kv: kv[0].lower())):
        if not files:
            continue
        cols = min(COLS, len(files))
        rows = (len(files) + cols - 1) // cols
        gw = PAD * 2 + cols * W + (cols - 1) * GAP
        gh = TOP + PAD + rows * H + (rows - 1) * GAP
        if x and x + gw > SHELF:
            x, y, shelf_h = 0, y + shelf_h + 2 * GAP, 0
        nodes.append({"id": _node_id("group", label), "type": "group", "label": label,
                      "x": x, "y": y, "width": gw, "height": gh})
        for i, f in enumerate(files):
            r, c = divmod(i, cols)
            node = {"id": _node_id("file", f["file"]), "type": "file", "file": f["file"],
                    "x": x + PAD + c * (W + GAP), "y": y + TOP + r * (H + GAP), "width": W, "height": H}
            if f.get("subpath"):
                node["subpath"] = f["subpath"]
            children.append(node)
            by_file[f["file"]] = node["id"]
        x += gw + 2 * GAP
        shelf_h = max(shelf_h, gh)
    out_edges = []
    for a, b in edges or []:
        if a in by_file and b in by_file and a != b:
            out_edges.append({"id": _node_id("edge", a, b), "fromNode": by_file[a], "toNode": by_file[b],
                              "toEnd": "arrow"})
    return {"nodes": nodes + children, "edges": out_edges}


def core_plugins(existing: dict | None = None) -> dict:
    d = dict(existing or {})
    for k in ("file-explorer", "global-search", "switcher", "graph", "backlink", "outgoing-link",
              "tag-pane", "properties", "page-preview", "outline", "canvas", "bases", "command-palette",
              "bookmarks", "file-recovery", "word-count"):
        d[k] = True
    return d


def code_dir_filter() -> str:
    names = "|".join(re.escape(n) for n in _CODE_DIRS)
    return f"/(^|\\/)({names})(\\/|$)/"


def app_json(ignore: list[str], existing: dict | None = None) -> dict:
    d = dict(existing or {})
    filters = list(d.get("userIgnoreFilters") or [])
    for f in [code_dir_filter()] + ignore:
        if f not in filters:
            filters.append(f)
    d["userIgnoreFilters"] = filters
    d.setdefault("alwaysUpdateLinks", True)
    # Journals and generated notes wrap long paragraphs over several lines; with Obsidian's default every wrapped
    # line showed as its own line ("adds to" / "as it works", seen on the first screenshots 2026-10-30).
    d.setdefault("strictLineBreaks", True)
    return d


def folders_without_md(root: Path, max_depth: int = 2) -> list[str]:
    """Topmost folders (vault-relative, trailing slash) whose whole subtree holds no .md file, at most
    max_depth levels deep (a big projects folder has thousands deeper down; the top ones carry the noise).
    Code folders and dot folders are not walked: the regex filter and Obsidian already hide them."""
    skip = set(rules()[0]) | set(_CODE_DIRS) | {OUT_DIR}
    has_md: dict[str, bool] = {}
    parent: dict[str, str] = {}
    order: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.startswith("."))
        rel = Path(dirpath).relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        order.append(rel)
        has_md[rel] = any(f.lower().endswith(".md") for f in filenames)
        for d in dirnames:
            parent[(rel + "/" + d) if rel else d] = rel
    for rel in reversed(order):
        if has_md[rel] and rel in parent:
            has_md[parent[rel]] = True
    out = []
    for rel in order:
        if rel and rel.count("/") < max_depth and not has_md[rel] and has_md.get(parent.get(rel, ""), True):
            out.append(rel + "/")
    return out


def _esc(s: str, table: bool = False) -> str:
    s = _no_dashes(s)
    for ch in "[]#`<*^":
        s = s.replace(ch, "\\" + ch)
    s = s.replace("==", "\\=\\=").replace("~~", "\\~\\~")
    if table:
        s = s.replace("|", "\\|")
    return s


def _clean_heading(t: str) -> bool:
    return not (set(t) & _BAD_HEADING_CHARS)


def heading_link(j: Journal, heading: str, label: str) -> str:
    """[[path#Heading\\|label]] when the journal has that heading and it is safe to link, else ''."""
    if j.too_big or set(j.rel) & _BAD_PATH_CHARS:
        return ""
    found = j.headings.get(heading.lower())
    if not found or not _clean_heading(found[0]):
        return ""
    return f"[[{j.rel.removesuffix('.md')}#{found[0]}\\|{label}]]"


def file_link(j: Journal, label: str) -> str:
    if set(j.rel) & _BAD_PATH_CHARS:
        return _esc(label, table=True)
    return f"[[{j.rel.removesuffix('.md')}\\|{_esc(label, table=True)}]]"


def start_here(journals: list[Journal]) -> str:
    rows = sorted(journals, key=lambda j: j.meta.get("updated") or j.updated, reverse=True)
    L = [
        "# START HERE",
        "",
        "This folder is a map of every project journal under this vault, rebuilt by `obsidian.py vault`.",
        "Each project keeps one journal: an append-only file with what was built, what was decided and why,",
        "what is running now and what is open. Edit the journals, never this map: the next build overwrites it.",
        "",
        "## How an AI should read this vault",
        "",
        "1. Read this map first to find the project's journal.",
        f"2. Open that journal at **{_STATE_HEADING}**: what is true right now.",
        f"3. Then read **{_HANDOFF_HEADING}**: the open work and where the last session stopped.",
        "4. Search the journals before answering how something works or why it was decided.",
        "5. Append, never rewrite: a new entry goes at the end as `## YYYY-MM-DD HH:MM [tag] title`.",
        f"   Keep {_STATE_HEADING} and the Handoff up to date by replacing those sections whole.",
        "",
        "Views: `Journals.base` (tables by last update, stale journals and biggest files) and",
        "`Journals map.canvas` (every journal by folder, arrows where one journal names another).",
        "",
        "## Journals",
        "",
        f"{len(rows)} journals. Links open the section directly; a blank cell means the journal has no such heading.",
        "",
        "| Project | Status | Updated | Size KB | Current state | Handoff |",
        "|---|---|---|---|---|---|",
    ]
    for j in rows:
        if j.too_big:
            L.append(f"| {_esc(j.rel, True)} | too big to open here | | {j.size // 1024} | | |")
            continue
        status = _esc(j.meta.get("status") or "live", True)
        upd = (j.meta.get("updated") or j.updated).replace("T", " ")[:16]
        L.append(f"| {file_link(j, j.slug)} | {status} | {upd} | {max(1, j.size // 1024)} | "
                 f"{heading_link(j, _STATE_HEADING, 'state')} | {heading_link(j, _HANDOFF_HEADING, 'handoff')} |")
    newest = sorted(((dt, ln, rest, j) for j in journals for dt, ln, rest in j.dated),
                    key=lambda t: t[0], reverse=True)[:NEWEST_ENTRIES]
    L += ["", f"## Newest {NEWEST_ENTRIES} entries", "",
          "Plain text on purpose: entry titles change, so they are cited by file and line, not linked.", ""]
    for dt, ln, rest, j in newest:
        title = rest if len(rest) <= 160 else rest[:157] + "..."
        name = j.path.name.replace("`", "")
        L.append(f"- {dt:%Y-%m-%d %H:%M} · `{name}` line {ln}: {_esc(title)}")
    return "\n".join(L) + "\n"


def build_vault(root: Path, apply: bool = False, out: Path | None = None) -> dict:
    """out: where to write (default: root itself); a different folder previews the vault files."""
    root = Path(root)
    dest = Path(out) if out else root
    journals = []
    for r, p in find_journals([root]):
        # throwaway site worktrees (shopsite-site-wt-audio, -wt-perf) hold stale copies of the same journals
        if re.search(r"-wt-[^/\\]*[/\\]", str(p.relative_to(root)) + "/"):
            continue
        try:
            journals.append(read_journal(p, root))
        except OSError:
            continue
    usable = [j for j in journals if not j.too_big]
    groups: dict[str, list[dict]] = {}
    for j in usable:
        top = j.rel.split("/")[0] if "/" in j.rel else "(root)"
        sub = ""
        found = j.headings.get(_STATE_HEADING.lower())
        if found and _clean_heading(found[0]):
            sub = "#" + found[0]
        groups.setdefault(top, []).append({"file": j.rel, "subpath": sub})
    stems = {}
    for j in usable:
        s = j.path.stem.lower()
        if s != "journal" and len(s) >= 6:
            stems.setdefault(s, j.rel)
    edges = sorted({(j.rel, stems[t]) for j in usable for t in j.mentions if t in stems and stems[t] != j.rel})
    canvas = make_canvas(groups, edges)
    base = make_live_base()
    md = start_here(journals)
    ignore = folders_without_md(root) + [j.rel for j in journals if j.too_big]
    obs = dest / ".obsidian"

    def load(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    app = app_json(ignore, load(obs / "app.json"))
    cores = core_plugins(load(obs / "core-plugins.json"))
    files = {
        dest / OUT_DIR / "START HERE.md": md,
        dest / OUT_DIR / "Journals.base": base,
        dest / OUT_DIR / "Journals map.canvas": json.dumps(canvas, indent=2, ensure_ascii=False) + "\n",
        obs / "app.json": json.dumps(app, indent=2, ensure_ascii=False) + "\n",
        obs / "core-plugins.json": json.dumps(cores, indent=2) + "\n",
    }
    if apply:
        for p, content in files.items():
            write_text_atomic(p, content)
    links = md.count("[[")
    return {"journals": len(journals), "too_big": [j.rel for j in journals if j.too_big],
            "canvas_nodes": len(canvas["nodes"]), "canvas_edges": len(canvas["edges"]),
            "links": links, "ignore_filters": len(app["userIgnoreFilters"]),
            "files": [str(p) for p in files], "written": apply}


def write_text_atomic(p: Path, content: str) -> None:
    assert p.name.lower() not in ("workspace.json", "workspace-mobile.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name + ".", suffix=".tmp", dir=str(p.parent))
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    os.replace(tmp, p)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _print_frontmatter_report(rep: dict, apply: bool) -> None:
    print(f"{'APPLY' if apply else 'DRY RUN'}: {rep['journals']} live journals found")
    print(f"  {'got' if apply else 'would get'} frontmatter: {len(rep['added'] if apply else rep['would_add'])}")
    print(f"  already have frontmatter (skipped): {len(rep['has_frontmatter'])}")
    for p in rep["has_frontmatter"]:
        print(f"    - {p}")
    print(f"  over {MAX_BYTES // (1024 * 1024)} MB (skipped): {len(rep['too_big'])}")
    for p, size in rep["too_big"]:
        print(f"    - {p} ({size / 1048576:.1f} MB)")
    if rep["read_only"]:
        print(f"  read-only mirrors (skipped, add it in the master copy): {len(rep['read_only'])}")
        for p in rep["read_only"]:
            print(f"    - {p}")
    if rep["changed"]:
        print(f"  changed while working (left alone, run again): {len(rep['changed'])}")
        for p in rep["changed"]:
            print(f"    - {p}")
    if rep["errors"]:
        print(f"  errors: {len(rep['errors'])}")
        for p, e in rep["errors"]:
            print(f"    - {p}: {e}")
    if not apply:
        for p in rep["would_add"]:
            print(f"    + {p}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Open your journals in Obsidian.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-frontmatter", help="give live journals an Obsidian Properties block")
    a.add_argument("--root", action="append", help="folder to scan (repeatable); default: the journal roots")
    a.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    v = sub.add_parser("vault", help="write the _obsidian map and .obsidian config at a root")
    v.add_argument("--root", required=True)
    v.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    v.add_argument("--out", help="write the vault files into this folder instead of the root (a preview)")
    args = ap.parse_args(argv)
    if args.cmd == "add-frontmatter":
        roots = [Path(r) for r in args.root] if args.root else list(rules()[4]())
        if not roots:
            print("no roots: pass --root")
            return 2
        _print_frontmatter_report(add_frontmatter(roots, args.apply), args.apply)
        return 0
    rep = build_vault(Path(args.root), args.apply, Path(args.out) if args.out else None)
    print(f"{'WROTE' if rep['written'] else 'DRY RUN, would write'}:")
    for f in rep["files"]:
        print(f"  {f}")
    print(f"  {rep['journals']} journals, {rep['links']} links in START HERE, canvas {rep['canvas_nodes']} nodes"
          f" / {rep['canvas_edges']} edges, {rep['ignore_filters']} ignore filters")
    if rep["too_big"]:
        print(f"  too big for Obsidian (listed, not linked, hidden): {', '.join(rep['too_big'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
