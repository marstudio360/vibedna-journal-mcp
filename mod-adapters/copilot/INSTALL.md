# Journals DNA mod for GitHub Copilot (VS Code agent, Copilot CLI, Copilot app, cloud agent)

**BETA.** Tested with recorded GitHub Copilot hook payloads only, not yet in a live session. In this app the journals gate only delivers the brief (note mode, the default); the other stops (the default rules pack, your exact rule tests, the paid-run guard, the server flood guard) stay stops.

What it does: when the Copilot agent touches a project (edits a file, runs a command, reads code), that project's journal brief (Handoff, current state, pending, decisions, newest entries) reaches the agent. On session start it gets a short "read the journals first" rule. Same core as the Claude Code mod (`quick_hook.py`), different plug.

How it reaches the agent, because Copilot hooks cannot add text before a tool runs:
- The brief rides on the `PostToolUse` of that same call: the agent reads it right after the tool output, in the same turn.
- The map of what you named in your message waits for the first tool call of the turn (Copilot drops the output of the prompt hook).
- Stops that are not the journals gate (the default rules pack, a paid run without your yes, a flood of server logins, your exact rule tests) are real denies with the reason shown to the agent.

You need: the journal tool folder (the one with `quick_hook.py`, called `<JOURNAL_MCP_DIR>` below) and Python 3.10+ (`<PYTHON>`).

## Install

- **One repository (also needed for the cloud agent):** copy `.github/hooks/journals.json` from this folder into the repository at `.github/hooks/journals.json`.
- **All your projects (VS Code, CLI, app):** copy the same file to `~/.copilot/hooks/journals.json`.

Then replace every `<PYTHON>` with the full path of your Python and every `<JOURNAL_MCP_DIR>` with the full path of the journal tool folder (forward slashes). The file has a `bash` and a `powershell` command per event; Copilot runs the one for your system. In VS Code, select Copilot as the session target (hooks are in Preview there).

The cloud agent reads only `.github/hooks/*.json` from the repository and runs in its own machine: the journal tool folder and Python must exist there (install them in your Copilot setup steps), and the paths in the file must be the paths on that machine.

## Check it works

From a terminal (bash):

```
echo '{"hook_event_name":"SessionStart","session_id":"smoke","cwd":".","source":"new"}' | <PYTHON> <JOURNAL_MCP_DIR>/quick_hook.py --app copilot --event SessionStart
```

PowerShell: `'{"hook_event_name":"SessionStart","session_id":"smoke","cwd":".","source":"new"}' | & "<PYTHON>" "<JOURNAL_MCP_DIR>/quick_hook.py" --app copilot --event SessionStart`

It prints one JSON line with `"additionalContext"` starting with `JOURNALS (one brain)`.

In Copilot: open a project whose folder has a `<NAME>_JOURNAL.md` with a `## Handoff` section. Ask the agent to show the first lines of a file inside that project. Then ask: "did a hook give you a journal brief after that tool ran? Quote its first line." It should quote `JOURNAL BRIEF for project ...`. Each brief is also logged as a `"kind": "brief"` line in `~/.journal/mod_events.jsonl` (or `$JOURNAL_HOME`).

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `JOURNAL_GATE_COPILOT` | `note` | `note`: the journals gate never stops the agent; the brief rides after the tool. `deny`: the first touch of a piece is stopped once with the brief as the reason (the retry goes through), and a gate with no brief to give stays stopped until the journal is read. Keep `note` until you have seen journal reads recorded in your setup. |
| `JOURNAL_HOME` | `~/.journal` | Where the journal tool keeps its index and per-session state (the waiting briefs live in `adapter_queue/`). |
| `JOURNAL_AI_CHECKS` | `off` | `risky` or `all`: an AI judge reads commands and writes before they run (costs tokens). |

## Remove

Delete `.github/hooks/journals.json` (or `~/.copilot/hooks/journals.json`). Optional: delete `~/.journal/adapter_queue/`.
