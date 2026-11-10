"""Nearest journal: a touched file that no "## Brain map" row names belongs to the journal of its own project folder.

Why (2026-11-10, Codex live test): a buyer's project held DEMO_JOURNAL.md next to notes.txt and no Brain map; the
AI's first edit of notes.txt got an EMPTY answer, because the first-touch brief only fired for files a Brain map row
names. Buyers mostly have a plain journal in the project folder and no Brain map.

The rule (find()):
- Walk up from the file's folder to the journal root that holds it (the deepest root of JOURNAL_ROOTS, else
  $JOURNAL_HOME/config.toml roots, else ~/Desktop and ~/Documents; a file outside every root uses the session's
  working folder as its root, never the home folder or a drive). Never above that root.
- The first folder with journals at its top decides: 1 to 5 journals there map the file to them (best named first);
  more than 5 is a workspace of many projects and maps nothing.
- The root itself counts only when it holds exactly ONE journal at its top (the root is one project). A root with
  several journals (a folder that holds many projects) is a workspace: its journals map nothing.
- A container of many projects between the journal and the file (servers/, packages/, apps/... with 4 or more
  subfolders) cuts the walk when the project folder inside it is not named in the journal: TOOLS HUB/servers/
  mail-tool/x.py is not HUB_JOURNAL.md's piece.
- Ignored: month archives (X_JOURNAL_2026-07.md), drafts and tool sheets, journals inside _archive, node_modules,
  build output, test fixtures, public web folders and throwaway worktrees (-wt-*).
"""
import os
import re
import unicodedata
from pathlib import Path

MAX_FOLDER_JOURNALS = 5
CONTAINER_MIN = 4
# "<NAME>_JOURNAL.md" or "journal.md" in any case, and our upper-case "<NAME>_JOURNAL_<PART>.md" variants; never a
# fragment ("_peers_journal_entry.md", "X_journal_section.md") or a file named after the journal tool
# ("JOURNAL_MARKETPLACE_CATALOG.md").
JOURNAL_FILE = re.compile(r"^(?!_)(?:(?:.*[_ .-])?journal\.md|.+(?-i:_JOURNAL_[A-Z0-9_]+)\.md)$", re.I)
MONTH_ARCHIVE = re.compile(r"[_-]\d{4}-\d{2}(?:-\d{2})?\.md$", re.I)
SCRATCH = re.compile(r"^(draft|scratch)|[-_]draft\.md$|^\d{4}-\d{2}-\d{2}[-_]|_juice\.md$", re.I)
SKIP_DIRS = {"node_modules", ".next", ".git", "__pycache__", "_archive", "venv", ".venv", "dist", "build", "fixtures",
             "journals-vault", "public"}
SKIP_DIR_RX = re.compile(r"-wt-[\w.-]+$", re.I)
CONTAINERS = set("servers packages apps services plugins mods projects companies tools bots workers extensions repos "
                 "sites".split())
GENERIC = set("servers server mods mod tools tool plugins plugin packages package apps app src lib libs hooks scripts "
              "mcp dna studio journal journals user the and".split())


def _fold(w: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", str(w).lower()) if unicodedata.category(ch) != "Mn")


def _words(name: str) -> set:
    base = re.sub(r"\.md$", "", str(name), flags=re.I)
    return {w for w in re.split(r"[^a-z0-9]+", _fold(base)) if len(w) >= 3} - GENERIC


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def roots() -> list:
    """The journal roots, read the way server.py reads them (no server import: this runs inside the hook)."""
    env = os.environ.get("JOURNAL_ROOTS", "")
    if env:
        return [p.strip() for p in env.split(";") if p.strip()]
    cfg = _home() / "config.toml"
    try:
        text = cfg.read_text(encoding="utf-8")
        try:
            import tomllib
            rs = tomllib.loads(text).get("roots") or []
        except Exception:
            m = re.search(r"^roots\s*=\s*\[(.*?)\]", text, re.S | re.M)
            rs = re.findall(r"[\"']([^\"']+)[\"']", m.group(1)) if m else []
        if rs:
            return [str(r) for r in rs]
    except OSError:
        pass
    return [str(p) for p in (Path.home() / "Desktop", Path.home() / "Documents") if p.is_dir()]


def _norm(p: str, cwd: str = "") -> str:
    p = str(p or "").strip().strip("\"'").replace("\\", "/")
    if not p:
        return ""
    m = re.match(r"^/([A-Za-z])/(.*)$", p)
    if m and os.name == "nt":  # a Git Bash path on Windows
        p = m.group(1) + ":/" + m.group(2)
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        base = _norm(cwd) if cwd else ""
        if not base:
            return ""
        p = os.path.join(base, p)
    return os.path.normpath(p)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(a.rstrip("\\/")) == os.path.normcase(b.rstrip("\\/"))


def _under(p: str, root: str) -> bool:
    a, r = os.path.normcase(p), os.path.normcase(root.rstrip("\\/"))
    return a == r or a.startswith(r + os.sep)


def _journals_at(d: str) -> list:
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return [n for n in names if JOURNAL_FILE.search(n) and not MONTH_ARCHIVE.search(n) and not SCRATCH.search(n)
            and os.path.isfile(os.path.join(d, n))]


def _parts(p: str, base: str) -> list:
    try:
        rel = os.path.relpath(p, base)
    except ValueError:
        return []
    return [] if rel in (".", "") or rel.startswith("..") else re.split(r"[\\/]", rel)


def _subdirs(d: str) -> int:
    try:
        return sum(1 for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return 0


def _owns(d: str, path: str, journals: list) -> bool:
    subs = _parts(os.path.dirname(path), d)
    jw = set().union(*(_words(j) for j in journals)) | _words(os.path.basename(d))
    for i, s in enumerate(subs[:-1]):
        if _fold(s) in CONTAINERS:
            cw = _words(subs[i + 1])
            if cw and not (cw & jw) and _subdirs(os.path.join(d, *subs[:i + 1])) >= CONTAINER_MIN:
                return False
    return True


def _ordered(d: str, journals: list) -> list:
    key = re.sub(r"[^a-z0-9]", "", os.path.basename(d).lower())
    return sorted(journals, key=lambda x: (not x.lower().endswith("_journal.md"),
                                           not re.sub(r"[^a-z0-9]", "", x.lower()).startswith(key), len(x), x))


def _root_for(p: str, cwd: str) -> str:
    rs = [r for r in (_norm(x) for x in roots()) if r and _under(p, r)]
    if rs:
        return max(rs, key=len)
    c = _norm(cwd) if cwd else ""
    if c and _under(p, c) and not _same(c, str(Path.home())) and os.path.dirname(c.rstrip("\\/")) != c.rstrip("\\/") \
            and _norm(c) != os.path.splitdrive(c)[0] + os.sep:
        return c
    return ""


def find(path: str, cwd: str = ""):
    """(project folder, [journal file names, best first]) for a file, or None. The rule is in the module doc."""
    p = _norm(path, cwd)
    if not p:
        return None
    root = _root_for(p, cwd)
    if not root:
        return None
    d = os.path.dirname(p)
    for _ in range(40):
        if not _under(d, root):
            return None
        skipped = any(x.lower() in SKIP_DIRS or SKIP_DIR_RX.search(x) for x in _parts(d, root))
        js = [] if skipped else _journals_at(d)
        if len(js) > MAX_FOLDER_JOURNALS:
            return None
        at_root = _same(d, root)
        if js and (not at_root or len(js) == 1):
            return (d, _ordered(d, js)) if _owns(d, p, js) else None
        if at_root:
            return None
        up = os.path.dirname(d)
        if not up or _same(up, d):
            return None
        d = up
    return None


def touch(seen: dict, path: str, cwd: str, gate) -> tuple:
    """The journals gate for a file mapped by its nearest journal: ("", "") when nothing to say, else the gate's
    (state, message): "deliver" brings the journal brief once per session, exactly like a Brain map piece. The key is
    the one reads use (quick_hook.read_turn: "r:<folder>"), so a brief delivered on a read is not repeated on an edit."""
    hit = find(path, cwd)
    if not hit:
        return "", ""
    d, js = hit
    name = os.path.basename(d.rstrip("\\/")) or d
    state, msg = gate(seen, "r:" + name.lower(), js, [os.path.join(d, j) for j in js], f'project "{name}"')
    return ("", "") if state == "open" else (state, msg)
