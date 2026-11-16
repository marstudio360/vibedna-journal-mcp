"""Done check: a reply that says "done", "fixed", "live" (English or Spanish) right after a change nobody looked at.

No AI. Read from the session transcript at the end of the turn. It stops only the clear case: the last thing the AI did
to the work was a CHANGE (an edit, a write, a command that writes or deploys, a script run), nothing LOOKED at anything
after it (no test, build, request to the page, screenshot, status read, read-back of a file), and the reply claims a
result. Then the reply goes back once for the one line that proves it, or for a plain "not verified yet".

Built for precision. In a first pilot on a real working session (37 stops read one by one) about 4 caught something
really wrong, 9 narrowed a claim to what was proven, 13 confirmed, 11 were false alarms from the wording. A replay of
that first rule over 615 real turns would have sent back 145, far too many, so this version stops only the clear
case: a plan, a negative, a name or a question is not a claim; a note, a git save, a document or a scratch file is
not a change; any look after the change is enough. Replayed on 1,533 real turns it sends back 26 (1.7%).

JOURNAL_DONE_CHECK=off turns it off. Standard library only; any error means no stop.
"""
from __future__ import annotations

import json
import os
import re

_PART = r"(?:listo|lista|hecho|hecha|arreglado|arreglada|corregido|corregida|resuelto|resuelta|terminado|terminada|" \
        r"publicado|publicada|desplegado|desplegada|subido|subida|funcionando|andando|en vivo)"
CLAIM = re.compile(
    r"(?<![\w-])(?:done|fixed|shipped|deployed|it works|works now|all set|completed|finished|resolved|solved|"
    r"implemented|ready to (?:ship|go|deploy|use)|is live|now live|good to go|should work now|should be fixed|"
    r"ya est[aá] " + _PART + r"|qued[oó] " + _PART + r"|ya (?:funciona|anda)|ya est[aá](?=\s*[:.!\n])|"
    r"listo(?=\s*[:.,!\n])|hecho(?=\s*[:.!\n]))(?![\w-])", re.I)
# words just before the claim that make it a plan, a condition or a negative
NOT_A_CLAIM = re.compile(
    r"(?:\bnot|n't|\bnever|\bneither|\bnor|\bno|\bnone|\bnothing|\buntil|\bonce|\bwhen|\bif|\bafter|\bbefore|\bto be|"
    r"\balmost|\bnearly|\bwhether|\bwill|\bwould|\bshould|\bmust|\bcan|\bgoing to|\bto get|\bnext|\bthen|\bstill|"
    r"\bnunca|\bni|\bsin|\btodav[ií]a|\ba[uú]n|\bfalta|\bcuando|\bsi|\bdespu[eé]s|\bantes|\bhasta|\bpara|\bva a|"
    r"\bvoy a|\bcasi|\bluego|\bqueda|\bquedan)\W+(?:[\w']+\W+){0,3}$", re.I)
# right after the claim: an adjective use ("fixed 28-day window", "done gate") or a name ("Working now card")
NOT_A_RESULT = re.compile(r"^\W{0,2}(?:\d|gate\b|check\b|list\b|price\b|size\b|width\b|window\b|rate\b|amount\b|para\b)", re.I)
ADMITS = re.compile(r"(?i)not (?:yet )?verified|unverified|not (?:yet )?checked|not (?:yet )?tested|not proven|"
                    r"sin verificar|no (?:lo |la |est[aá] )?verifi|falta (?:ver|verificar|probar|comprobar)|"
                    r"no (?:lo |la )?prob[eé]|sin probar|todav[ií]a no (?:lo |la )?(?:vi|prob|verifi)")

LOOK_CMD = re.compile(
    r"(?:^|[\s;&|(`'\"])(?:ls|dir|cat|type|grep|rg|head|tail|find|wc|stat|du|df|diff|cmp|file|jq|curl|wget|tree|xh|"
    r"Get-Content|Get-ChildItem|Get-Item|Test-Path|Select-String|Get-ScheduledTask\w*|Get-Process|Get-Service|"
    r"Get-FileHash|Invoke-WebRequest|Invoke-RestMethod|sha256sum|md5sum|ps|ss|netstat|journalctl|"
    r"pytest|jest|vitest|mocha|phpunit|rspec|unittest|tox|nox|cypress|playwright|lighthouse|puppeteer|"
    r"tsc|eslint|ruff|mypy|pyright|flake8|pylint|biome|stylelint|py_compile|compileall)\b"
    r"|\bcrontab\s+-l\b|\bsystemctl\s+(?:status|is-active)\b|\bdocker\s+(?:ps|logs)\b|\bgit\s+(?:status|diff|log|show|ls-files)\b"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|tests|build|lint|check|typecheck|type-check|e2e|verify|ci)\b"
    r"|\b(?:cargo|go|dotnet)\s+(?:test|build|check|vet|clippy)\b|\b(?:make|just)\s+(?:test|check|build|verify|ci|smoke)\b"
    r"|\b(?:next|vite|astro|nuxt)\s+(?:build|check)\b|\bnode\s+--check\b|\bgit\s+apply\s+--check\b"
    r"|--dry-run\b|--status\b|--plan\b|\bast\.parse\b|\bprint\(|console\.log\(", re.I)
LOOK_SCRIPT = re.compile(r"(?i)(?:^|[/\\_.-])(?:test|check|verify|shoot|screenshot|probe|smoke|audit|measure|validate|strip|"
                         r"read|show|list|print|status|report|find|search|dump|look|cat|get|count|stat|grep|scan|inspect|"
                         r"query|peek|diff|replay)[\w-]*\.(?:py|pyw|js|mjs|cjs|ts|sh|ps1)$")
LOOK_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch"}
LOOK_TOOL_WORDS = {"test", "tests", "screenshot", "browser", "playwright", "navigate", "fetch", "preview", "verify",
                   "diagnostics", "lint", "check", "snapshot", "get", "list", "read", "search", "status", "info",
                   "query", "quick", "find", "show", "view"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# Housekeeping (rm, mkdir, chmod, opening a file for the owner) and downloads are not a change to the work.
CHANGE_CMD = re.compile(
    r"(?:^|[\s;&|(])(?:mv|cp|tee|install|rsync|Set-Content|Add-Content|Out-File|Copy-Item|Move-Item|Rename-Item|"
    r"Register-ScheduledTask|Unregister-ScheduledTask)\b"
    r"|\bscp\b[^;&|\n]*\s[\"']?[\w.@-]{2,}:[^\s\"']+[\"']?\s*(?:$|[;&|\n)'])"   # scp TO a server; from a server is a look
    r"|\bsed\s+-i\b|\bgit\s+(?:push|merge|rebase|reset|checkout|apply|pull|revert|cherry-pick|am)\b(?!\s+--check)"
    r"|\b(?:npm|pnpm|yarn|bun|pip|pip3|uv)\s+(?:install|add|remove|uninstall|publish|update|upgrade|ci)\b"
    r"|(?:^|[;&|(]\s*|\b(?:npm|pnpm|yarn|bun)\s+run\s+|\b(?:vercel|wrangler|netlify|firebase|fly|railway|sudo)\s+(?:-\S+\s+)*)"
    r"(?:deploy|ship|publish|release|migrate|upload)[\w:.-]*(?!\S*\s+--(?:status|tag|plan|dry-run))"
    r"|[\w./~-]*(?:deploy|ship|publish|release)[\w-]*\.(?:sh|py|mjs|js)\b(?!\s+--(?:status|tag|plan|dry-run))"
    r"|\bsystemctl\s+(?:start|stop|restart|reload|enable|disable)\b|\bschtasks\s+/(?:create|delete|change)\b"
    r"|\bcrontab\s+(?!-l)\S"
    r"|(?<![0-9&<>=-])>{1,2}\s*(?!/dev/null|\$null|&)[\"']?[\w~$.-]*[/\\.][\w./\\~-]+", re.I)
SCRIPT_RUN = re.compile(r"\b(?:python[0-9.]*|py|pythonw|node|bash|sh|pwsh|powershell)(?:\.exe)?\"?\s+(?:-[A-Za-z]\s+)*"
                        r"(?!-)[\"']?([^\s\"'<>|;&]+\.(?:py|pyw|js|mjs|cjs|ts|sh|ps1))", re.I)
INLINE_WRITE = re.compile(r"\.write(?:_text|_bytes)?\(|open\([^)]*[\"'][wa]b?\+?[\"']|os\.replace|os\.remove|shutil\.|"
                          r"\.unlink\(|writeFileSync|json\.dump\(")
# notes are not a change to the work: the journal entry written after the check is the usual last step of a turn
_NOTE_SRC = (r"(?:journal|handoff|work[_ -]?log|worklog|changelog|notes?|memory|now_post)[^/\\\s\"']*"
             r"\.(?:md|txt|jsonl|log|py|pyw|sh)\b|(?:^|[/\\])memory[/\\]"
             r"|\b(?:log_work|journal_append|journal_update_section|journal_decision_add|journal_capability_add|log_mistake)\b")
NOTE = re.compile(_NOTE_SRC, re.I)
_NOTE_TOKEN = re.compile(r"[^\s\"';|&<>]*(?:" + _NOTE_SRC + r")", re.I)  # the whole path of a note file
SCRATCH = re.compile(r"(?i)[/\\](?:scratchpad|te?mp)[/\\]|^/tmp/")
TAIL_BYTES = 2_000_000


def claim_in(text: str) -> str:
    """The first word of the reply that claims a result, or ''. Code blocks, quotes and questions do not count."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith((">", "- [ ]")))
    for m in CLAIM.finditer(text):
        before = re.split(r"[.!?:;\n]", text[max(0, m.start() - 60):m.start()])[-1]
        after = text[m.end():m.end() + 24]
        sentence_end = re.search(r"[.!\n?]", text[m.end():m.end() + 160])
        if NOT_A_CLAIM.search(before) or NOT_A_RESULT.search(after):
            continue
        if ADMITS.search(text[m.start():m.end() + 160]):
            continue
        if sentence_end and sentence_end.group(0) == "?":
            continue
        if m.group(0)[:1].isupper() and re.match(r"\s+[A-Z]", after):  # "Working Now", "Done Gate": a name
            continue
        return m.group(0)
    return ""


def _content(entry: dict) -> list:
    msg = entry.get("message") or {}
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c if isinstance(c, list) else []


def _real_user(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    items = _content(entry)
    if any(isinstance(i, dict) and i.get("type") == "tool_result" for i in items):
        return False
    return any(isinstance(i, dict) and i.get("type") == "text" and str(i.get("text", "")).strip() for i in items)


def last_turn_tools(transcript_path: str) -> list:
    """[(tool name, input)] of the AI since the user's last real message."""
    with open(transcript_path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_BYTES))
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]
    entries = []
    for ln in lines:
        try:
            entries.append(json.loads(ln))
        except ValueError:
            continue
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        if _real_user(entries[i]):
            start = i + 1
            break
    tools = []
    for e in entries[start:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for item in _content(e):
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tools.append((str(item.get("name", "")), item.get("input") or {}))
    return tools


def _last(rx, text: str) -> int:
    pos = -1
    for m in rx.finditer(text):
        pos = m.start()
    return pos


_HEREDOC = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?[^\n]*\n(.*?)\n\s*\1\b", re.S)
_TO_SCRATCH = re.compile(r">{1,2}\s*[\"']?(?:\$\{?(?:[A-Z]|\w*(?:TE?MP|SCRATCH)\w*)\}?[/\\]|[^\s\"';|&]*(?:scratchpad|[/\\]te?mp[/\\]))"
                         r"[^\s\"';|&]*[\"']?", re.I)
# A report, a readout or a manual written from the shell is a document, the same as one written with the Write tool
# (2026-11-14 replay of 4,165 real turns of a team of AI workers: most of the 125 stops were "cat > REPORT.md",
# "printf ... >> FIXES.md", "sed -i ... NOTES.md" or a heredoc script that rewrites OPTIMIZE.md, then a message).
_TO_DOC = re.compile(r">{1,2}\s*[\"']?[^\s\"';|&<>]*\.md\b[\"']?"
                     r"|\bsed\s+-i\b[^;&|\n]*\.md\b[\"']?(?=\s*(?:$|[;&|\n)]))", re.I)
_QUOTED_FILE = re.compile(r"[\"']([^\"'\n]*\.(\w{1,5}))[\"']")
_SCRIPT_IN = re.compile(r"<\s*[\"']?([^\s\"'<>|;&]+\.(?:sh|py|ps1))", re.I)
_DOC = re.compile(r"(?i)\.(?:md|txt|rst)$")
_SCP_FROM = re.compile(r"\bscp\b(?:\s+-\S+)*\s+[\"']?[\w.@-]{2,}:", re.I)  # fetching results from a server


def split_heredocs(cmd: str) -> tuple[str, str]:
    """(the shell lines, the code or text fed to them through heredocs)."""
    bodies = "\n".join(m.group(2) for m in _HEREDOC.finditer(cmd))
    return _HEREDOC.sub(" ", cmd), bodies


def classify(name: str, inp: dict) -> tuple[str, str]:
    """('change' | 'look' | '', short label). A command that changes and then looks at it counts as a look."""
    if name in SHELL_TOOLS:
        head, body = split_heredocs(str(inp.get("command") or ""))
        work = _TO_DOC.sub(" ", _TO_SCRATCH.sub(" ", _NOTE_TOKEN.sub(" ", head)))
        change, what = _last(CHANGE_CMD, work), "ran a command that writes"
        look = max(_last(LOOK_CMD, head), _last(_SCP_FROM, head))
        for m in list(SCRIPT_RUN.finditer(head)) + list(_SCRIPT_IN.finditer(head)):
            script = m.group(1)
            if LOOK_SCRIPT.search(script):
                look = max(look, m.start())
            elif not NOTE.search(script) and m.start() > change:
                change, what = m.start(), "ran " + os.path.basename(script.replace("\\", "/"))
        if change < 0 and body:
            if NOTE.search(head) or NOTE.search(body):  # the entry written through a heredoc is a note
                return "", ""
            if INLINE_WRITE.search(body) and not (SCRATCH.search(head) or SCRATCH.search(body)):
                exts = {m.group(2).lower() for m in _QUOTED_FILE.finditer(body)}
                if not (exts and exts <= {"md"}):   # a script that only rewrites documents is a note
                    change = 0
            elif LOOK_CMD.search(body):
                look = max(look, 0)
        if look > change:
            return "look", ""
        if change >= 0:
            return "change", what
        return "", ""
    if name in WRITE_TOOLS:
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if NOTE.search(path) or SCRATCH.search(path) or _DOC.search(path):
            return "", ""
        return "change", "edited " + os.path.basename(path.replace("\\", "/"))
    if name in LOOK_TOOLS:
        return "look", ""
    if NOTE.search(name):
        return "", ""
    words = set(w.lower() for w in re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)) if w)
    if LOOK_TOOL_WORDS & words:
        return "look", ""
    return "", ""


def last_change_and_look(tools: list) -> tuple[int, int, str]:
    change, look, what = -1, -1, ""
    for i, (name, inp) in enumerate(tools):
        kind, label = classify(name, inp if isinstance(inp, dict) else {})
        if kind == "change":
            change, what = i, label
        elif kind == "look":
            look = i
    return change, look, what


def check(reply: str, transcript_path: str) -> str:
    """'' when fine; else the text that sends the reply back once."""
    if os.environ.get("JOURNAL_DONE_CHECK", "").lower() in ("off", "0", "false", "no"):
        return ""
    word = claim_in(reply or "")
    if not word or not transcript_path or not os.path.isfile(transcript_path):
        return ""
    change, look, what = last_change_and_look(last_turn_tools(transcript_path))
    if change < 0 or look > change:
        return ""
    return ("DONE CHECK: your reply says \"%s\", but nothing looked at the result after your last change in this turn (%s). "
            "The owner has already read the reply. Now run the check that proves it (a test, a build, a request to the "
            "page, a screenshot, a status read) and write ONLY one or two lines, in the owner's language, with its result. "
            "If it cannot be checked from here, say plainly that it is not verified yet and what to open or run to see it. "
            "Do not repeat the reply and do not mention this check." % (word, what))
