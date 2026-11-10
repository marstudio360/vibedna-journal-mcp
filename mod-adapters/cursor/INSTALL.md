# Journals DNA mod for Cursor (IDE agent, CLI, cloud agents)

**BETA.** Tested with recorded Cursor hook payloads only, not yet in a live session. In this app the journals gate only delivers the brief (note mode, the default); the other stops (the default rules pack, your exact rule tests, the paid-run guard, the server flood guard) stay stops.

What it does: before the Cursor agent edits a file, runs a command or reads code of a project, that project's journal brief (Handoff, current state, pending, decisions, newest entries) is added to what the agent sees. The map of what you named in your message arrives with the first tool call of the turn (Cursor's prompt hook cannot add context). After a command, it gets what you already ruled on about names in the output. Same core as the Claude Code mod (`quick_hook.py`), different plug.

You need: the journal tool folder (the one with `quick_hook.py`, called `<JOURNAL_MCP_DIR>` below) and Python 3.10+ (`<PYTHON>`).

Use this native file, not Cursor's import of Claude Code hooks: the import sends the reason to you instead of the agent, and maps the prompt hook to one that cannot add context. If you also have the Claude Code journals hooks in `~/.claude/settings.json`, turn off Settings, Third-Party Imports in Cursor so each call does not run twice.

## Install

1. Copy `.cursor/hooks.json` from this folder to `<project>/.cursor/hooks.json` (one project) or `~/.cursor/hooks.json` (all projects). If you already have one, merge the six events into it.
2. Replace every `<PYTHON>` with the full path of your Python and every `<JOURNAL_MCP_DIR>` with the full path of the journal tool folder (forward slashes).
   - Paths with spaces on macOS or Linux: wrap each in escaped double quotes (`\"/path with space/python3\"`).
   - Paths with spaces on Windows (the desktop app runs hooks through PowerShell): `"command": "& \"C:/Program Files/Python312/python.exe\" \"C:/tools/journal-mcp/quick_hook.py\" --app cursor"`.
3. Restart Cursor or reload the window.

## Check it works

From a terminal (bash):

```
echo '{"hook_event_name":"sessionStart","conversation_id":"smoke","session_id":"smoke"}' | <PYTHON> <JOURNAL_MCP_DIR>/quick_hook.py --app cursor
```

PowerShell: `'{"hook_event_name":"sessionStart","conversation_id":"smoke","session_id":"smoke"}' | & "<PYTHON>" "<JOURNAL_MCP_DIR>/quick_hook.py" --app cursor`

It prints one JSON line with `"additional_context"` starting with `JOURNALS (one brain)`.

In Cursor: open a project whose folder has a `<NAME>_JOURNAL.md` with a `## Handoff` section. Ask the agent to read a file inside that project, then ask: "did a hook give you a journal brief before that read? Quote its first line." It should quote `JOURNAL BRIEF for project ...`. Each brief is also logged as a `"kind": "brief"` line in `~/.journal/mod_events.jsonl` (or `$JOURNAL_HOME`).

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `JOURNAL_GATE_CURSOR` | `note` | `note`: the journals gate only delivers the brief or warns, it never stops the agent. `deny`: the journals gate works as in Claude Code (the brief comes with the first touch; a touch with no brief to give is stopped until the journal was read). Keep `note` until you have seen journal reads recorded in your setup. |
| `JOURNAL_HOME` | `~/.journal` | Where the journal tool keeps its index and per-session state (waiting maps and the last reply live in `adapter_queue/`). |
| `JOURNAL_REPLY_GATE` | off | `on`: the stop hook checks the finished reply against your journals and can send one follow-up (uses the judge model, costs tokens). |
| `JOURNAL_AI_CHECKS` | `off` | `risky` or `all`: an AI judge reads commands and writes before they run (costs tokens). |

Stops that are not the journals gate (the default rules pack, a paid run without your yes, a flood of server logins, your exact rule tests) stay stops in both gate modes.

## Remove

Delete the six `quick_hook.py --app cursor` entries from `.cursor/hooks.json` (or delete the file if it only had these) and reload Cursor. Optional: delete `~/.journal/adapter_queue/`.
