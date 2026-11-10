"""Tools map: before an action, the tools and working flows that ALREADY do what it is about to do.

Incident 2026-10-26: a session posted an Instagram carousel on a new account by writing a loose Playwright
script (connect_over_cdp, "New post", set_input_files, Share) and running it on a server, while the owner's own
posting tool (an MCP that publishes Instagram posts, carousels and reels through the official API) sat unused.
The journals map never warned: it matched journal WORDS ("drip", "schedule"), none of which the action used, and
"Already exists" cards never stopped anything.

This module matches the action by CONCEPT, not by exact word:
  - tool_concepts.json (next to this file, extended by $JOURNAL_HOME/tool_concepts.json) maps words in any
    language and code signals (connect_over_cdp, set_input_files, smtplib, instagram.com...) to concepts:
    verbs (publish, send, charge...), objects (instagram, carousel, email, payment...) and methods (browser
    automation, raw HTTP calls, cron jobs);
  - the tools side is indexed once into $JOURNAL_HOME/quick_tools.json (rebuilt when a source changes): every
    "Already exists" card of every journal (quick_cards.json, kept by the quick map), and the tool docs: capability
    docs (*_JUICE.md, *CAPABILITIES*.md), an MCP registry (one "### `name`" section per MCP) and installed skills
    (SKILL.md frontmatter). Sources: JOURNAL_TOOL_DOCS (globs separated by ";"), config.toml `tool_docs`, else
    the capability docs among config.toml `extra_docs` plus ~/.claude/MCP_REGISTRY.md and ~/.claude/skills;
  - the action's concepts come from its description, command, file path, the first 4 KB of written content or
    an agent brief, and the local scripts a command runs or feeds; the last few actions of the session add
    context at half weight ("send the post job to the box" right after building an Instagram carousel).

Output: "TOOLS THAT ALREADY DO THIS", at most 3 tools, best first, each with how to call it and where its
journal and doc are. When the action BUILDS or RUNS its own way (writes a script, runs a script or a remote
command, briefs an agent) and the best tool shares a verb of the action and an object, the call is DENIED ONCE
per intent; reading or searching never stops. A tool the action itself names (editing that tool, calling it) is
never shown: it is already in view.

No server import: this runs in the light front door (quick_hook.py), ~0.05 s with a warm index.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import posixpath
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX_VERSION = "4"
NOTE_T, STOP_T = 4.0, 6.0     # tool score to show it / to stop on it (measured on the real journals, 2026-10-26)
HISTORY = 6                   # acting calls of the session whose concepts stay as context
CODE_EXT = re.compile(r"\.(py|js|mjs|cjs|ts|tsx|sh|bash|ps1|bat|cmd|rb|go|rs|php|pl|lua)$", re.I)
RUN_CMD = re.compile(
    r"(?:^|[\s;&|(\"'/\\])(?:python3?(?:\.exe)?|py|node|npx|bun|deno|tsx|ts-node|bash|sh|zsh|pwsh|powershell(?:\.exe)?|"
    r"ruby|perl|php|tmux|nohup|ssh|scp|rsync)[\"']?(?=\s)|\bgo\s+run\b|\bcargo\s+run\b|\bcurl\s[^\n|;&]*-(?:X\s*(?:POST|PUT)|d\s|F\s)",
    re.I)
# A command word, never a piece of a path: "grep Host ~/.ssh/config" is a read (2026-10-27, it got a tools note).
WRITE_CMD = re.compile(r"(?<![\w./~\\-])(ssh|scp|rsync|sed\s+-i|tee|cp|mv|crontab|systemctl|git\s+push)(?![\w./\\-])|(?<![0-9&>])>{1,2}(?!&)\s*(?!/dev/null\b|\$null\b|nul\b)[^\s&|;]")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
JOURNAL_MD = re.compile(r"journal[^\\/]*\.md$", re.I)
DASH = re.compile("[\u2013\u2014]")


def _home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(ch) != "Mn")


def _stem(w: str) -> str:
    """posts, posting, posted -> post; stories -> story; shares, shared, sharing -> shar (both sides alike)."""
    if len(w) <= 4 or w.isdigit():
        return w
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    for suf in ("ing", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


def _stems(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", _fold(text))]


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(text))


def _clean(s: str, n: int) -> str:
    s = DASH.sub(",", re.sub(r"\s+", " ", str(s or ""))).strip(" ,")
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


# ---------------------------------------------------------------- concepts

_CON = {"stamp": None}


def _concept_files() -> list[Path]:
    return [p for p in (HERE / "tool_concepts.json", _home() / "tool_concepts.json") if p.is_file()]


def concepts_table() -> dict:
    """{"kind": {concept: kind}, "single": {stem: [concepts]}, "phrase": [(stems, concept)], "code": [(re, [c])]}"""
    files = _concept_files()
    stamp = tuple((str(p), p.stat().st_mtime) for p in files)
    if _CON["stamp"] == stamp:
        return _CON["t"]
    kinds, words, code, passive, channel, needs, weak, vendors = {}, {}, [], set(), set(), {}, {}, set()
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for name, c in (d.get("concepts") or {}).items():
            kinds[name] = c.get("kind") or kinds.get(name) or "object"
            if c.get("passive"):
                passive.add(name)
            if c.get("channel"):
                channel.add(name)
            if c.get("needs"):
                n = c["needs"]
                needs[name] = ("own" if c.get("needs_own") else "any", None if n == "channel" else set(n))
            if c.get("weak"):
                weak.setdefault(name, []).extend(c["weak"])
            words.setdefault(name, []).extend(c.get("words") or [])
        vendors.update(_alnum(v) for v in d.get("vendors") or [])
        for pat, cs in (d.get("code") or {}).items():
            try:
                code.append((re.compile(pat), list(cs)))
            except re.error:
                pass
    single, phrase = {}, []
    for name, ws in words.items():
        for w in ws:
            st = _stems(w)
            if len(st) == 1:
                single.setdefault(st[0], []).append(name)
            elif st:
                phrase.append((" " + " ".join(st) + " ", name))
    t = {"kind": kinds, "single": single, "phrase": phrase, "code": code, "passive": passive, "channel": channel,
         "needs": needs, "vendors": vendors,
         "weak": {n: re.compile(r"\b(?:" + "|".join(re.escape(_fold(w)) for w in ws) + r")(?:s|d|ed|ing)?\b")
                  for n, ws in weak.items()}}
    _CON.update(stamp=stamp, t=t)
    return t


# A file name or a path is a name, not words: "site_publish.sh" is a site's ship script, not "publish";
# "ig_carousel_incident.json" is a test fixture, not Instagram (2026-10-27: a website ship was stopped 5 times).
_FILE_WORD = re.compile(r"[\w.~$-]*[\\/][^\s\"'`|;&<>()]*|[\w.~$-]*[\w-]\.(?:sh|bash|py|js|mjs|cjs|ts|tsx|jsx|astro|vue|"
                        r"svelte|json|md|txt|log|ps1|bat|bundle|tgz|tar|gz|zip|html|css|yaml|yml|toml|env|service|"
                        r"conf|csv|jpg|jpeg|png|webp|mp4|mp3|wav)\b", re.I)


def words_text(text: str) -> str:
    """The words of a text without its file names and paths, nor code options that only look like words
    (fetch(u, { credentials: "same-origin" }) is a browser fetch mode, not credential handling; 2026-10-27)."""
    return _FILE_WORD.sub(" ", _CODE_OPT.sub(" ", text or ""))


_CODE_OPT = re.compile(r"\bcredentials\s*[:=]\s*[\"'](?:same-origin|include|omit)[\"']", re.I)


def concepts_of(text: str, code_text: str = "") -> dict:
    """{concept: count} found in a text (words and phrases; file names and paths left out) and in code (code
    signals over text + code_text, where names count: instagram.com, studio.youtube.com)."""
    t = concepts_table()
    st = _stems(words_text(text + "\n" + code_text))
    out: dict = {}
    for w in st:
        for c in t["single"].get(w, ()):
            out[c] = out.get(c, 0) + 1
    line = " " + " ".join(st) + " "
    for ph, c in t["phrase"]:
        n = line.count(ph)
        if n:
            out[c] = out.get(c, 0) + n
    raw = text + "\n" + code_text
    for rx, cs in t["code"]:
        n = len(rx.findall(raw))
        if n:
            for c in cs:
                out[c] = out.get(c, 0) + n
    return out


def code_concepts(raw: str) -> set:
    """Concepts from code signals only (connect_over_cdp, requests.post...), never from words a text mentions."""
    return {c for rx, cs in concepts_table()["code"] if rx.search(raw) for c in cs}


# ---------------------------------------------------------------- the tools index

def _config_list(key: str) -> list[str]:
    cfg = _home() / "config.toml"
    if not cfg.is_file():
        return []
    try:
        import tomllib
        return [str(x) for x in (tomllib.loads(cfg.read_text(encoding="utf-8")).get(key) or [])]
    except Exception:
        return []


def _doc_paths() -> list[str]:
    pats = [x.strip() for x in os.environ.get("JOURNAL_TOOL_DOCS", "").split(";") if x.strip()]
    pats += _config_list("tool_docs")
    if not pats:
        pats = [p for p in _config_list("extra_docs") if re.search(r"(juice|capabilit|tools?)[^/\\]*\.md$", p, re.I)]
        cc_dir = Path.home() / ".claude"
        pats += [str(cc_dir / "MCP_REGISTRY.md"), str(cc_dir / "skills" / "*" / "SKILL.md")]
    out, seen = [], set()
    for pat in pats:
        for f in sorted(glob.glob(os.path.expanduser(pat))):
            k = os.path.normcase(os.path.realpath(f))
            if k not in seen and os.path.isfile(f) and f.lower().endswith(".md"):
                seen.add(k)
                out.append(f)
    return out


def _key(name: str) -> str:
    k = _alnum(name)
    for suf in ("juice", "server", "dna", "mcp"):
        if k.endswith(suf) and len(k) - len(suf) >= 3:
            k = k[: -len(suf)]
    return k


_FN = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\([^`]*\))?`")


def _functions(text: str) -> dict:
    """Backticked tool names (`publish_multi(...)`) by the concepts written on the same line."""
    out: dict = {}
    for ln in text.splitlines():
        fns = _FN.findall(ln)
        if not fns:
            continue
        for c in concepts_of(ln):
            lst = out.setdefault(c, [])
            for f in fns:
                if f not in lst:
                    lst.append(f)
    return out


def _parse_doc(path: str) -> list[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    name = Path(path).name
    if name.upper() == "SKILL.MD":
        fm = re.match(r"---\s*\n(.*?)\n---", text, re.S)
        body = fm.group(1) if fm else text[:600]
        nm = re.search(r"^name:\s*(.+)$", body, re.M)
        ds = re.search(r"^description:\s*(.+(?:\n\s+.+)*)", body, re.M)
        sname = (nm.group(1).strip().strip("\"'") if nm else Path(path).parent.name)
        desc = ds.group(1).strip().strip("\"'") if ds else ""
        return [{"kind": "skill", "name": sname, "key": "skill:" + _key(sname), "one": desc, "ids": [sname],
                 "src": f"skill {sname}", "text": f"{sname} {desc}"}]
    secs = list(re.finditer(r"^###\s+`([^`]+)`\s*(.*)$", text, re.M))
    if len(secs) >= 3:   # a registry: one entry per MCP section, plus "| `name` | what |" table rows
        out = []
        for i, m in enumerate(secs):
            end = secs[i + 1].start() if i + 1 < len(secs) else len(text)
            body = re.sub(r"```.*?```", " ", text[m.end():end], flags=re.S)
            one = re.sub(r"^[\s\u2013\u2014:-]+", "", m.group(2))
            # The name a config uses ("social-engine": {...}) is how it is called; the heading may carry a suffix.
            cfg = re.search(r'"([\w.-]+)"\s*:\s*\{', text[m.end():end])
            out.append({"kind": "mcp", "name": cfg.group(1) if cfg else m.group(1), "key": _key(m.group(1)), "one": one,
                        "ids": [m.group(1)] + ([cfg.group(1)] if cfg else []),
                        "src": name, "text": f"{m.group(1)} {one} {body[:1500]}"})
        for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|\s*([^|\n]+)\|", text, re.M):
            out.append({"kind": "mcp", "name": m.group(1), "key": _key(m.group(1)), "one": m.group(2).strip(),
                        "src": name, "text": f"{m.group(1)} {m.group(2)}"})
        return out
    h1 = re.search(r"^#\s+(.+)$", text, re.M)
    title = re.sub(r",?\s*(?:the\s+juice|juice)\s*$", "", (h1.group(1) if h1 else Path(path).stem), flags=re.I)
    title = re.split(r"\s[-\u2013\u2014:|]\s|\ufffd|,", re.sub(r"\bMCP\b", "", title))[0].strip(" ,*")
    if title.isupper() or title.islower():
        title = title.replace("-", " ").title()
    # Its one line: a "one-liner" / "what it does" section, else the first plain paragraph that is not about the
    # doc itself ("Source-grounded. Read off server.py ...").
    one = re.search(r"^#+[^\n]*(?:one[- ]liner|in one line|what it (?:is|does)|pitch)[^\n]*\n+(.+?)(?:\n\s*\n|\n---)",
                    text, re.I | re.S | re.M)
    if not one:
        one = next((m for m in re.finditer(r"^(?![#*>|\s-])(.{40,}?)(?:\n\s*\n)", text, re.M | re.S)
                    if not re.match(r"(?i)(source|written|distilled|generated|read off|last updated|verified)",
                                    m.group(1))), None)
    stem = re.sub(r"_?juice$|_?capabilities$", "", Path(path).stem, flags=re.I)
    return [{"kind": "doc", "name": title, "key": _key(stem), "ids": [title, Path(path).stem.replace("_JUICE", "")], "one": re.sub(r"[*_`]{1,2}", "", one.group(1)).strip() if one else "",
             "src": name, "text": text, "fn": _functions(text)}]


def _cards() -> list[dict]:
    try:
        cache = json.loads((_home() / "quick_cards.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for path, ent in cache.items():
        for c in ent.get("c", []):
            if c.get("k") == "exists" and c.get("what"):
                out.append({"kind": "card", "name": c["what"], "one": c["what"], "how": c.get("how") or "",
                            "status": c.get("status") or "", "src": ent.get("n") or Path(path).name,
                            "text": f'{c["what"]} {c.get("how") or ""} {c.get("keys") or ""}'})
    return out


def _stamp(docs: list[str]) -> str:
    parts = [INDEX_VERSION]
    for p in docs + [str(x) for x in _concept_files()] + [str(_home() / "quick_cards.json")]:
        try:
            parts.append(f"{p}|{os.stat(p).st_mtime}")
        except OSError:
            parts.append(p)
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


_IDX = {"stamp": None}


def tool_index() -> dict:
    """{"entries": [...], "idf": {concept: w}, "names": {key: display name}} cached in quick_tools.json."""
    docs = _doc_paths()
    stamp = _stamp(docs)
    if _IDX["stamp"] == stamp:
        return _IDX["v"]
    f = _home() / "quick_tools.json"
    try:
        v = json.loads(f.read_text(encoding="utf-8"))
        if v.get("stamp") == stamp:
            _IDX.update(stamp=stamp, v=v)
            return v
    except Exception:
        pass
    entries = []
    for p in docs:
        entries += _parse_doc(p)
    names = {}
    for e in entries:
        if e["kind"] in ("doc", "mcp") and len(e["key"]) >= 4:
            if e["kind"] == "doc" or e["key"] not in names:
                names[e["key"]] = e["name"]
    keys = sorted(names, key=len, reverse=True)
    for c in _cards():
        head = _alnum(c["how"][:80]) + " " + _alnum(c["name"][:60])
        c["key"] = next((k for k in keys if k in head), "card:" + _alnum(c["name"])[:40])
        entries.append(c)
    # How an action names a tool as a tool: its own names ("social-engine", "Social Engine", "youtube-dna"; never a
    # bare platform word like "youtube" or "gumroad", which is what the action is about) and its function names.
    single = concepts_table()["single"]
    # A tool named after the platform it works on ("gumroad", "youtube") ranks first when the action names it.
    ids, fns, plain = {}, {}, {}
    for e in entries:
        for i in (e.pop("ids", []) or []) + ([e["key"]] if e["kind"] in ("doc", "mcp") else []):
            a = _alnum(i)
            if _stem(a) in single:
                if _stem(a) not in plain.setdefault(e["key"], []):
                    plain[e["key"]].append(_stem(a))
            elif len(a) >= 5 and a not in ids.setdefault(e["key"], []):
                ids[e["key"]].append(a)
        found = [f for lst in (e.get("fn") or {}).values() for f in lst]
        found += re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(", e.get("how") or "")
        fl = fns.setdefault(e["key"], [])
        fl += [f for f in found if len(f) >= 8 and f not in fl]
    df: dict = {}
    for e in entries:
        e["cc"] = concepts_of(e.pop("text"))
        for c in e["cc"]:
            df[c] = df.get(c, 0) + 1
    n = max(1, len(entries))
    idf = {c: 1.0 + math.log(n / d) for c, d in df.items()}
    v = {"stamp": stamp, "entries": entries, "idf": idf, "names": names, "ids": ids, "fns": fns, "plain": plain}
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass
    _IDX.update(stamp=stamp, v=v)
    return v


# ---------------------------------------------------------------- matching

_KW = {"verb": 1.0, "object": 1.0, "method": 0.5}


def names_tool(idx: dict, key: str, text: str) -> bool:
    """The action names this tool as a tool (one of its names, or one of its function names): it is in view."""
    if key.startswith("card:"):
        return False
    a, f = _alnum(text), _fold(text)
    return any(i in a for i in idx.get("ids", {}).get(key, [])) or any(x in f for x in idx.get("fns", {}).get(key, []))


def rank(now: dict, ctx: dict = None, named: str = "") -> list[dict]:
    """Tool groups ranked for an action: now = {concept: count} of the action, ctx = concepts of the session's
    last actions (half weight). named: the action's own text; a tool it names as a tool is skipped."""
    idx = tool_index()
    kinds = concepts_table()["kind"]
    want = {c: 1.0 for c in now}
    for c in ctx or {}:
        want.setdefault(c, 0.5)
    groups: dict = {}
    for e in idx["entries"]:
        shared = [c for c in e["cc"] if c in want]
        if not shared:
            continue
        div = 3.0 if e["kind"] == "doc" else 1.0
        sc = sum(want[c] * min(1.0, e["cc"][c] / div) * idx["idf"].get(c, 1.0) * _KW.get(kinds.get(c), 1.0)
                 for c in shared)
        sc += 0.002 * min(50, sum(e["cc"][c] for c in shared))   # ties: the card that talks most about it first
        g = groups.setdefault(e["key"], {"key": e["key"], "entries": [], "shared": set()})
        g["entries"].append((sc, e))
        g["shared"] |= set(shared)
    out = []
    said = set(_stems(named)) if named else set()
    for k, g in groups.items():
        g["entries"].sort(key=lambda x: -x[0])
        scores = [s for s, _ in g["entries"]]
        g["score"] = scores[0] + 0.15 * sum(scores[1:3])
        if said & set(idx.get("plain", {}).get(k, [])):
            g["score"] *= 1.5
        nm = idx["names"].get(k) or g["entries"][0][1]["name"]
        g["name"] = nm
        # A tool named after a hosting or database service (supabase-deploy) fits only an action on that service.
        vend = {v for v in concepts_table()["vendors"] if v in _alnum(k + " " + nm)}
        if vend and not any(v in _alnum(named) for v in vend):
            continue
        if named and names_tool(idx, k, named):
            continue   # the action names this tool: it is already in view
        out.append(g)
    out.sort(key=lambda g: -g["score"])
    return out


def _kinds_of(cs, kind: str) -> set:
    kinds = concepts_table()["kind"]
    return {c for c in cs if kinds.get(c) == kind}


def _qualifies(g: dict, now: dict) -> bool:
    """Shown when it shares 2+ concepts with THIS action, or one of this action plus a verb and an object counting
    the session's last actions. Context alone never shows a tool (an unrelated edit right after Instagram work)."""
    sh = g["shared"]
    if g["score"] < NOTE_T:
        return False
    sh_now = [c for c in sh if c in now]
    return len(sh_now) >= 2 or (len(sh_now) == 1 and bool(_kinds_of(sh, "verb") & set(now))
                                and bool(_kinds_of(sh, "object")))


def _strong(g: dict, now: dict) -> bool:
    """A stop: a verb of THIS action, an object, and 3 shared concepts (one from the session's last actions counts
    half), score over STOP_T. Two concepts ("send" + "email") only show the tools: too thin to stop on."""
    sh = g["shared"]
    weight = sum(1.0 if c in now else 0.5 for c in sh)
    passive = concepts_table()["passive"]
    return (g["score"] >= STOP_T and weight >= 2.5 and bool((_kinds_of(sh, "verb") & set(now)) - passive)
            and bool(_kinds_of(sh, "object")))


def _how(g: dict, now: dict) -> str:
    cards = [e for _, e in g["entries"] if e["kind"] == "card"]
    if cards:
        c = cards[0]
        return _clean(c.get("how") or "", 230) + (f'\n   Status: {_clean(c["status"], 150)}' if c.get("status") else "")
    fns: list = []
    for _, e in g["entries"]:
        for c in sorted(now, key=lambda c: -now[c]):
            for f in (e.get("fn") or {}).get(c, []):
                if f not in fns:
                    fns.append(f)
    return ", ".join(fns[:4])


TOOL_TASK = ("You decide which existing tools already do the job an AI session is about to do (it may be about to write "
             "its own script for it). List every tool that does THIS job, the most specific first: a tool or card made "
             "for exactly this job and target (e.g. reading the DMs sent to a named account) comes before any generic "
             "tool; a generic tool (a plain browser driver, a shell, a CLI for any website) counts ONLY when no "
             "specific one does the job. Sharing a word, a platform or a topic is not enough. When the action says too "
             "little to tell what job it does, none fit. An action that configures, edits, tests or fixes a tool itself "
             "(its settings, its code, its env) is not a job that tool does: none fit then. An action that already USES "
             "a tool (calls its CLI or service, runs its own scripts or code from its source folder, or a script that "
             "runs them) is that tool at work, not a rival to it: that tool does not fit then, nor do the tools it is "
             "built on or runs inside it (an action using the studio is also its render engines at work). A tool fits "
             "only when it takes the action's real input and gives the output the action needs: frames of a public "
             "video URL are not frames of a private studio project or a local take. A card fits only when it "
             "does the same job, not when it shares a word like owner, brief or account. None may fit.")


_NEAR = {"dms": {"dm", "inbox", "thread"}, "dm": {"inbox", "thread"}, "messages": {"inbox", "dm", "thread"},
         "message": {"inbox", "dm", "thread"}, "mensajes": {"inbox", "dm", "thread"}, "inbox": {"dm", "thread"}}


def _desc(g: dict, q: set = frozenset()) -> str:
    ents = [e for _, e in g["entries"]]
    doc = next((e for e in ents if e["kind"] == "doc"), None)
    mcp_e = next((e for e in ents if e["kind"] == "mcp"), None)
    one = next((e.get("one") for e in (doc, mcp_e, ents[0]) if e and e.get("one")), "")
    hows = "; ".join(sorted({str(e.get("how") or "") for e in ents if e.get("how")}))[:200]
    want = set(q) | {w for x in q for w in _NEAR.get(x, ())}
    # The functions that share a word with the action first: a long tool cut at 900 characters hid unified_inbox.
    fns = sorted({f for e in ents for v in (e.get("fn") or {}).values() for f in v},
                 key=lambda f: (not (_words(f) & want), f))
    # where the tool lives (its journal, doc and source paths): lets the judge see that an action running a script
    # from that folder already USES the tool (2026-11-05: capture.py of MEDIA HUB/services/capture, the Creator
    # Studio recorder, was stopped ~25 times with "use Video Studio Record a site")
    src = "; ".join(dict.fromkeys(str(e.get("src") or "") for e in ents if e.get("src")))[:240]
    return (f"{_clean(g['name'], 90)}: {_clean(one, 200)}" + (f" | how: {hows}" if hows else "")
            + (f" | lives in: {src}" if src else "")
            + (f" | functions: {', '.join(fns[:40])}" if fns else ""))


def _judge_tools(intent: str, text: str, cand: list[dict]) -> list[dict] | None:
    """The candidates the judge says do this job, in rank order; None when there is no judge."""
    try:
        sys.path.insert(0, str(HERE))
        import judge
        # 3600: at 1200 a long command alone filled the window and the scripts it runs never reached the judge
        q = _words(f"{intent} {text[:3600]}")
        pick = judge.judge(f"{intent}\n{text[:3600]}", [_desc(g, q) for g in cand], task=TOOL_TASK, tmax=900, model=judge.STRONG, ordered=True)
    except Exception:
        return None
    return None if pick is None else [cand[i] for i in pick]


def block(groups: list[dict], now: dict, intent: str = "") -> str:
    lines = []
    allents = tool_index()["entries"]
    for i, g in enumerate(groups[:3], 1):
        ents = [e for _, e in g["entries"]]
        mcp = next((e["name"] for e in allents if e["kind"] == "mcp" and e.get("key") == g["key"]), "")
        skill = next((e["name"] for e in ents if e["kind"] == "skill"), "")
        label = g["name"] if not g["key"].startswith("card:") else _clean(g["name"], 90)
        label += f" (MCP {mcp})" if mcp else (f" (skill {skill})" if skill and skill != g["name"] else "")
        doc = next((e for e in ents if e["kind"] == "doc"), None)
        mcp_e = next((e for e in ents if e["kind"] == "mcp"), None)
        one = next((e.get("one") for e in (doc, mcp_e, ents[0]) if e and e.get("one")), "")
        lines.append(f"{i}. {label}: {_clean(one, 170)}")
        how = _how(g, now)
        if how:
            lines.append(f"   Use: {how}")
        see = list(dict.fromkeys(e["src"] for e in ents if e["kind"] in ("card", "doc")))[:3]
        if see:
            lines.append(f"   Journal and docs: {', '.join(see)}")
    shared = sorted(set().union(*(g["shared"] for g in groups[:3])) & set(now)) if groups else []
    head = "TOOLS THAT ALREADY DO THIS" + (f' ("{_clean(intent, 80)}"; matched: {", ".join(shared[:6])})' if shared else "")
    return (head + ":\n" + "\n".join(lines) + "\nUse it. If it does not fit, say in one line why and improve that tool "
            "(and log it in its journal); a loose script that redoes what a tool does is a duplicate.")


# ---------------------------------------------------------------- the hook side

def _local_files(cmd: str, cwd: str) -> str:
    """The local scripts and text files a command runs, feeds or edits ($VAR set in the command expanded)."""
    vars_ = dict(re.findall(r"\b([A-Za-z_]\w*)=\"([^\"\n]+)\"", cmd)) | dict(re.findall(r"\b([A-Za-z_]\w*)='([^'\n]+)'", cmd))
    exp = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda m: vars_.get(m.group(1), m.group(0)), cmd)
    cd = re.search(r"\bcd\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))", exp)
    base = next((x for x in cd.groups() if x), "") if cd else (cwd or "")
    out, seen = [], set()
    for m in re.finditer(r"\"([^\"\n]+\.\w{1,4})\"|'([^'\n]+\.\w{1,4})'|([\w./\\:~-]+\.\w{1,4})\b", exp):
        p = next(x for x in m.groups() if x)
        if not re.search(r"\.(py|js|mjs|ts|sh|ps1|txt|json|md)$", p, re.I):
            continue
        p = re.sub(r"^/([a-z])/", r"\1:/", p)
        cands = [p] if re.match(r"^([A-Za-z]:)?[/\\]|^~", p) else [os.path.join(base, p)] if base else []
        if base and p.startswith("/") and not os.path.isfile(p):
            # a script that runs on a server (ssh host 'bash /tmp/x/build_demo.sh'): its source usually sits next to
            # where the command works from; without it the judge saw no script and offered box_job to a build that
            # already runs through box_job (2026-11-05)
            cands.append(os.path.join(base, os.path.basename(p)))
        for c in cands:
            c = os.path.expanduser(c)
            k = os.path.normcase(os.path.abspath(c))
            if k in seen or not os.path.isfile(c):
                continue
            seen.add(k)
            try:
                if os.path.getsize(c) < 400_000:
                    with open(c, encoding="utf-8", errors="replace") as fh:
                        out.append(f"# file: {os.path.basename(c)}\n" + fh.read(4000))
            except OSError:
                pass
        if len(out) >= 3:
            break
    return _FILE_SEP.join(out)


_FILE_SEP = "\n# --- next file ---\n"   # shell comments: readonly_probe skips them


def _heads(files: str, n: int = 1800) -> str:
    """An equal share of n characters for EACH local file: the first script cut at n hid the others (2026-11-05: a
    command that edits an old pc script and then runs run_take.sh, the Video Studio capture runner, showed the
    judge only the old script's header and was stopped as a rival of the Video Studio)."""
    parts = [x for x in files.split(_FILE_SEP) if x.strip()]
    return _FILE_SEP.join(x[:n // len(parts)] for x in parts) if parts else ""


_TOOL_MARKS = ("INSTALL.md", "mcpize.yaml", "SKILL.md", ".claude-plugin", "tool_concepts.json")


_RO_WORDS = {"cat", "ls", "ll", "echo", "printf", "head", "tail", "grep", "egrep", "rg", "find", "wc", "sort", "uniq",
             "awk", "cut", "tr", "diff", "md5sum", "sha256sum", "stat", "file", "date", "uptime", "df", "du", "free",
             "ps", "pgrep", "ss", "netstat", "lsof", "id", "whoami", "hostname", "uname", "which", "type", "env",
             "printenv", "journalctl", "readlink", "realpath", "basename", "dirname", "test", "[", "true", "jq",
             "column", "nl", "less", "more", "tree", "sed", "set", "cd", "pwd", "nvidia-smi", "dig", "ping"}
_RO_SUBCMD = {"systemctl": {"cat", "status", "show", "list-units", "list-unit-files", "is-active", "is-enabled",
                            "list-timers"},
              "git": {"log", "status", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame"},
              "docker": {"ps", "logs", "inspect", "images"}, "tmux": {"ls", "list-sessions", "capture-pane"},
              "crontab": {"-l"}, "curl": None}


def readonly_probe(cmd: str, files: str) -> bool:
    """A command that only writes a local probe script (cat > x.sh <<'EOF' ... EOF) and feeds it to a server
    (ssh host bash -s < x.sh), or runs ssh 'cat ...', where every command that reaches the server only reads."""
    hd = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?[^\n]*\n(.*?)\n\1\b", re.S)
    bodies = "\n".join(m.group(2) for m in hd.finditer(cmd))
    outer = hd.sub("", cmd)
    outer = re.sub(r"\bcat\s*>\s*\S+", "", outer)
    inline = re.search(r"\bssh\s+(?:-\S+\s+)*\S+\s+[\"'](.+?)[\"']\s*$", outer.strip(), re.S)
    fed = re.search(r"\bssh\b[^\n|;&]*\bbash\s+-s\s*<\s*\S", outer)
    if not (fed or inline):
        return False
    remote = (bodies + "\n" + files) if fed else inline.group(1)
    rest = re.sub(r"\bssh\b[^\n;&|]*", "", outer)
    rest_ok = not re.search(r"[A-Za-z]", re.sub(r"\b\w+=(\"[^\"]*\"|'[^']*'|\S*)", "", rest)) or readonly_script(rest)
    return bool(remote.strip()) and readonly_script(remote) and rest_ok


def readonly_script(text: str) -> bool:
    """True when every command in a shell text only reads (cat, ls, grep, systemctl cat/status, ss, journalctl,
    sed without -i, curl without a body...): a probe sent to a server is not an action (2026-10-26: "Read VD
    Chrome env and proxy unit on box", an ssh bash -s of cat/sed/systemctl cat/ss/ls, was stopped)."""
    body = re.sub(r"<<-?\s*[\"']?(\w+)[\"']?.*?\n\1\b", "", text, flags=re.S)
    body = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "Q", body)   # quoted args (regexes, sed scripts) never split commands
    if re.search(r"(?<![0-9&>])>{1,2}(?!&)\s*(?!/dev/null\b|\$null\b|nul\b)[^\s&|;]|\bsed\s+(-\w*\s+)*-i|\btee\b", body):
        return False
    seen = False
    for part in re.split(r"[;\n|]|&&|\|\||\$\(|`", body):
        words = [w for w in part.strip().split() if not re.match(r"^\w+=", w)]
        while words and words[0] in ("sudo", "-u", "nice", "timeout", "time", "do", "then", "else", "{", "}", "(", ")"):
            words = words[2:] if words[0] == "-u" else words[1:]
            if words and re.match(r"^\d+[smh]?$", words[0]):
                words = words[1:]
        if not words or words[0].startswith("#") or words[0] in ("for", "if", "fi", "done", "while", "esac", "in"):
            continue
        cmd = posixpath.basename(words[0])
        if cmd in _RO_SUBCMD:
            allowed = _RO_SUBCMD[cmd]
            if allowed is None:
                if re.search(r"\s-(X\s*(POST|PUT|PATCH|DELETE)|d\s|F\s)|--data", part):
                    return False
            elif not (len(words) > 1 and words[1] in allowed):
                return False
        elif cmd not in _RO_WORDS:
            return False
        seen = True
    return seen


_IDENTITY = re.compile(
    r"-c\s+user\.(?:name|email)=(?:\"[^\"]*\"|'[^']*'|\S+)|--author[=\s](?:\"[^\"]*\"|'[^']*'|\S+)"
    r"|\bgit\s+config\s+(?:--\S+\s+)*user\.(?:name|email)\s+(?:\"[^\"]*\"|'[^']*'|\S+)"
    r"|\bGIT_(?:AUTHOR|COMMITTER)_(?:NAME|EMAIL)=(?:\"[^\"]*\"|'[^']*'|\S+)"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def strip_identity(text: str) -> str:
    """Who a commit is signed as (git -c user.email=..., --author, git config user.name) and any email address are
    not an action on email (2026-10-27: `git -c user.email=admin@site commit` matched "email")."""
    return _IDENTITY.sub(" ", text or "")


GIT_COMMIT = re.compile(r"\bgit\s+(?:-[cC]\s+\S+\s+)*commit\b|\bgh\s+(?:pr|issue|release)\s+create\b")

# Shipping a website: its own ship or deploy script (/opt/<x>-ship/, *publish*.sh, *ship*.sh, *deploy*.py), a
# package script (npm run ship) or a hosting CLI. Social and marketplace tools never fit that (2026-10-27:
# mapleworks.dev shipped through /opt/appuser-ship/site_publish.sh was stopped with Social Engine, Webweave, Gumroad).
SITE_SHIP = re.compile(
    r"/opt/[\w.-]*-ship/|(?<![\w.-])[\w.-]*(?:publish|ship|deploy|release)[\w.-]*\.(?:sh|bash|py|mjs|js|ts|ps1)\b"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:ship|deploy|publish|release)\b|\bvercel\s+(?:deploy\b|--prod\b)"
    r"|\bwrangler\s+(?:pages\s+)?deploy\b|\bnetlify\s+deploy\b|\bfirebase\s+deploy\b|\bgh-pages\b|\bastro\s+build\b",
    re.I)


# Putting a web page's own file (.js, .css, .html) in place on a server is a site deploy too (2026-10-27: replacing
# /data/localmodel/panel/media-library.js over ssh was stopped with Social Engine and supabase-deploy).
_WEB_ASSET_PUT = re.compile(r"(?:\b(?:mv|cp|install)\s+(?:-\S+\s+)*\S+\s+|>\s*|\bscp\s+(?:-\S+\s+)*)"
                            r"[\"']?[\w./~$-]+\.(?:js|mjs|css|html?)\b")
_REMOTE = re.compile(r"(?<![\w./~\\-])(?:ssh|scp|rsync)(?![\w./\\-])")


def site_ship(*texts: str) -> bool:
    if any(SITE_SHIP.search(t or "") for t in texts):
        return True
    allt = "\n".join(t or "" for t in texts)
    return bool(_REMOTE.search(allt) and _WEB_ASSET_PUT.search(allt))


def channel_objects(cs) -> set:
    return set(cs) & concepts_table()["channel"]


_TARGET_FILE = re.compile(r"[\w.~$-]*[\w-]\.[A-Za-z][\w]{0,7}\b")


def target_of(call: dict) -> str:
    """What an action works ON: the file it writes, or the scripts, files and hosts a command names. The once-stop
    keys on it, so rewording the description of the same command does not stop it again (2026-10-27: "Commit
    change and prepare one-shot publish script" then "Commit the website edit locally and write the box script",
    the same command, were stopped twice)."""
    tool = str(call.get("tool_name") or "")
    ti = call.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        return "file:" + os.path.normcase(str(ti.get("file_path") or ti.get("notebook_path") or "").replace("\\", "/"))
    if tool in ("Bash", "PowerShell", "Agent", "Task"):
        # an agent brief: the files and hosts it names (a relaunch with a reworded brief is the same job)
        cmd = strip_identity(strip_payloads(str(ti.get("command") or ti.get("prompt") or "")))
        cmd = re.sub(r"(?s)\bgit\s+(?:-[cC]\s+\S+\s+)*commit\b.*?(?=&&|;|\n|$)", " git commit ", cmd)
        names = {posixpath.basename(m.group(0).replace("\\", "/")) for m in _TARGET_FILE.finditer(cmd)}
        hosts = {m.group(1) for m in re.finditer(r"(?<![\w.-])(?:ssh|scp|rsync)\s+(?:-\S+\s+(?:\d+\s+)?)*([\w.@-]+)", cmd)}
        parts = sorted(n.lower() for n in names | hosts if n)
        return tool[:5].lower() + ":" + (" ".join(parts) if parts else re.sub(r"\s+", " ", cmd.strip())[:300])
    return ""


def strip_payloads(cmd: str) -> str:
    """Encoded data carried inside a command is not the action: long base64 runs are dropped. Code in a heredoc
    stays (it is what runs: the 2026-10-26 Instagram post script travelled that way)."""
    return re.sub(r"(?:[A-Za-z0-9+/=]{60,}\s*){3,}", " ", cmd)


def _existing_dir(p: str) -> str:
    """The longest folder a path names that exists. A path written in prose runs on into the sentence ("C:/x/
    journal-mcp (git repo): toolmap.py, ..."): its real folder is still found (2026-10-27: an agent brief to fix
    the journal tool was stopped because its path was not recognized)."""
    p = p.rstrip("/\\ ")
    if os.path.isdir(p):
        return p
    parts = re.split(r"[\\/]", p)
    best = ""
    for i in range(1, len(parts) + 1):
        d = "/".join(parts[:i])
        if not d:
            continue
        if re.fullmatch(r"[A-Za-z]:", d):
            d += "/"
        if os.path.isdir(d):
            best = d
        elif i > 1 and best:
            # prose after the path: "journal-mcp (git repo)" -> try the leading word of this part
            head = re.split(r"\s+[(\[:,]|[,:;]\s|\s+\(", parts[i - 1])[0]
            cand = "/".join(parts[: i - 1] + [head])
            if head and os.path.isdir(cand):
                best = cand
            break
    return best if best and best.rstrip("/") not in ("", ".") and len(re.split(r"[\\/]", best.rstrip("/"))) > 2 else ""


def _in_tool_source(text: str, cwd: str = "") -> bool:
    """The action works inside a tool's own source (a folder with server.py and an install doc, a skill, a mod):
    improving a tool is the right move, so it is never stopped (2026-10-26: editing the concept table stopped)."""
    cands = re.findall(r"[A-Za-z]:[\\/][^\"'\n|;&<>]+|(?<![\w.])/(?:[a-z]/|home/|Users/|opt/)[^\"'\s|;&<>]+", text)
    # quoted paths keep their spaces ("/c/Users/x/Desktop/DEV PROJECTS/TOOL SHOP/servers/journal-mcp")
    cands = re.findall(r"[\"']((?:[A-Za-z]:)?[/\\][^\"'\n]+)[\"']", text) + cands
    cd = re.search(r"\bcd\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))", text)
    if cd:
        cands.append(next(x for x in cd.groups() if x))
    for p in cands[:16]:
        d = _existing_dir(re.sub(r"^/([a-z])/", r"\1:/", p.strip()))
        if not d:
            continue
        for _ in range(4):
            try:
                names = set(os.listdir(d))
            except OSError:
                break
            if (".claude-plugin" in names or "SKILL.md" in names
                    or ("server.py" in names and names & set(_TOOL_MARKS))):
                return True
            up = os.path.dirname(d)
            if not up or up == d:
                break
            d = up
    return False


def action_parts(call: dict) -> tuple[str, str, str, str, bool]:
    """(intent, text, code, files, builds): the AI's own words for the action, everything it says, the code it
    writes or runs, the local scripts a command runs or feeds, and whether it builds or runs its own way of doing
    something. intent "" = not an acting call."""
    tool = str(call.get("tool_name") or "")
    ti = call.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        fp = str(ti.get("file_path") or ti.get("notebook_path") or "")
        if not fp or JOURNAL_MD.search(fp) or re.search(r"\.(md|mdx|txt|rst)$", fp, re.I):
            return "", "", "", "", False   # prose (journals, rules, manuals, docs) is never the action itself
        content = str(ti.get("content") or ti.get("new_string") or ti.get("new_source") or "")[:4000]
        return Path(fp.replace("\\", "/")).name, fp, content, "", bool(CODE_EXT.search(fp))
    if tool in ("Bash", "PowerShell"):
        cmd = strip_identity(str(ti.get("command") or ""))
        if not (RUN_CMD.search(cmd) or WRITE_CMD.search(cmd)):
            return "", "", "", "", False   # reading or searching never stops
        desc = strip_identity(str(ti.get("description") or ""))
        # A command that writes prose into a markdown file (a journal entry, a rule, a manual) is not doing what the
        # prose talks about: only its description counts and it never stops (2026-10-26: a heredoc adding two rule
        # lines about Instagram posting to OWNER_SAID_JOURNAL.md was stopped). Automation in the same command
        # (a browser driven, a raw API call) still counts.
        # A commit or PR message is prose too.
        if (re.search(r"\.md\b", cmd, re.I) and not (code_concepts(cmd) & {"browser_automation", "http_api"})) \
                or GIT_COMMIT.search(cmd):
            return desc or cmd[:80], desc, "", "", False
        body = strip_payloads(cmd)
        files = strip_payloads(_local_files(body, str(call.get("cwd") or "")))
        if readonly_probe(cmd, files):
            return desc or cmd[:80], desc, "", "", False   # a read-only probe on a server is not an action
        return desc or cmd[:80], desc, body[:6000], files, not (reads_only(desc) or _TEST_WORDS.search(desc))
    if tool in ("Agent", "Task"):
        desc = str(ti.get("description") or "")
        # An agent the AI itself labels as research ("Research vision and market") reads and reports: it may get
        # the map, never a stop, whatever products its brief mentions (2026-10-27).
        t = concepts_table()
        verbs = {c for c in concepts_of(desc) if t["kind"].get(c) == "verb"}
        builds = not (verbs and verbs <= t["passive"]) and not reads_only(desc)
        return desc, strip_identity(desc + "\n" + str(ti.get("prompt") or "")[:4000]), "", "", builds
    return "", "", "", "", False


# "Send a Resend test mail to the mailbox and check KV": a test of our own setup shows the tools, never stops.
_TEST_WORDS = re.compile(r"\b(?:test|smoke|dry[- ]run|prueba|probar)\b", re.I)
_READ_START = re.compile(r"^\s*(?:show|list|count|check|find|read|inspect|measure|verify|compare|look|see|print|"
                         r"get|fetch|report|inventory|audit|evaluate|review|probe|mostrar|ver|contar|revisar|buscar)\b",
                         re.I)


def reads_only(desc: str) -> bool:
    """The AI labels the call as a read ("Show what the main feed has been posting"): a read verb first, and either
    a question clause (what, which, how) or no second action ("Find Playwright python on box and launch post" is
    a read AND a launch: it still acts)."""
    if not _READ_START.search(desc or ""):
        return False
    if re.search(r"\b(?:what|which|how|whether|why|que|cual|como)\b", desc, re.I):
        return True
    return not re.search(r"\b(?:and|then|y|luego)\b", desc, re.I)


def _check_concepts(call: dict, seen: dict) -> dict | None:
    """{"deny": text} once per intent when the action builds its own way and a tool already does it,
    {"note": text} when a tool fits but nothing is being built, None otherwise. Updates seen (session state)."""
    intent, text, code, files, builds = action_parts(call)
    if not intent:
        return None
    now = concepts_of(text, code)
    hist = seen.get("tc") or []
    # What the local scripts it runs or feeds say, and the session's last actions, count half: they are context,
    # never the verb of this action (a test harness that mentions Instagram is not posting to Instagram).
    ctx = {c: 1 for h in hist for c in h if c not in now}
    if files:
        ctx.update({c: 1 for c in concepts_of("", files) if c not in now})
    t = concepts_table()
    signals = code_concepts(code) | code_concepts(files)
    # What the action DOES comes from the AI's own words for it or from a code signal (set_input_files, a quoted
    # "Share", smtplib), never from a word that happens to sit in its code: "-shared" of x11vnc, ws.send of a
    # read-only CDP probe, "Shared=1" (2026-10-27, box infra work stopped as publishing and messaging).
    said = set(concepts_of(text)) | signals
    if call.get("tool_name") in ("Agent", "Task"):
        # An agent brief describes a whole job and mentions everything around it; what the agent DOES is the
        # AI's label for it (the description), its objects may come from the brief (2026-10-27: "Capture service
        # for demo recording", "Conector de la suite para IAs" were stopped on verbs buried in their briefs).
        said = {c for c in said if t["kind"].get(c) != "verb"} | set(concepts_of(intent)) | signals
    for c in [c for c in now if t["kind"].get(c) == "verb" and c not in said]:
        now.pop(c)
    # "Generate a strong password" is not media: generating a secret, a key or an id.
    if "generate_media" in now and "credentials" in said and not ({"image", "video", "audio"} & said) \
            and "generate_media" not in signals:
        now.pop("generate_media")
    # The channels this action itself names: its words, or a code signal in what it writes, runs or feeds.
    own_ch = channel_objects(said | (set(concepts_of("", code)) if call.get("tool_name") in EDIT_TOOLS else set()))
    # Shipping a website through its ship or deploy script is a site deploy, never social publishing, unless the
    # action itself names a channel (a "publish" script that drives instagram.com still counts).
    if site_ship(code, files, text) and not own_ch:
        return None
    # A verb that needs a channel counts only with one: "publish" with no platform, store or inbox in sight is not
    # posting; "send" with no inbox or chat named by the action itself is not a message ("send the site change
    # to the box").
    for v, (where, req) in t["needs"].items():
        if req is not None:
            # a list: one of those concepts must be named (a web source to scrape, a generation API or a platform to
            # generate for); a code signal of the verb itself (BeautifulSoup, scrapy) is enough on its own.
            # 2026-10-27: extracting frames from a local video and rendering a local game demo were stopped.
            if v not in signals and not (req & (said | set(now))):   # from the action, never the session context
                now.pop(v, None)
                ctx.pop(v, None)
            continue
        # a channel from context: the session's last actions or a code signal of what it runs, never a word that
        # sits in the script it feeds (hook.sh mentioning "email" made a panel auto-post a social post, 2026-10-27)
        if not (own_ch if where == "own" else channel_objects(set(now) | {c for h in hist for c in h} | signals)
                | ({"social_format"} & said)):   # a carousel or reel the action itself names is for a feed
            now.pop(v, None)
            ctx.pop(v, None)
        elif v in now and not own_ch and v in t["weak"] and v not in signals \
                and v not in concepts_of(t["weak"][v].sub(" ", _fold(text))):
            now.pop(v)   # only a weak word ("upload a fixed script") with a channel from context alone: not posting
    kinds = t["kind"]
    # A file written with no verb anywhere (no code signal of posting, sending, charging...) is code that only
    # mentions things: a Playwright check of our own app that opens the "instagram" folder is not posting
    # (2026-10-27, real_test.py).
    if call.get("tool_name") in EDIT_TOOLS and not _kinds_of(now, "verb"):
        return None
    if any(kinds.get(c) == "object" for c in now):
        seen["tc"] = (hist + [sorted(now)])[-HISTORY:]
    if not now:
        return None
    named = text + " " + code[:4000]
    cand = [g for g in rank(now, ctx, named) if _qualifies(g, now)][:12]
    # Cards whose rare words the action shares (an account, a script name) join the judge's list even when the concept
    # rank misses them (2026-11-03: the "read the DMs sent to @demoacct_" card was not among the concept candidates).
    have = {g["key"] for g in cand}
    cand += [g for g in _lexical_cands(f"{intent}\n{text}\n{code[:3000]}")
             if g["score"] >= LEX_MIN and g["key"] not in have and g["key"].startswith("card:")][:4]
    if not cand:
        return None
    # The judge picks among the candidates (2026-11-03: a session reading DMs of an account was shown Bidbot and
    # Gumroad, never Social Engine's message reader; the concept score cannot tell "read messages" from "publish").
    # The judge sees what the action RUNS, not only its description: the command and the local scripts it runs or
    # feeds (2026-11-05: "bash run_take.sh room8 1" runs capture.py, the very tool the judge kept recommending).
    picked = _judge_tools(intent, chr(10).join((text, code[:1500], _heads(files))), cand)
    if picked is not None:
        if not picked:
            return None
        groups = picked[:3]
    else:
        groups = [g for g in cand[:3] if g["score"] >= 0.6 * cand[0]["score"]]   # far behind the best = another job
    # Once per TARGET (the file written, the scripts, files and hosts a command acts on), not per description or
    # per best tool: rewording the same command, or the ranking shifting with the session's history, used to stop
    # the same action again (2026-10-27).
    key = "tm:" + hashlib.md5((target_of(call) or _fold(intent)).encode("utf-8")).hexdigest()[:16]
    if key in seen:
        return None
    # Working on a tool's own code is improving the tool: no stop and no note. A weak match (no shared verb and
    # object) is noise, not a map: nothing is shown (2026-10-26: "deploy" pulled Bidbot onto every server command).
    if _in_tool_source(text + "\n" + code[:3000], str(call.get("cwd") or "")):
        return None
    strong = _strong(groups[0], now)
    if not strong:
        # the AI's words, a clear code signal in what it writes or runs, or an object of its last actions
        own = set(concepts_of(text)) | set(code_concepts(code)) | set(code_concepts(files)) | own_ch
        # The objects of the last actions count only for an action that DOES something of its own ("send the post
        # job to the box" after building the carousel). A deploy, a check or a code edit with no verb never borrows
        # Instagram from the session (2026-10-27: a panel deploy and a library code patch got Social Engine).
        if (_kinds_of(now, "verb") - t["passive"]):
            own |= {c for h in hist for c in h}
        if not (_kinds_of(groups[0]["shared"], "object") & own):
            return None
        # With no verb at all, plain objects (an image, a fetch option) are code, not a job: only a channel the
        # action itself names keeps the map.
        if not _kinds_of(now, "verb") and not ((channel_objects(groups[0]["shared"]) | ({"social_format"} & groups[0]["shared"])) & own):
            return None
    seen[key] = 1
    txt = block(groups, now, intent)
    return {"deny": txt} if builds and strong else {"note": txt}


_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
LEX_MIN = 10.0  # text-match score of a real fit (measured 2026-11-03: real fits 11.7-17.4, noise 5.4-7.1)


def _words(text: str) -> set:
    return set(_WORD.findall(_fold(re.sub(r"[_\-./]", " ", text))))


def _lexical_cands(query: str, cap: int = 12) -> list[dict]:
    """Tool groups whose name, one-liner and function names share rare words with the action (the second road when
    the concept table has no word for the job: "read the DMs of @demoacct_" had no concept, 2026-11-03)."""
    import math as _m
    idx = tool_index()
    docs: dict = {}
    for e in idx["entries"]:
        fns = " ".join(f for v in (e.get("fn") or {}).values() for f in v)
        d = docs.setdefault(e["key"], {"words": set(), "entries": []})
        d["words"] |= _words(f"{e['name']} {e.get('one') or ''} {fns}")
        d["entries"].append((0.0, e))
    n = len(docs) or 1
    df: dict = {}
    for d in docs.values():
        for w in d["words"]:
            df[w] = df.get(w, 0) + 1
    q = _words(query)
    out = []
    for k, d in docs.items():
        sc = sum(_m.log(n / df[w]) for w in q & d["words"] if df[w] < n * 0.3)
        if sc > 0:
            out.append({"key": k, "entries": d["entries"], "shared": set(), "score": sc,
                        "name": idx["names"].get(k) or d["entries"][0][1]["name"]})
    out.sort(key=lambda g: -g["score"])
    return out[:cap]


def check(call: dict, seen: dict) -> dict | None:
    """The concept road first; when it finds nothing for an action that builds or runs its own way, the text road
    with the judge (once per target)."""
    r = _check_concepts(call, seen)
    if r is not None:
        return r
    intent, text, code, files, builds = action_parts(call)
    if not intent or not builds or _in_tool_source(text + "\n" + code[:3000], str(call.get("cwd") or "")):
        return None
    key = "tl:" + hashlib.md5((target_of(call) or _fold(intent)).encode("utf-8")).hexdigest()[:16]
    if key in seen:
        return None
    # No "the action names this tool" filter here: a script that names the account (@demoacct_) is not calling the card
    # whose title names that account; that filter hid the right card (2026-11-03).
    named = text + " " + code[:4000]
    cand = [g for g in _lexical_cands(f"{intent}\n{text}\n{code[:3000]}\n{files[:1000]}")
            if g["score"] >= LEX_MIN and (g["key"].startswith("card:") or not names_tool(tool_index(), g["key"], named))]
    picked = _judge_tools(intent, chr(10).join((text, code[:1500], _heads(files))), cand) if cand else None
    if not picked:
        return None
    seen[key] = 1
    return {"deny": block(picked[:3], {}, intent)}


if __name__ == "__main__":   # python toolmap.py "<what you are about to do>": the tools that already do it
    import sys
    q = " ".join(sys.argv[1:])
    now = concepts_of(q)
    gs = [g for g in rank(now, named=q) if _qualifies(g, now)]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(now))
    for g in gs[:6]:
        print(round(g["score"], 2), g["key"], sorted(g["shared"]))
    print(block(gs, now, q) if gs else "(no tool fits)")
