"""Default rules pack: exact tests that fire where most AI users need them, with no AI call, no judge and no setup.
The data (formats, commands, messages, version) lives in default_rules.json next to this file.

  stop once      a secret written into a file or a commit, a destructive delete, git reset --hard / checkout -- . /
                 clean over unsaved work, DROP / TRUNCATE / DELETE without WHERE, a force push to main or master,
                 overwriting or deleting .env and key files. Stopped once; the same call again passes.
  needs a yes    publish to production, spending money, messaging customers or posting. Stopped until the user's
                 latest message holds a yes; a plain retry does not pass.

Where it runs: rulecompile.check() adds the stop-once hits to the compiled tests (one stop per call, the same retry
rule), and cmdguard.money_guard() runs the yes-gated ones (it already reads the user's latest message).
Settings: JOURNAL_DEFAULT_RULES=on (default) | off; JOURNAL_DEFAULT_RULES_OFF=secrets,force_push,... per rule.
Yes words: the money guard's own, plus the English ones in default_rules.json, plus JOURNAL_APPROVAL_WORDS.
The user's own answers (starter_rules_interview.md): $JOURNAL_HOME/yes_patterns.txt (more actions that need a yes)
and JOURNAL_MAIN_BRANCHES (branches a force push must not rewrite; default main,master).
Not here: a reminder when a reply claims something is live, paid, sent or working. No reply-side state-claim note
exists to reuse (quickmap._STATE_CLAIM only marks journal map lines), so the pack skips it.

  python default_rules.py "<command>"            what the pack says about one command
  python default_rules.py --write <path> <file>  what it says about writing that file's text to <path>
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
_D: dict = {}


_ASSIGN = re.compile(r"(?i)\b([A-Za-z0-9_]*(?:key|token|secret|password|passwd|pwd)[A-Za-z0-9_]*)(\s*[=:]\s*[\"']?)"
                     r"([^\s\"'&;|]{8,})")
_AUTH = re.compile(r"(?i)(authorization:\s*(?:bearer|basic)\s+|x-api-key:\s*)([^\s\"']{8,})")
_URL_CRED = re.compile(r"(?i)(https?://[^/\s:@]+:)([^@\s/]{4,})(@)")


def redact(text: str) -> str:
    """The text with secrets replaced by <redacted>, for anything written to a log or state file. The command log kept
    commands verbatim, keys included (a VOYAGE_API_KEY=... line sat in it in plain text, found 2026-11-11)."""
    if not text:
        return text
    try:
        for _, rx in data()["_fmt"]:
            text = rx.sub("<redacted>", text)
    except Exception:
        pass
    text = _ASSIGN.sub(lambda m: m.group(1) + m.group(2) + ("<redacted>" if not m.group(3).startswith(("$", "<", "%"))
                                                           else m.group(3)), text)
    text = _AUTH.sub(r"\1<redacted>", text)
    return _URL_CRED.sub(r"\1<redacted>\3", text)


def data() -> dict:
    if not _D:
        _D.update(json.loads((HERE / "default_rules.json").read_text(encoding="utf-8")))
        _D["_say"] = {r["id"]: r for r in _D["rules"]}
        _D["_fmt"] = [(n, re.compile(p)) for n, p in _D["secret_formats"]]
        _D["_kw"] = re.compile(r"(?i)\b([A-Za-z0-9_]*?(?:" + _D["secret_keywords"] + r"))\b[\"']?\s*(?::|=|:=|=>)\s*"
                               r"([\"'])([^\"'\n]{6,200})\2")
        _D["_secret_file"] = re.compile(_D["secret_file_names"], re.I)
        _D["_env_ok"] = re.compile(_D["env_files_ok"], re.I)
        _D["_db"] = re.compile(_D["db_clients"], re.I)
        for k in ("publish", "spend_cli", "message_cli"):
            _D["_" + k] = [(n, re.compile(p, re.I)) for n, p in _D[k]]
        for k in ("spend_http", "message_http"):
            _D["_" + k] = [(n, re.compile(h, re.I), re.compile(b, re.I) if b else None) for n, h, b in _D[k]]
    return _D


def version() -> str:
    return str(data().get("version", ""))


def active() -> set:
    """The rule ids that are on (JOURNAL_DEFAULT_RULES, JOURNAL_DEFAULT_RULES_OFF)."""
    if os.environ.get("JOURNAL_DEFAULT_RULES", "on").strip().lower() in ("off", "0", "false", "no"):
        return set()
    off = {x.strip() for x in os.environ.get("JOURNAL_DEFAULT_RULES_OFF", "").split(",") if x.strip()}
    return {r["id"] for r in data()["rules"]} - off


def _hit(rid: str, what: str, where: str) -> dict:
    r = data()["_say"][rid]
    return {"id": rid, "mode": r["mode"], "where": f"default rule: {rid}",
            "say": r["say"].format(what=what, where=where), "rule": rid}


# ───────────── probes (git and the file system), injectable for tests ─────────────

def _git(args: list, cwd: str) -> tuple:
    """(returncode, stdout); (-1, '') when git could not answer in time. Hidden console on Windows."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd or None, capture_output=True, timeout=3, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, r.stdout.decode("utf-8", "replace")
    except Exception:
        return -1, ""


def probe_dirty(cwd: str) -> bool | None:
    """Tracked changes not committed: True / False; None = not a repo (the command will fail on its own)."""
    rc, out = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    if rc == -1:
        return True
    return None if rc else bool(out.strip())


def probe_clean_loses(cwd: str, flags: str) -> list | None:
    """What `git clean` would delete, minus build output and caches (a dry run with the same flags)."""
    dry = ["clean", "-n"] + [f"-{c}" for c in flags if c in "dxX"]
    rc, out = _git(dry, cwd)
    if rc == -1:
        return ["(git did not answer)"]
    if rc:
        return None
    lost = [ln.split(" ", 2)[-1].strip() for ln in out.splitlines() if ln.strip()]
    return [p for p in lost if not _disposable_path(p)]


def probe_branch(cwd: str) -> str:
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return out.strip() if rc == 0 else ("" if rc > 0 else "?")


def probe_exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return True


PROBES = {"dirty": probe_dirty, "clean": probe_clean_loses, "branch": probe_branch, "exists": probe_exists}
REMOTE = {"dirty": lambda cwd: True, "clean": lambda cwd, fl: ["(on another machine, not checked)"],
          "branch": lambda cwd: "?", "exists": lambda p: True}


# ───────────── shell parsing ─────────────

def segments(cmd: str) -> list:
    """The simple commands of a shell line, split on && || ; | & and newlines outside quotes; a heredoc body stays with
    its command; a line ending in a backslash or a backtick continues."""
    cmd = re.sub(r"[\\`]\r?\n", " ", cmd)
    out, cur, q, i, n = [], "", "", 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if q:
            cur += ch
            if ch == q and (q == "'" or cmd[i - 1] != "\\"):
                q = ""
            i += 1
            continue
        if ch in "\"'":
            q = ch
            cur += ch
            i += 1
            continue
        if ch == "\n":
            m = re.search(r"(?<!<)<<-?\s*['\"]?(\w+)['\"]?", cur)
            if m:
                end = re.compile(r"^\s*" + re.escape(m.group(1)) + r"\s*$", re.M)
                e = end.search(cmd, i + 1)
                stop = e.end() if e else n
                cur += cmd[i:stop]
                i = stop
                continue
        if cmd.startswith("&&", i) or cmd.startswith("||", i):
            out.append(cur)
            cur = ""
            i += 2
            continue
        # a lone & runs the command in the background; 2>&1, &> and PowerShell's leading & (call) stay in place
        background = ch == "&" and cur.strip() and not cur.endswith(">") and cmd[i + 1:i + 2] != ">"
        if ch in ";|\n" or background:
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    out.append(cur)
    return [s.strip() for s in out if s.strip()]


_PREFIX = re.compile(r"^(?:(?:sudo|doas)\s+(?:-\S+\s+)*|env\s+(?:-\S+\s+)*|time\s+|command\s+|exec\s+|nohup\s+|"
                     r"timeout\s+(?:-\S+\s+)*\d+\S*\s+|nice\s+(?:-n\s*-?\d+\s+|-\d+\s+)?|"
                     r"[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\S*)\s+|"
                     r"(?:npx|bunx|pnpx)\s+(?:-y\s+|--yes\s+)?|(?:pnpm|yarn)\s+dlx\s+|&\s*|"
                     r"ssh\s+(?:-\S+\s+(?:\S+\s+)?)*[\w.@-]+\s+[\"']?|\(\s*)+")


_WRAP = re.compile(r"^(?:timeout\s+(?:-\S+\s+)*\d+\S*\s+)?(?:(ssh)\s+(?:-\S+\s+(?:(?![\"'])\S+\s+)?)*[\w.@-]+|"
                   r"(?:ba|z|da)?sh\s+-l?c|(?:powershell|pwsh)(?:\.exe)?\s+(?:-\S+\s+)*-c(?:ommand)?|cmd(?:\.exe)?\s+/[ck])"
                   r"\s+([\"'])(.*)\2(?:\s*\d?(?:<|>>?)&?\s*[^\s;&|]+)*\s*$", re.S | re.I)
# The trailing redirections ("ssh host '...' < /dev/null 2>&1") must not hide the wrapped command: without them in the
# pattern the whole remote script stayed one segment and `rm -rf /tmp/x; git -C /home/a/site ...` read every later
# word as an rm target (two false stops on 2026-11-11/12).


def _expanded(cmd: str, depth: int = 0) -> list:
    """(segment, remote) pairs: a command run through ssh, bash -c, powershell -Command or cmd /c is split too."""
    out = []
    for seg in segments(cmd):
        m = _WRAP.match(seg.strip()) if depth < 2 else None
        if m:
            out += [(s, r or bool(m.group(1))) for s, r in _expanded(m.group(3), depth + 1)]
        else:
            out.append((seg, False))
    return out


def program(seg: str) -> str:
    """The segment from its program on: sudo, env vars, npx, an ssh host and the like are dropped."""
    s = seg.strip()
    for _ in range(6):
        t = _PREFIX.sub("", s, count=1)
        if t == s:
            break
        s = t
    s = s.rstrip()
    for q in "\"'":  # the closing quote of a stripped `ssh host '...` prefix, never one that closes an argument
        if s.endswith(q) and s.count(q) % 2:
            s = s[:-1]
    return s


def tokens(s: str) -> list:
    return [re.sub(r"[\"']", "", t) for t in re.findall(r"\"[^\"]*\"\S*|'[^']*'\S*|\S+", s)]


_READ = re.compile(r"^(?:grep|egrep|fgrep|rg|ag|ack|cat|bat|head|tail|less|more|wc|ls|dir|tree|stat|file|diff|find|"
                   r"select-string|findstr|get-content|gc|get-childitem|gci|type|which|where|whereis|man|jq|yq|"
                   r"git\s+(?:log|show|grep|diff|status|blame|branch|remote|config\s+--get))\b", re.I)


def _cd(seg: str, cwd: str) -> str:
    m = re.match(r"^(?:cd|set-location|sl|pushd)\s+(?:/d\s+)?(\"[^\"]+\"|'[^']+'|\S+)\s*$", seg.strip(), re.I)
    if not m:
        return cwd
    d = os.path.expanduser(m.group(1).strip("\"'"))
    return d if os.path.isabs(d) or re.match(r"^[A-Za-z]:", d) else os.path.join(cwd or os.getcwd(), d)


# ───────────── paths ─────────────

def _norm(p: str) -> str:
    """One spelling for a path: forward slashes, home as ~, no trailing slash."""
    p = p.strip().strip("\"'").replace("\\", "/")
    p = re.sub(r"^(?:\$\{?HOME\}?|\$env:(?:USERPROFILE|HOME)|%USERPROFILE%|%HOMEPATH%)(?=/|$)", "~", p, flags=re.I)
    p = re.sub(r"^(?:[A-Za-z]:|/[a-z])?/(?:Users|home)/[^/]+(?=/|$)", "~", p, flags=re.I)
    p = re.sub(r"^/([a-z])(?=/|$)", lambda m: m.group(1).upper() + ":", p)  # Git Bash /d/x = D:/x
    p = re.sub(r"/+", "/", p)
    p = re.sub(r"/\.(?=/|$)", "", p)
    return p.rstrip("/") if len(p) > 1 else p


def _disposable_path(p: str) -> bool:
    d = data()
    parts = [x for x in _norm(p).split("/") if x not in ("", ".", "~")]
    while parts and re.fullmatch(r"[*?]+|\*\.\w+|\*\*", parts[-1]):
        parts = parts[:-1]
    if not parts:
        return False
    last = parts[-1]
    if last in d["disposable_dirs"] or last.endswith(".egg-info") or last.endswith(".log") or \
            re.fullmatch(r"\.?(?:tmp|temp)[\w.-]*", last, re.I):
        return True
    joined = "/".join(parts)
    return any(c in parts or c in joined for c in d["cache_parts"] if "/" in c) or \
        any(c in parts for c in d["cache_parts"] if "/" not in c)


_WHOLE = {"/": "the whole drive", "/*": "the whole drive", "~": "the whole home folder", "~/*": "the whole home folder",
          ".": "everything in the current folder", "./*": "everything in the current folder",
          "*": "everything in the current folder", "*.*": "everything in the current folder",
          ".*": "every hidden file here, .git included", "..": "the parent folder", "../*": "the parent folder",
          "../..": "the folder two levels up", ".git": "the git history", "~/.git": "the git history"}
_SYSTEM = {"usr", "etc", "bin", "sbin", "lib", "lib32", "lib64", "boot", "var", "opt", "home", "users", "root", "srv",
           "system", "library", "applications", "windows", "program files", "program files (x86)", "programdata",
           "mnt", "media", "snap", "nix", "data"}


def big_target(raw: str) -> str:
    """'' or why deleting this path recursively is destructive: a root, the home folder, a project-level folder."""
    p = _norm(raw)
    if not p:
        return ""
    if p in _WHOLE:
        return _WHOLE[p]
    if re.fullmatch(r"[A-Za-z]:/?\*?", p):
        return "the whole drive"
    if p.endswith("/.git"):
        return "the git history"
    base = re.sub(r"/\*$", "", p)
    if "$" in base or "%" in base:
        return ""
    if re.match(r"^(?:[A-Za-z]:)?/", base):
        parts = re.sub(r"^(?:[A-Za-z]:)?/", "", base).split("/")
        top = parts[0].lower()
        if top in ("tmp", "private", "dev", "proc", "run") or \
                top == "var" and len(parts) > 1 and parts[1].lower() in ("tmp", "folders", "cache", "log"):
            return ""
        if len(parts) <= 2 and (top in _SYSTEM or not _disposable_path(base)):
            return f"the {'system ' if top in _SYSTEM else ''}folder {raw.strip()}"
        return ""
    if _disposable_path(base):
        return ""
    if base.startswith("~/"):
        parts = base[2:].split("/")
        if len(parts) <= 2 or (len(parts) == 3 and parts[0].lower() in data()["project_containers"]):
            return f"the folder {raw.strip()}"
        return ""
    if re.fullmatch(r"\.\./[^/*]+", base):
        return f"the sibling project folder {raw.strip()}"
    return ""


# ───────────── stop-once rules on commands ─────────────

_RM = re.compile(r"^(?:rm|rm\.exe|remove-item|ri|del|erase|rmdir|rd|unlink|trash|trash-put)\b(.*)$", re.I | re.S)


def _rm_hits(prog: str, cwd: str, ok: set, probes: dict) -> list:
    m = _RM.match(prog)
    if not m:
        return []
    verb = prog.split()[0].lower()
    args = tokens(m.group(1))
    cmd_style = verb in ("rmdir", "rd", "del", "erase")
    recursive = any(re.fullmatch(r"-[a-zA-Z]{0,3}[rR][a-zA-Z]{0,3}", a) and not re.fullmatch(r"-force|-fo|-for", a, re.I)
                    or a.lower() in ("--recursive", "-recurse", "-recur") or (cmd_style and a.lower() == "/s")
                    for a in args)
    targets, skip = [], False
    for a in args:
        if skip:
            skip = False
            targets.append(a)
            continue
        if a.lower() in ("-path", "-literalpath"):
            skip = True
            continue
        if a.startswith("-") or (verb in ("rmdir", "rd", "del", "erase") and re.fullmatch(r"/[a-zA-Z]", a)):
            continue
        targets.append(a)
    out = []
    for t in targets:
        if "destructive_rm" in ok and recursive:
            why = big_target(t)
            if why:
                out.append(_hit("destructive_rm", f"`{prog[:80]}`", why))
                continue
        if "secret_files" in ok and _is_secret_file(t) and _exists(t, cwd, probes):
            out.append(_hit("secret_files", f"`{prog[:80]}`", f"deletes {Path(_norm(t)).name}"))
    return out


def _is_secret_file(p: str) -> bool:
    name = _norm(p).rsplit("/", 1)[-1]
    d = data()
    if d["_env_ok"].search(name) or name.endswith(".pub"):
        return False
    if name == "credentials" and "/.aws" not in _norm(p) and not _norm(p).startswith(".aws"):
        return False
    return bool(d["_secret_file"].match(name))


def _exists(p: str, cwd: str, probes: dict) -> bool:
    raw = p.strip("\"'")
    if any(c in raw for c in "*?"):
        return True
    if any(c in raw for c in "$%"):
        return False  # a path built from a variable: unknown, so it passes (precision first)
    full = os.path.expanduser(raw)
    if not (os.path.isabs(full) or re.match(r"^[A-Za-z]:", full)):
        full = os.path.join(cwd or os.getcwd(), full)
    return probes["exists"](full)


_REDIRECT = re.compile(r"(?<![0-9&>])(>>?)\s*(\"[^\"]+\"|'[^']+'|[^\s;&|<>]+)")
_WRITE_CMD = re.compile(r"^(?:cp|copy|copy-item|cpi|mv|move|move-item|mi|install|set-content|sc|out-file|"
                        r"add-content|ac|new-item|ni)\b(.*)$", re.I | re.S)


def _secret_file_writes(prog: str, cwd: str, probes: dict) -> list:
    out = []
    for op, tgt in _REDIRECT.findall(prog):
        if op == ">" and _is_secret_file(tgt) and _exists(tgt, cwd, probes):
            out.append(_hit("secret_files", f"`{prog[:80]}`", f"overwrites {Path(_norm(tgt)).name}"))
    m = _WRITE_CMD.match(prog)
    if m:
        verb = prog.split()[0].lower()
        args = [a for a in tokens(m.group(1)) if not a.startswith("-")]
        named = re.search(r"-(?:destination|path|filepath|literalpath)\s+(\"[^\"]+\"|'[^']+'|\S+)", m.group(1), re.I)
        dest = named.group(1) if named else (args[-1] if args else "")
        if verb in ("add-content", "ac"):
            dest = ""
        if verb in ("new-item", "ni") and not re.search(r"-force\b", prog, re.I):
            dest = ""
        if dest and _is_secret_file(dest) and _exists(dest, cwd, probes):
            out.append(_hit("secret_files", f"`{prog[:80]}`", f"overwrites {Path(_norm(dest)).name}"))
    g = re.match(r"^git\s+rm\b(?!.*--cached)(.*)$", prog, re.S)
    if g:
        for a in tokens(g.group(1)):
            if not a.startswith("-") and _is_secret_file(a) and _exists(a, cwd, probes):
                out.append(_hit("secret_files", f"`{prog[:80]}`", f"deletes {Path(_norm(a)).name}"))
    return out


_GIT = re.compile(r"^git\s+((?:-C\s+(?:\"[^\"]+\"|'[^']+'|\S+)\s+|-c\s+\S+\s+|--no-pager\s+)*)(\S+)(.*)$", re.S)


def _git_hits(prog: str, cwd: str, ok: set, probes: dict) -> list:
    m = _GIT.match(prog)
    if not m:
        return []
    c = re.search(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)", m.group(1))
    where = os.path.join(cwd or os.getcwd(), c.group(1).strip("\"'")) if c else cwd
    sub, rest = m.group(2).lower(), m.group(3)
    out = []
    if "git_discard" in ok:
        if sub == "reset" and re.search(r"(?:^|\s)--hard\b", rest) or \
                sub in ("checkout", "restore") and re.search(r"(?:^|\s)(?:--\s+)?\.(?:\s|$)", rest) and \
                not re.search(r"--staged\b(?!.*--worktree)", rest) or \
                sub == "checkout" and re.search(r"(?:^|\s)(?:-f|--force)\b", rest) and not re.search(r"\s-b\s", rest):
            if probes["dirty"](where):
                out.append(_hit("git_discard", f"`{prog[:60]}`", "the uncommitted changes in this repo"))
        elif sub == "clean" and re.search(r"(?:^|\s)-[a-zA-Z]*f", rest) and not re.search(r"(?:^|\s)-[a-zA-Z]*n|--dry-run", rest):
            fl = "".join(re.findall(r"(?:^|\s)-([a-zA-Z]+)", rest))
            lost = probes["clean"](where, fl)
            if lost:
                show = ", ".join(lost[:3]) + (f" and {len(lost) - 3} more" if len(lost) > 3 else "")
                out.append(_hit("git_discard", f"`{prog[:60]}`", f"files that are in no commit ({show})"))
    if "force_push" in ok and sub == "push":
        args = tokens(rest)
        force = any(a in ("-f", "--force", "--force-if-includes") or a.startswith("--force-with-lease") or
                    re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in args)
        refs = [a for a in args if not a.startswith("-")][1:]
        if any(r.startswith("+") for r in refs):
            force = True
        if force:
            names = main_branches()
            alt = "|".join(re.escape(b) for b in names)
            mains = [r for r in refs if re.fullmatch(r"\+?(?:[\w./-]+:)?(?:refs/heads/)?(?:" + alt + ")", r)]
            if not refs and any(a in ("--all", "--mirror") for a in args):
                mains = ["every branch"]
            elif not refs:
                b = probes["branch"](where)
                if b in names or b == "?":
                    mains = [b if b != "?" else "the current branch"]
            if mains:
                out.append(_hit("force_push", f"`{prog[:60]}`", mains[0].lstrip("+").split(":")[-1]))
    return out


_SQL_DROP = re.compile(r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b(?:\s+IF\s+EXISTS)?\s+([\w.\"`\[\]]+)", re.I)
_SQL_TRUNC = re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?(?!-)([\w.\"`\[\]]+)", re.I)
_SQL_DEL = re.compile(r"\bDELETE\s+FROM\s+([\w.\"`\[\]]+)([^;\"']*)", re.I)


def _sql_hits(prog: str) -> list:
    if re.match(r"^(?:dropdb)\b", prog, re.I):
        return [_hit("sql_destroy", f"`{prog[:60]}`", "a whole database")]
    if not data()["_db"].search(prog):
        return []
    m = _SQL_DROP.search(prog)
    if m:
        return [_hit("sql_destroy", "DROP", m.group(1).strip("\"`[]"))]
    m = _SQL_TRUNC.search(prog)
    if m and not re.match(r"^truncate\b", prog, re.I):
        return [_hit("sql_destroy", "TRUNCATE", f"every row of {m.group(1).strip(chr(34) + '`[]')}")]
    for m in _SQL_DEL.finditer(prog):
        if not re.search(r"\b(?:WHERE|USING|LIMIT)\b", m.group(2), re.I):
            return [_hit("sql_destroy", "DELETE without WHERE", f"every row of {m.group(1).strip(chr(34) + '`[]')}")]
    return []


def _secret_in(text: str, generic: bool) -> str:
    """'' or what kind of secret the text carries as a literal."""
    d = data()
    low_ph = [w for w in d["placeholder_words"]]
    for name, rx in d["_fmt"]:
        for m in rx.finditer(text):
            v = m.group(0)
            if re.search(r"x{4,}|X{4,}|\.\.\.|<|your|example|placeholder|redacted|dummy|fake|(.)\1{7,}", v, re.I):
                continue
            if "PRIVATE KEY" not in v and not re.search(r"\d", v):
                continue
            if name.startswith("an OpenAI") and not (re.search(r"[A-Z]", v) and re.search(r"[a-z]", v[3:])):
                continue
            if name.startswith("a Google") and re.search(r"firebase|authDomain|messagingSenderId|maps\.googleapis",
                                                          text, re.I):
                continue
            return name
    for m in re.finditer(r"eyJ[A-Za-z0-9_-]{8,}\.(eyJ[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{8,}", text):
        try:
            body = m.group(1) + "=" * (-len(m.group(1)) % 4)
            if '"service_role"' in base64.urlsafe_b64decode(body).decode("utf-8", "replace").replace(" ", ""):
                return "a service-role JWT (full database access)"
        except Exception:
            pass
    if generic:
        for m in d["_kw"].finditer(text):
            key, val = m.group(1), m.group(3)
            lv = val.lower()
            if any(rx.search(val) for _, rx in d["_fmt"]):
                continue  # a known key format was already judged above (a public Firebase key, a placeholder)
            if any(w in lv for w in low_ph) or re.search(r"\s", val) or "/" in val or \
                    re.fullmatch(r"[A-Z][A-Z0-9_]*", val) or re.fullmatch(r"[A-Za-z_.-]+", val) or \
                    lv.startswith(("django-insecure", "pk_", "pk-", "pub_", "sha256-", "sha512-")) or \
                    val.startswith(("#", "$", "@", "%", "{")):
                continue
            pw = re.search(r"pass|pwd", key, re.I)
            if not pw and not (len(val) >= 12 and re.search(r"\d", val) and re.search(r"[A-Za-z]", val)):
                continue
            if pw and len(val) < 6:
                continue
            return f"a literal value for {key}"
    return ""


def _env_target(p: str) -> bool:
    """A real env file (where secrets belong), not an example that goes to git."""
    name = _norm(p).rsplit("/", 1)[-1]
    if data()["_env_ok"].search(name):
        return False
    return bool(re.match(r"^(?:\.env(?:\.[\w.-]+)?|[\w.-]+\.env|\.dev\.vars|\.npmrc|\.netrc|\.pypirc)$", name, re.I)) or \
        "/.aws/" in _norm(p) or "/.ssh/" in _norm(p) or "/secrets/" in _norm(p)


def _secret_cmd(cmd: str) -> list:
    """A secret literal that a command writes into a file, a commit message or a public post body."""
    what = _secret_in(cmd, generic=False)
    if not what:
        return []
    for seg in segments(cmd):
        prog = program(seg)
        if re.match(r"^git\s+(?:-C\s+\S+\s+)?commit\b", prog) or \
                re.match(r"^gh\s+(?:pr|issue|release|gist)\s+(?:create|comment|edit)\b", prog):
            if _secret_in(seg, False):
                return [_hit("secrets", what, "a commit message" if "commit" in prog[:20] else "a GitHub post")]
    targets = [t for _, t in _REDIRECT.findall(cmd)] + \
        re.findall(r"\btee\s+(?:-a\s+)?(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", cmd) + \
        re.findall(r"\b(?:set-content|add-content|out-file)\s+(?:-(?:path|filepath|literalpath)\s+)?"
                   r"(\"[^\"]+\"|'[^']+'|[^\s-]\S*)", cmd, re.I)
    targets = [t.strip("\"'") for t in targets if t and t.strip("\"'").lower() not in ("/dev/null", "$null", "nul")]
    files = [t for t in targets if not _env_target(t)]
    if files:
        return [_hit("secrets", what, files[0])]
    return []


def check_command(cmd: str, cwd: str = "", probes: dict | None = None, ok: set | None = None) -> list:
    """Every default-rule hit for one shell command (both modes)."""
    ok = active() if ok is None else ok
    if not ok or not cmd or not _PRE.search(cmd):
        return []
    probes = {**PROBES, **(probes or {})}
    cwd = cwd or os.getcwd()
    out = []
    if "secrets" in ok:
        out += _secret_cmd(cmd)
    local = probes
    for seg, remote in _expanded(cmd):
        prog = program(seg)
        # on another machine nothing can be checked from here: git counts as unsaved, files as present
        probes = {**local, **REMOTE} if remote else local
        if re.match(r"^(?:cd|set-location|sl|pushd)\b", prog, re.I):
            cwd = _cd(prog, cwd)
            continue
        low = prog.lower()
        if _READ.match(prog) and not _REDIRECT.search(prog):
            continue
        if re.match(r"^(?:echo|printf|write-host|write-output)\b", low) and not _REDIRECT.search(prog):
            continue
        out += _rm_hits(prog, cwd, ok, probes)
        if "secret_files" in ok:
            out += _secret_file_writes(prog, cwd, probes)
        if low.startswith("git"):
            out += _git_hits(prog, cwd, ok, probes)
        if "sql_destroy" in ok:
            out += _sql_hits(prog)
        out += _gated(prog, ok)
    seen, uniq = set(), []
    for h in out:
        if (h["id"], h["say"]) not in seen:
            seen.add((h["id"], h["say"]))
            uniq.append(h)
    return uniq


# ───────────── yes-gated rules ─────────────

def _http_write(prog: str) -> bool:
    if re.match(r"^curl(?:\.exe)?\b", prog, re.I):
        if re.search(r"\s(?:-G|--get)\b", prog):
            return False
        return bool(re.search(r"\s(?:-X\s*|--request\s+)[\"']?(?:POST|PUT|PATCH|DELETE)\b|\s(?:-d|--data(?:-\w+)?|-F|--form|"
                              r"--json|-T|--upload-file)(?:\s|=|$)", prog, re.I))
    if re.match(r"^wget\b", prog, re.I):
        return bool(re.search(r"--post-(?:data|file)|--method[= ]\s*(?:POST|PUT|PATCH)", prog, re.I))
    if re.match(r"^(?:https?|xh|xhs)\s+(?:--\S+\s+)*(?:POST|PUT|PATCH|DELETE)\b", prog, re.I):
        return True
    if re.match(r"^(?:invoke-restmethod|invoke-webrequest|irm|iwr)\b", prog, re.I):
        return bool(re.search(r"-method\s+[\"']?(?:post|put|patch|delete)\b|\s-body\s", prog, re.I))
    if re.match(r"^(?:python3?|py|node|deno|bun)\b.*\s-(?:c|e)\s", prog, re.I | re.S):
        return bool(re.search(r"\b(?:requests|httpx|session|client)\.(?:post|put|patch)\s*\(|method\s*[:=]\s*[\"']"
                              r"(?:POST|PUT|PATCH)", prog, re.I))
    return False


def _named(prog: str, name: str) -> str:
    return f"`{prog[:70]}`" if name.lower() in prog.lower() else f"`{prog[:70]}` ({name})"


def _gated(prog: str, ok: set) -> list:
    d = data()
    out = []
    if "publish" in ok:
        for name, rx in d["_publish"]:
            if rx.search(prog) and not re.search(r"\s(?:--help|-h)\b", prog):
                out.append(_hit("publish", _named(prog, name), ""))
                break
    if "spend" in ok:
        for name, rx in d["_spend_cli"]:
            if rx.search(prog) and not re.search(r"\s(?:--help|-h)\b|--dry-run\b", prog):
                out.append(_hit("spend", _named(prog, name), ""))
                break
    if "message" in ok:
        for name, rx in d["_message_cli"]:
            if rx.search(prog):
                out.append(_hit("message", _named(prog, name), ""))
                break
    if ("spend" in ok or "message" in ok) and _http_write(prog):
        for rid, key in (("spend", "_spend_http"), ("message", "_message_http")):
            if rid not in ok:
                continue
            for name, host, body in d[key]:
                if host.search(prog) and (body is None or body.search(prog)):
                    if rid == "spend" and "stripe" in name.lower() and re.search(r"\bsk_test_", prog):
                        continue
                    out.append(_hit(rid, name, ""))
                    break
    return out


def has_yes(msg: str, approval=None) -> bool:
    """The user's latest message holds a yes: the money guard's words (approval), the pack's English ones, and the
    user's own in JOURNAL_APPROVAL_WORDS (comma-separated)."""
    if not msg:
        return False
    if approval is not None and approval.search(msg):
        return True
    words = list(data()["yes_words"]) + [w.strip() for w in os.environ.get("JOURNAL_APPROVAL_WORDS", "").split(",")
                                         if w.strip()]
    return bool(re.search(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", msg, re.I))


def _owner_compiled_hit(cmd: str) -> bool:
    """The owner's own compiled tests already catch this command: they stop it, the pack stays quiet (one stop)."""
    try:
        import rulecompile
        return any(p.search(cmd) and not (u and u.search(cmd)) for p, u, _ in rulecompile.tests("command"))
    except Exception:
        return False


def main_branches() -> list:
    """The branches a force push must never rewrite: JOURNAL_MAIN_BRANCHES (comma-separated), else main and master."""
    return [b.strip() for b in os.environ.get("JOURNAL_MAIN_BRANCHES", "").split(",") if b.strip()] or ["main", "master"]


def user_yes_patterns() -> list:
    """The user's own actions that need a yes, one Python regex per line in $JOURNAL_HOME/yes_patterns.txt (written by
    the start prompt's interview: a custom deploy command, a push to the production branch, a send script)."""
    home = Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))
    out = []
    try:
        for ln in (home / "yes_patterns.txt").read_text(encoding="utf-8").splitlines():
            if ln.strip() and not ln.lstrip().startswith("#"):
                try:
                    out.append(re.compile(ln.strip(), re.I))
                except re.error:
                    pass
    except OSError:
        pass
    return out


def _user_yes_hits(cmd: str) -> list:
    pats = user_yes_patterns() if "user_yes" in active() else []
    for seg, _ in _expanded(cmd) if pats else []:
        prog = program(seg)
        if _READ.match(prog) or re.match(r"^(?:echo|printf|write-host|write-output)\b", prog, re.I):
            continue
        if any(p.search(prog) for p in pats):
            return [_hit("user_yes", f"`{prog[:70]}`", "")]
    return []


def yes_gate(cmd: str, owner_msg: str, approval=None, cwd: str = "") -> str:
    """'' or the stop text for a yes-gated command (publish, spend, message, the user's own yes_patterns.txt) without a
    yes in the latest message."""
    ok = active() & {"publish", "spend", "message"}
    hits = [h for h in check_command(cmd, cwd, ok=ok) if h["mode"] == "needs_yes"] if ok and _YES_PRE.search(cmd) else []
    hits += _user_yes_hits(cmd)
    if not hits or has_yes(owner_msg, approval) or _owner_compiled_hit(cmd):
        return ""
    return "STOPPED (default rule, exact match, no AI): " + " ".join(h["say"] for h in hits[:2])


def yes_prefilter():
    """A cheap regex that matches every command a yes-gated rule could catch (and more): the caller reads the user's
    latest message only when it matches."""
    parts = [_YES_PRE.pattern] if active() & {"publish", "spend", "message"} else []
    parts += [p.pattern for p in (user_yes_patterns() if "user_yes" in active() else [])]
    return re.compile("|".join(f"(?:{p})" for p in parts), re.I) if parts else None


# ───────────── stop-once entry points (rulecompile.check) ─────────────

def check_write(path: str, text: str, probes: dict | None = None, ok: set | None = None) -> list:
    ok = active() if ok is None else ok
    if not ok or not path:
        return []
    probes = {**PROBES, **(probes or {})}
    out = []
    if "secret_files" in ok and _is_secret_file(path) and probes["exists"](path):
        out.append(_hit("secret_files", "this write", f"overwrites {Path(_norm(path)).name}"))
    elif "secrets" in ok and not _env_target(path) and not _is_secret_file(path):
        doc = re.search(r"\.(?:md|mdx|txt|rst|adoc)$", path, re.I)
        testy = re.search(r"(?:^|[/\\])(?:tests?|__tests__|spec|specs|fixtures?|mocks?|__mocks__|testdata)(?:[/\\])|"
                          r"[._-](?:test|spec)\.\w+$|(?:^|[/\\])test_[^/\\]+$|conftest\.py$", path, re.I)
        what = _secret_in(text, generic=not (doc or testy))
        if what:
            out.append(_hit("secrets", what, Path(path).name))
    return out


def stop_once(text: str, on: str, path: str = "") -> list:
    """The stop-once hits for one command or one write (rulecompile.check adds these to the compiled tests)."""
    ok = active() - {"publish", "spend", "message"}
    if not ok:
        return []
    try:
        hits = check_write(path, text, ok=ok) if on == "write" else check_command(text, ok=ok)
    except Exception:
        return []
    return [h for h in hits if h["mode"] == "stop_once"]


_PRE = re.compile(r"\b(?:rm|rmdir|rd|del|erase|unlink|trash|remove-item|ri|git|dropdb|drop|truncate|delete|cp|mv|copy|"
                  r"move|copy-item|move-item|set-content|out-file|new-item|install|tee|vercel|vc|netlify|npm|pnpm|yarn|"
                  r"bun|twine|poetry|uv|flit|hatch|cargo|gem|gh|firebase|fly|flyctl|stripe|gcloud|aws|az|doctl|hcloud|"
                  r"linode-cli|vultr-cli|runpodctl|vastai|sendmail|msmtp|ssmtp|mail|mailx|mutt|swaks|send-mailmessage|"
                  r"curl|wget|https?|xh|invoke-restmethod|invoke-webrequest|irm|iwr|requests|httpx|fetch)\b|>|"
                  r"sk-|[sr]k_live_|gh[pousr]_|github_pat_|AKIA|ASIA|xox|AIza|npm_|PRIVATE KEY|eyJ", re.I)
# Only the phrases a yes-gated rule needs: a match makes the hook read the user's latest message (a slow import), so a
# plain `npm run build` or a GET to graph.facebook.com must not match.
_YES_PRE = re.compile(
    r"\b(?:publish|promote|twine\s+upload|release\s+create|(?:firebase|fly|flyctl)\s+deploy|gem\s+push|"
    r"push\s+(?:-\S+\s+)*heroku|(?:charges|payment_intents|payouts|transfers|subscriptions|invoices|sessions)\s+"
    r"(?:create|pay|confirm|capture)|(?:instances|tpu-vm|tpus|clusters|vm|droplet|server|linodes|instance)\s+create|"
    r"run-instances|request-spot-instances|create\s+(?:pods?|instance)|sendmail|msmtp|ssmtp|mailx?\s+-s|mutt\s+-s|"
    r"swaks|send-mailmessage)\b|\s--prod\b|"
    r"^(?=[\s\S]*(?:api\.stripe\.com|graph\.facebook\.com|googleads\.googleapis|api\.resend|api\.sendgrid|"
    r"api\.postmark|api\.mailgun|api\.brevo|api\.sendinblue|graph\.threads|api\.(?:twitter|x)\.com|api\.linkedin|"
    r"tiktokapis|api\.twilio))(?=[\s\S]*(?:\s-X\s*[\"']?(?:POST|PUT|PATCH|DELETE)|--request\s+(?:POST|PUT|PATCH)|"
    r"\s-d[\s=]|--data|\s-F\s|--form|--json|-method\s+[\"']?(?:post|put|patch)|post-data|\.post\s*\(|\s-T\s|"
    r"method\s*[:=]\s*[\"']POST|\s(?:POST|PUT|PATCH)\s))", re.I)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 3 and sys.argv[1] == "--write":
        hits = check_write(sys.argv[2], Path(sys.argv[3]).read_text(encoding="utf-8", errors="replace"))
    elif len(sys.argv) > 1:
        hits = check_command(sys.argv[1])
    else:
        print(f"default rules {version()}: on = {', '.join(sorted(active())) or 'none'}")
        sys.exit(0)
    for h in hits:
        print(f"{'STOP ONCE' if h['mode'] == 'stop_once' else 'NEEDS A YES'}: {h['say']}")
    if not hits:
        print("nothing caught")
