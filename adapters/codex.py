"""OpenAI Codex (CLI and desktop app). Hook contract per https://learn.chatgpt.com/docs/hooks.md (read 2026-11-10):
nearly Claude Code's. Shell runs as Bash (tool_input.command, a string or an argv array); file edits go through
apply_patch, whose patch text is in tool_input.command; MCP tools are mcp__<server>__<tool>. Output is Claude Code's
hookSpecificOutput (permissionDecision / additionalContext); Stop takes {"decision": "block", "reason"}.
"""
import re

from adapters.base import Adapter, abs_path, command_text, first

PATCH_HEAD = re.compile(r"^\*\*\* (Update|Add|Delete) File:\s*(.+?)\s*$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$")


def parse_patch(text: str, cwd: str = "") -> list:
    """[(file_path, added text)] for every file an apply_patch touches, in order; a Move to: target is its own
    entry. Paths are made absolute against cwd."""
    files, cur = [], None
    for ln in str(text or "").splitlines():
        m = PATCH_HEAD.match(ln)
        mv = PATCH_MOVE.match(ln)
        if m or mv:
            cur = [abs_path(m.group(2) if m else mv.group(1), cwd), []]
            files.append(cur)
        elif cur is not None and ln.startswith("+") and not ln.startswith("+++"):
            cur[1].append(ln[1:])
        elif ln.startswith("*** End Patch"):
            cur = None
    out, seen = [], set()
    for fp, added in files:
        if fp and fp not in seen:
            seen.add(fp)
            out.append((fp, "\n".join(added)[:4000]))
    return out


def patch_text(args: dict) -> str:
    cmd = first(args, "command", "patch", "input", default="")
    if isinstance(cmd, (list, tuple)):
        return next((str(x) for x in cmd if "*** Begin Patch" in str(x)), command_text(cmd))
    return str(cmd)


class Codex(Adapter):
    name = "codex"
    EVENTS = {"PreToolUse": "pre", "PostToolUse": "post", "UserPromptSubmit": "prompt", "SessionStart": "session",
              "Stop": "stop"}

    def classify(self, name: str) -> str:
        return "patch" if name == "apply_patch" else super().classify(name)

    def pre_tool_calls(self, p: dict) -> list:
        name, args = self.tool(p)
        text = patch_text(args) if name in ("apply_patch", "Bash", "shell") else ""
        if name == "apply_patch" or (text.lstrip().startswith(("apply_patch", "*** Begin Patch"))
                                     and "*** Begin Patch" in text):
            # an apply_patch is an edit: one Edit per file it touches (Add File is a new file: Write)
            adds = {abs_path(m.group(2), self.cwd(p)) for m in map(PATCH_HEAD.match, text.splitlines())
                    if m and m.group(1) == "Add"}
            return [{"hook_event_name": "PreToolUse", "tool_name": "Write" if fp in adds else "Edit",
                     "tool_input": {"file_path": fp, "content": added}}
                    for fp, added in parse_patch(text, self.cwd(p)) if not re.search(r"journal[^\\/]*\.md$", fp, re.I)]
        return super().pre_tool_calls(p)

    def out_pre(self, deny: str, ctx: str, sid: str):
        if deny:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": deny}}
        if ctx:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ctx}}
        return None

    def out_post(self, ctx: str, sid: str):
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}} if ctx else None

    def out_prompt(self, ctx: str, sid: str):
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}} if ctx else None

    def out_session(self, ctx: str, sid: str):
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}} if ctx else None

    def out_stop(self, reason: str, sid: str):
        return {"decision": "block", "reason": reason} if reason else None


ADAPTER = Codex()
