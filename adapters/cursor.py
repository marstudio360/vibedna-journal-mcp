"""Cursor (IDE agent, CLI, cloud agents), native .cursor/hooks.json.

Contract per https://cursor.com/docs/hooks (read 2026-11-10) and the staff answer on preToolUse additional_context
(https://forum.cursor.com/t/pretooluse-additional-context-works-but-isnt-documented-is-it-officially-supported/166969):
- Common input: conversation_id, generation_id, hook_event_name, workspace_roots; preToolUse adds tool_name (Shell,
  Read, Write, Grep, Delete, Task, MCP:<tool>), tool_input, tool_use_id, cwd; postToolUse adds tool_output (a JSON
  string).
- Output: preToolUse {permission: "deny", agent_message, user_message} or {additional_context}; postToolUse and
  sessionStart {additional_context}; beforeSubmitPrompt {continue} only (no context); stop {followup_message}.
- Invalid JSON on a permission hook blocks the call: run.py always prints valid JSON ("{}" for nothing).

beforeSubmitPrompt cannot inject, so the prompt-time map waits in the queue for the first preToolUse of the turn.
stop carries no reply text, so afterAgentResponse keeps it for the stop check.
"""
from adapters.base import Adapter, first


class Cursor(Adapter):
    name = "cursor"
    EMPTY = "{}"
    EVENTS = {"preToolUse": "pre", "postToolUse": "post", "beforeSubmitPrompt": "prompt", "sessionStart": "session",
              "stop": "stop", "afterAgentResponse": "reply"}

    def session_id(self, p: dict) -> str:
        return str(first(p, "conversation_id", "session_id", default="cursor-nosession"))

    def tool_result(self, p: dict):
        return first(p, "tool_output", "tool_response")

    def out_pre(self, deny: str, ctx: str, sid: str):
        if deny:
            return {"permission": "deny", "agent_message": deny,
                    "user_message": "Journals DNA: reading your notes on this first."}
        text = "\n\n".join(x for x in (self.queue_take(sid), ctx) if x)
        return {"additional_context": text} if text else None

    def out_post(self, ctx: str, sid: str):
        return {"additional_context": ctx} if ctx else None

    def out_prompt(self, ctx: str, sid: str):
        self.queue_put(sid, ctx)
        return {"continue": True}

    def out_session(self, ctx: str, sid: str):
        return {"additional_context": ctx} if ctx else None

    def on_reply(self, p: dict, sid: str):
        self.state_set(sid, "reply", str(p.get("text") or "")[:8000])
        return None

    def stop_reply(self, p: dict) -> str:
        return str(self.state_get(self.session_id(p), "reply", "") or "") if str(p.get("status") or "completed") \
            == "completed" else ""

    def stop_active(self, p: dict) -> bool:
        return int(p.get("loop_count") or 0) > 0

    def out_stop(self, reason: str, sid: str):
        return {"followup_message": reason} if reason else None


ADAPTER = Cursor()
