# Journals DNA mod for Codex (CLI and desktop app)

**BETA.** Tested live in Codex: the hooks run and the model follows the brief. In this app the journals gate only delivers the brief (note mode, the default); the other stops (the default rules pack, your exact rule tests, the paid-run guard, the server flood guard) stay stops.

What it does: before Codex edits a file (apply_patch) or runs a command, the journal of that project is put in front of it (its Handoff, current state, pending, decisions, newest entries). On each prompt it gets the journal map of what you named; after a command it gets what you already ruled on about names in the output. Same core as the Claude Code mod (`quick_hook.py`), different plug.

You need: the journal tool folder (the one with `quick_hook.py`, called `<JOURNAL_MCP_DIR>` below) and a Python 3.10+ (`<PYTHON>`). The journal MCP server itself is added to Codex the usual way; the hooks work without it, but journal reads only count when the AI uses the journal tools or reads a `*_JOURNAL.md`.

## Install

1. Copy `hooks.json` from this folder to `~/.codex/hooks.json` (all your projects) or `<repo>/.codex/hooks.json` (one trusted project). If you already have a hooks file, merge the five events into it.
2. Replace every `<PYTHON>` with the full path of your Python and every `<JOURNAL_MCP_DIR>` with the full path of the journal tool folder. Use forward slashes. If a path has spaces, wrap each path in double quotes (`\"C:/Program Files/Python312/python.exe\"` inside the JSON string).
3. Trust the new hooks: `/hooks` in the CLI, or Settings, Hooks in the desktop app. Codex does not run a new or changed hook until you trust it.

## Check it works

From a terminal (bash):

```
echo '{"hook_event_name":"SessionStart","session_id":"smoke","source":"startup"}' | <PYTHON> <JOURNAL_MCP_DIR>/quick_hook.py --app codex
```

PowerShell: `'{"hook_event_name":"SessionStart","session_id":"smoke","source":"startup"}' | & "<PYTHON>" "<JOURNAL_MCP_DIR>/quick_hook.py" --app codex`

It prints one JSON line with `"hookEventName": "SessionStart"` and text starting with `JOURNALS (one brain)`.

In Codex: open a project whose folder has a `<NAME>_JOURNAL.md` with a `## Handoff` section. Ask Codex to show the first lines of a file inside that project with a shell command. Then ask it: "did a hook give you a journal brief? Quote its first line." It should quote `JOURNAL BRIEF for project ...`. Each brief is also logged as a `"kind": "brief"` line in `~/.journal/mod_events.jsonl` (or `$JOURNAL_HOME`).

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `JOURNAL_GATE_CODEX` | `note` | `note`: the journals gate only delivers the brief or warns, it never stops Codex. `deny`: the journals gate works as in Claude Code (the brief comes with the first touch; a touch with no brief to give is stopped until the journal was read). Keep `note` until you have seen journal reads recorded in your setup. |
| `JOURNAL_HOME` | `~/.journal` | Where the journal tool keeps its index and per-session state. |
| `JOURNAL_REPLY_GATE` | off | `on`: the Stop hook checks the finished reply against your journals and can send it back once (uses the judge model, costs tokens). |
| `JOURNAL_AI_CHECKS` | `off` | `risky` or `all`: an AI judge reads commands and writes before they run (costs tokens). |

Stops that are not the journals gate (the default rules pack, a paid run without your yes, a flood of server logins, your exact rule tests) stay stops in both gate modes.

## Remove

Delete the five `quick_hook.py --app codex` entries from `~/.codex/hooks.json` (or delete the file if it only had these), then trust the change in `/hooks`. Optional: delete `~/.journal/adapter_queue/`.
