"""GitHub Copilot (VS Code agent with the Copilot harness, Copilot CLI, Copilot app, cloud coding agent).

Contract per https://docs.github.com/en/copilot/reference/hooks-reference and
https://code.visualstudio.com/docs/agent-customization/hooks (both read 2026-11-10):
- PascalCase event keys (PreToolUse, PostToolUse, UserPromptSubmit, SessionStart, Stop) give the snake_case payload
  (tool_name, tool_input, session_id); camelCase keys give toolName, toolArgs, sessionId. Both are read here.
- Output is flat, no hookSpecificOutput: preToolUse {permissionDecision, permissionDecisionReason}; postToolUse and
  sessionStart {additionalContext}; agentStop / Stop {decision: "block", reason}; userPromptSubmitted output is dropped.
- A non-zero exit other than 2 on preToolUse DENIES (fail closed): run.py always exits 0 and prints valid JSON.

Copilot has no pre-tool context, so a brief or note from the core rides on the postToolUse of the same call (the
model reads it right after the tool output, same turn), and the prompt-time map waits for the first tool call of
the turn. With JOURNAL_GATE_COPILOT=deny a delivered brief rides on a one-time deny instead (the core already marked
it read, so the retry passes: it cannot deadlock).
"""
from adapters.base import BRIEF_SIG, Adapter, first, gate_mode


class Copilot(Adapter):
    name = "copilot"
    EMPTY = "{}"
    EVENTS = {"PreToolUse": "pre", "preToolUse": "pre", "PostToolUse": "post", "postToolUse": "post",
              "UserPromptSubmit": "prompt", "userPromptSubmitted": "prompt", "SessionStart": "session",
              "sessionStart": "session", "Stop": "stop", "agentStop": "stop"}

    def tool_result(self, p: dict):
        return first(p, "tool_response", "tool_result", "toolResult")

    def out_pre(self, deny: str, ctx: str, sid: str):
        if deny:
            return {"permissionDecision": "deny", "permissionDecisionReason": deny}
        if ctx and gate_mode(self.name) == "deny" and BRIEF_SIG.search(ctx):
            return {"permissionDecision": "deny", "permissionDecisionReason":
                    ctx + "\n\nThis journal brief counts as read: run the same call again and it goes through."}
        self.queue_put(sid, ctx)
        return None

    def out_post(self, ctx: str, sid: str):
        text = "\n\n".join(x for x in (self.queue_take(sid), ctx) if x)
        return {"additionalContext": text} if text else None

    def out_prompt(self, ctx: str, sid: str):
        self.queue_put(sid, ctx)   # the prompt hook's output is dropped by Copilot; the map rides on the next tool call
        return None

    def out_session(self, ctx: str, sid: str):
        return {"additionalContext": ctx} if ctx else None

    def out_stop(self, reason: str, sid: str):
        return {"decision": "block", "reason": reason} if reason else None


ADAPTER = Copilot()
