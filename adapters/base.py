"""The adapter contract: one core (quick_hook.py), thin plugs per AI app.

Each app sends its own hook payload. normalize() turns it into the Claude Code-style dicts quick_hook.py already handles
({hook_event_name, tool_name, tool_input: {file_path | command | paths | mcp_tool ...}, session_id, cwd, prompt}),
run_core() runs the unchanged core in this process, and the app's out_*() methods write its answer back in the
shape the app expects. quick_hook.py with no --app is never touched by any of this.

Gate safety. In Claude Code the first touch of a mapped piece carries its journal brief, and a touch with no brief
to give is denied until the session read the journal (the mod reports each read). In these apps that read path is
not tested live yet, so by default the gate only DELIVERS the brief or warns, never denies:
  JOURNAL_GATE_CODEX / JOURNAL_GATE_COPILOT / JOURNAL_GATE_CURSOR = note (default) | deny
"deny" behaves like Claude Code (the adapter then also reports journal reads, reports_reads). Every other stop
(money guard, server flood, the exact rule tests, the default rules pack) stays a stop in both modes.
"""
import io
import json
import os
import re
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent  # the journal-mcp folder (quick_hook.py lives here)
DEFAULT_GATE = "note"
GATE_MODES = ("note", "deny")

# Stops that come from the journals gate (quick_hook.gate, read_turn, quickmap's edit gate and intent map).
GATE_SIG = re.compile(r"JOURNALS GATE|^JOURNALS: you are reading code or data|^JOURNALS FOR WHAT|^REPLACED/NEWER"
                      r"|The call passes once that journal read is recorded", re.M)
RETRY_LINE = re.compile(r"\n*\(?(Stopped once:|The call passes once that journal read)[^\n]*\)?")
BRIEF_SIG = re.compile(r"JOURNAL BRIEF for ")
JOURNAL_FILE = re.compile(r"journal[^\\/]*\.md$", re.I)
JOURNAL_READ_TOOL = re.compile(r"(?:^|[^a-z0-9])(journal_(?:read_section|read|handoff_brief|search|quick))$", re.I)
JOURNAL_SAVE_TOOL = re.compile(r"(?:^|[^a-z0-9])journal_(?:append|update_section|decision_add|capability_add)$", re.I)
DATA_TOOL = re.compile(r"sql|query", re.I)

SHELL_NAMES = {"bash", "powershell", "shell", "exec", "run_in_terminal", "runinterminal", "run_shell_command",
               "run_command", "terminal"}
WRITE_NAMES = {"write", "create", "create_file", "createfile", "write_file"}
EDIT_NAMES = {"edit", "multiedit", "notebookedit", "editfiles", "edit_file", "replace_string_in_file",
              "multi_replace_string_in_file", "insert_edit_into_file", "strreplace", "str_replace",
              "str_replace_editor", "search_replace", "delete", "delete_file", "apply_patch"} | WRITE_NAMES
READ_NAMES = {"read", "view", "readfile", "read_file"}
GREP_NAMES = {"grep", "grep_search", "search", "codebase_search"}
GLOB_NAMES = {"glob", "file_search", "list_dir", "ls"}
AGENT_NAMES = {"task", "agent", "subagent", "runsubagent"}

BRAIN = ("JOURNALS (one brain). Every project keeps its context in a *_JOURNAL.md. Before touching, building or "
         "answering about anything, call journal_quick(\"<word or file>\") and read what it points to: what was "
         "decided, what exists, what is in flight. The journals hooks put a piece's journal brief in front of you "
         "when you touch it: read it before acting. Before writing your own script for a job, use the tool that "
         "already does it.")


def gate_mode(app: str) -> str:
    m = os.environ.get(f"JOURNAL_GATE_{app.upper()}", DEFAULT_GATE).strip().lower()
    return m if m in GATE_MODES else DEFAULT_GATE


def home() -> Path:
    return Path(os.environ.get("JOURNAL_HOME", str(Path.home() / ".journal")))


def log_error(where: str) -> None:
    try:
        import traceback
        from datetime import datetime, timezone
        with (home() / "quick_errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} adapter {where} "
                     f"{traceback.format_exc()}\n")
    except Exception:
        pass


class _Capture(io.StringIO):
    """stdout stand-in: the core calls sys.stdout.reconfigure(...), which a plain StringIO does not have."""

    def reconfigure(self, *a, **k):
        pass


def run_core(flag: str, call: dict) -> dict:
    """Run quick_hook.main() unchanged on one Claude Code-style call; give back its hookSpecificOutput ({} for none)."""
    if str(CORE_DIR) not in sys.path:
        sys.path.insert(0, str(CORE_DIR))
    old = sys.argv, sys.stdin, sys.stdout, os.getcwd()
    buf = _Capture()
    try:
        import quick_hook
        sys.argv = ["quick_hook.py"] + ([flag] if flag else [])
        sys.stdin = io.StringIO(json.dumps(call))
        sys.stdout = buf
        quick_hook.main()
    except Exception:
        log_error(f"core {flag or 'pre'}")
    finally:
        sys.argv, sys.stdin, sys.stdout = old[0], old[1], old[2]
        try:
            os.chdir(old[3])  # the core changes to its own folder before loading the map
        except OSError:
            pass
    out = buf.getvalue().strip()
    for text in (out, out.splitlines()[-1] if out else ""):
        try:
            doc = json.loads(text)
            return (doc.get("hookSpecificOutput") or {}) if isinstance(doc, dict) else {}
        except Exception:
            continue
    return {}


# ---- payload helpers -------------------------------------------------------------------------------------------

def first(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def as_dict(v) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip().startswith("{"):
        try:
            o = json.loads(v)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    return {}


def command_text(cmd) -> str:
    """A command as one string: Codex may send an argv array (["bash", "-lc", "ls"])."""
    if isinstance(cmd, (list, tuple)):
        parts = [str(x) for x in cmd]
        if len(parts) >= 3 and parts[-2] in ("-c", "-lc", "-Command", "/c", "-command"):
            return parts[-1]
        return " ".join(parts)
    return str(cmd or "")


def result_text(res) -> str:
    """The text a finished tool returned, whatever shape the app gives it."""
    if res is None:
        return ""
    if isinstance(res, str):
        o = as_dict(res)
        return result_text(o) if o else res
    if isinstance(res, dict):
        for k in ("textResultForLlm", "text", "output", "stdout", "aggregated_output", "formatted_output", "result"):
            if isinstance(res.get(k), str) and res[k]:
                return res[k]
        if isinstance(res.get("content"), list):
            return "\n".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in res["content"])
    try:
        return json.dumps(res, ensure_ascii=False)
    except Exception:
        return str(res)


def result_ok(res) -> bool:
    d = as_dict(res) if not isinstance(res, dict) else res
    if not d:
        return True
    if d.get("isError") is True or d.get("is_error") is True or d.get("success") is False:
        return False
    return str(d.get("resultType") or "success").lower() not in ("failure", "error", "denied", "rejected")


def abs_path(p: str, cwd: str) -> str:
    p = str(p or "").strip()
    if not p or re.match(r"^([A-Za-z]:)?[\\/]", p) or p.startswith("~") or not cwd:
        return p
    return os.path.normpath(os.path.join(cwd, p))


def mcp_bare(name: str) -> str:
    """mcp__journal__journal_read, MCP:journal_read, journal-journal_read -> journal_read (or the name itself)."""
    m = JOURNAL_READ_TOOL.search(name or "")
    return m.group(1).lower() if m else name


def is_mcp(name: str) -> bool:
    return name.startswith("mcp__") or name.startswith("MCP:") or bool(JOURNAL_READ_TOOL.search(name)) \
        or bool(JOURNAL_SAVE_TOOL.search(name))


def merge(outs: list) -> tuple:
    """Several core answers (one per file of a patch) -> (deny reason or "", context or "")."""
    denies = [o.get("permissionDecisionReason", "") for o in outs if o.get("permissionDecision") == "deny"]
    ctx = [o.get("additionalContext", "") for o in outs if o.get("additionalContext")]
    return "\n\n".join(d for d in denies if d), "\n\n".join(dict.fromkeys(c for c in ctx if c))


class Adapter:
    name = "base"
    EVENTS: dict = {}   # the app's event name -> pre | post | prompt | session | stop | reply
    EMPTY = ""          # what to print when there is nothing to say ("{}" where the app needs valid JSON)

    # ---- normalize: app payload -> Claude Code-style calls ---------------------------------------------------------

    def kind(self, p: dict, event: str = "") -> str:
        return self.EVENTS.get(event or str(p.get("hook_event_name") or ""), "")

    def session_id(self, p: dict) -> str:
        return str(first(p, "session_id", "sessionId", "conversation_id", "conversationId",
                         default=f"{self.name}-nosession"))

    def cwd(self, p: dict) -> str:
        roots = first(p, "workspace_roots", "workspaceRoots", default=[]) or [""]
        return str(first(p, "cwd", default=roots[0] if isinstance(roots, list) else ""))

    def tool(self, p: dict) -> tuple:
        return str(first(p, "tool_name", "toolName", default="")), as_dict(first(p, "tool_input", "toolArgs",
                                                                               default={}))

    def tool_result(self, p: dict):
        return first(p, "tool_response", "tool_result", "toolResult", "tool_output")

    def reply_text(self, p: dict) -> str:
        return str(first(p, "last_assistant_message", "lastAssistantMessage", "response", "text", default=""))

    def prompt_text(self, p: dict) -> str:
        return str(first(p, "prompt", default=""))

    def classify(self, name: str) -> str:
        n = name.lower()
        if is_mcp(name):
            return "mcp"
        for k, names in (("shell", SHELL_NAMES), ("write", WRITE_NAMES), ("edit", EDIT_NAMES), ("read", READ_NAMES),
                         ("grep", GREP_NAMES), ("glob", GLOB_NAMES), ("agent", AGENT_NAMES)):
            if n in names:
                return k
        return ""

    def edit_targets(self, name: str, args: dict, cwd: str) -> list:
        """[(file_path, written text)] for an edit or write call."""
        fp = first(args, "file_path", "filePath", "path", "target_file", "targetFile", "notebook_path", "file")
        paths = [fp] if fp else [first(f, "filePath", "file_path", "path") if isinstance(f, dict) else f
                                 for f in (args.get("files") or [])]
        text = first(args, "content", "contents", "new_string", "newString", "new_str", "file_text", "code_edit",
                     "code", "text", "new_source", default="")
        if not text and isinstance(args.get("edits"), list):
            text = "\n".join(str(e.get("new_string") or e.get("newString") or "") for e in args["edits"]
                             if isinstance(e, dict))
        return [(abs_path(str(x), cwd), str(text)[:4000]) for x in paths if x]

    def pre_tool_calls(self, p: dict) -> list:
        """The Claude Code-style tool calls this pre-tool event stands for (the same inputs the Claude Code mod sends)."""
        name, args = self.tool(p)
        cwd = self.cwd(p)
        k = self.classify(name)
        calls = []
        if k == "shell":
            cmd = command_text(first(args, "command", "cmd", "script", default=""))
            if cmd:
                calls.append(("Bash", {"command": cmd, "description": str(args.get("description") or "")}))
        elif k in ("write", "edit"):
            for fp, text in self.edit_targets(name, args, cwd):
                if fp and not JOURNAL_FILE.search(fp):
                    calls.append(("Write" if k == "write" else "Edit", {"file_path": fp, "content": text}))
        elif k == "read":
            fp = abs_path(str(first(args, "file_path", "filePath", "path", "target_file", default="")), cwd)
            if fp and not JOURNAL_FILE.search(fp):   # a journal read is never gated; it is recorded after it ran
                calls.append(("Read", {"paths": [fp]}))
        elif k in ("grep", "glob"):
            where = first(args, "path", "file_path", "directory", "target_directory")
            ps = [abs_path(str(where), cwd)] if where else []
            pattern = first(args, "glob", "glob_pattern") if k == "grep" else first(args, "pattern", "glob",
                                                                                    "glob_pattern")
            ps += [str(pattern)] if pattern else []
            if ps:
                calls.append(("Grep" if k == "grep" else "Glob", {"paths": ps}))
        elif k == "agent":
            calls.append(("Agent", {"description": str(args.get("description") or ""),
                                    "prompt": str(first(args, "prompt", "task", default=""))[:4000]}))
        elif k == "mcp" and not JOURNAL_READ_TOOL.search(name) and not JOURNAL_SAVE_TOOL.search(name):
            try:
                a = json.dumps(args, ensure_ascii=False)
            except Exception:
                a = str(args)
            if DATA_TOOL.search(name) and not re.search(r"journal", name, re.I):
                calls.append((name, {"query": str(first(args, "query", "sql", default=a))[:4000]}))
            else:
                calls.append((name, {"mcp_tool": name, "args": a[:3000]}))
        return [{"hook_event_name": "PreToolUse", "tool_name": t, "tool_input": ti} for t, ti in calls]

    def post_tool_calls(self, p: dict) -> list:
        """After a tool ran: [(flag, call)]: a journal read to record (opens the gate) and a command's output check."""
        name, args = self.tool(p)
        res = self.tool_result(p)
        k = self.classify(name)
        out = []
        if k == "mcp" and JOURNAL_READ_TOOL.search(name):
            out.append(("", {"tool_name": name, "tool_input": {"journal_tool": mcp_bare(name), "args": args,
                                                               "text": result_text(res)[:40000],
                                                               "ok": result_ok(res)}}))
        elif k == "read":
            fp = abs_path(str(first(args, "file_path", "filePath", "path", "target_file", default="")), self.cwd(p))
            if JOURNAL_FILE.search(fp):
                out.append(("", {"tool_name": "Read", "tool_input": {"journal_read": fp, "ok": result_ok(res)}}))
        elif k == "shell":
            text = result_text(res)
            if len(text) > 20:
                out.append(("--output", {"output": text[-60000:]}))
        return out

    def normalize(self, p: dict, event: str = "") -> list:
        """[(core flag, Claude Code-style call)] for this event, each with session_id and cwd (and reports_reads in deny
        mode, so the gate may wait for a recorded read)."""
        kind = self.kind(p, event)
        base = {"session_id": self.session_id(p), "cwd": self.cwd(p)}
        if gate_mode(self.name) == "deny":
            base["reports_reads"] = True
        if kind == "pre":
            calls = [("", c) for c in self.pre_tool_calls(p)]
        elif kind == "post":
            calls = self.post_tool_calls(p)
        elif kind in ("prompt", "session"):
            text = self.prompt_text(p) if kind == "prompt" else str(first(p, "initial_prompt", "initialPrompt",
                                                                          default=""))
            calls = [("--prompt", {"hook_event_name": "UserPromptSubmit", "prompt": text})] if text else []
        elif kind == "stop":
            calls = [("--stop", {"hook_event_name": "Stop", "reply": self.stop_reply(p),
                                 "stop_hook_active": bool(self.stop_active(p))})]
        else:
            calls = []
        return [(f, {**c, **base}) for f, c in calls]

    def stop_reply(self, p: dict) -> str:
        return self.reply_text(p)

    def stop_active(self, p: dict) -> bool:
        return bool(first(p, "stop_hook_active", "stopHookActive", default=False))

    # ---- gate policy -----------------------------------------------------------------------------------------

    def soften(self, out: dict) -> dict:
        """Note mode: a journals-gate stop becomes context the AI sees; any other stop stays a stop."""
        reason = out.get("permissionDecisionReason", "")
        if out.get("permissionDecision") != "deny" or gate_mode(self.name) != "note" or not GATE_SIG.search(reason):
            return out
        note = ("JOURNALS (note, nothing was stopped): read the journal named below before you act on this.\n"
                + RETRY_LINE.sub("", reason).strip())
        return {"hookEventName": out.get("hookEventName", "PreToolUse"),
                "additionalContext": note + ("\n\n" + out["additionalContext"] if out.get("additionalContext") else "")}

    # ---- run one event -----------------------------------------------------------------------------------------

    def handle(self, p: dict, event: str = "", core=run_core):
        """One hook event -> the app's output object (None when there is nothing to say)."""
        kind = self.kind(p, event)
        sid = self.session_id(p)
        calls = self.normalize(p, event)
        if kind == "pre":
            deny, ctx = merge([self.soften(core(f, c)) for f, c in calls])
            return self.out_pre(deny, ctx, sid)
        if kind == "post":
            _, ctx = merge([core(f, c) for f, c in calls])
            return self.out_post(ctx, sid)
        if kind == "prompt":
            _, ctx = merge([core(f, c) for f, c in calls])
            return self.out_prompt(ctx, sid)
        if kind == "session":
            _, ctx = merge([core(f, c) for f, c in calls])
            return self.out_session(BRAIN + ("\n\n" + ctx if ctx else ""), sid)
        if kind == "stop":
            if not calls or not calls[0][1].get("reply"):
                return None
            return self.out_stop(str(core(*calls[0]).get("block") or ""), sid)
        if kind == "reply":
            return self.on_reply(p, sid)
        return None

    # ---- format: core answer -> app output (override per app) ---------------------------------------------------

    def out_pre(self, deny: str, ctx: str, sid: str):
        raise NotImplementedError

    def out_post(self, ctx: str, sid: str):
        raise NotImplementedError

    def out_prompt(self, ctx: str, sid: str):
        raise NotImplementedError

    def out_session(self, ctx: str, sid: str):
        raise NotImplementedError

    def out_stop(self, reason: str, sid: str):
        raise NotImplementedError

    def on_reply(self, p: dict, sid: str):
        return None

    def render(self, out) -> str:
        return self.EMPTY if out is None else json.dumps(out, ensure_ascii=True)

    # ---- per-session queue: context an app cannot take now rides on its next event that can ------------------

    def _qfile(self, sid: str) -> Path:
        d = home() / "adapter_queue"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.name}-{re.sub(r'[^A-Za-z0-9_-]', '', sid)[:80]}.json"

    def _qload(self, sid: str) -> dict:
        try:
            return json.loads(self._qfile(sid).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _qsave(self, sid: str, st: dict) -> None:
        try:
            self._qfile(sid).write_text(json.dumps(st), encoding="utf-8")
        except Exception:
            pass

    def queue_put(self, sid: str, text: str) -> None:
        if not text:
            return
        st = self._qload(sid)
        q = [x for x in st.get("queue") or [] if x != text] + [text]
        st["queue"] = q[-5:]
        self._qsave(sid, st)

    def queue_take(self, sid: str) -> str:
        st = self._qload(sid)
        q = st.pop("queue", None) or []
        if q:
            self._qsave(sid, st)
        return "\n\n".join(q)

    def state_set(self, sid: str, key: str, value) -> None:
        st = self._qload(sid)
        st[key] = value
        self._qsave(sid, st)

    def state_get(self, sid: str, key: str, default=None):
        return self._qload(sid).get(key, default)
