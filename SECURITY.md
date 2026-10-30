# Journals DNA: Security Posture

What Journals DNA touches, where data goes, and how to report a vulnerability.

## What it is

A **local MCP server** (`server.py`, a Python stdio process started by your MCP client) plus, in Claude Code, the
**journals mod** (a plugin whose hooks run `quick_hook.py` before and after tool calls). It opens no network listener
unless you set `JOURNAL_TRANSPORT=http`, which is meant only for cloud hosting.

## What it reads

- Files whose name matches `*JOURNAL*.md` (or `journal.md`) inside the folders in `JOURNAL_ROOTS` (default:
  `~/Desktop` and `~/Documents`). Folders such as `node_modules`, `.git`, `venv`, `fixtures` and `-wt-` git worktrees
  are skipped, and so are files under a `public/` folder.
- The journal tools accept a short name or a full path. Given a full path to an existing journal file, they operate
  on that file; the server trusts the path your AI client passes.
- `~/.journal/` (index, session state of the mod, optional `config.toml`, optional `auth.json`).
- What a tool call is about to do (the file path, the command and its description, the first 4 KB of written
  content, an agent brief) and the text a shell command returned, to build the map. These stay on your machine.
- Optional, only when you set them: the docs in `JOURNAL_TOOL_DOCS` / `JOURNAL_EXTRA_DOCS`, the names-only vault index
  in `JOURNAL_INCLUDE_VAULT_PATH` (names, categories and field names, never values).

## What it writes

- Journal files you ask it to create or update (`journal_create`, `journal_append`, `journal_update_section`,
  `journal_decision_add`, `journal_capability_add`). Appends use an atomic write.
- `~/.journal/` (index, the mod's per-session state, `quick_errors.log` when the hook fails).
- `~/journal-outbox/` (or `JOURNAL_OUTBOX`), only when an append targets a read-only journal.
- `~/.claude/CLAUDE.md` or `./CLAUDE.md`, only with `journal_install_rule(..., confirm=True)`; `~/.claude/settings.json`,
  only with `journal_install_build_check(confirm=True)` or `install_mod.py` (two env keys, backup first).
- `_obsidian/` and `.obsidian/` in a folder you name, only with `obsidian.py vault --apply`; a properties block at the
  top of journals, only with `obsidian.py add-frontmatter --apply`.
- `~/.journal/library/` (or the folder you pass), only when you call `journal_get` for a journal you own.

## Network

The journaling core, the quick map and the mod make no network calls. The mod runs `git diff` locally, only after a
`git status` or `git diff` command, to say when files changed only in line endings. These tools go out, and only
when called:

| Tool | Goes to | Sends |
|---|---|---|
| `check_for_update` | `https://vibedna.ai/api/mcp/latest` | The product slug |
| `journal_market` | vibedna.ai | Nothing but the request (the filter runs locally) |
| `journal_pair`, `journal_get`, `journal_library` | vibedna.ai | The pairing token from `~/.journal/auth.json` and the journal slug |
| `journal_verify` | The URLs written in your journal's `check: url ...` lines | A plain GET |
| `journal_audit(check_urls=True)` | The URLs found in that journal | A plain request per URL |
| `journal_backup_to_drive` | Your own rclone remote | Your journal files (the server runs `rclone copy`) |

`VIBEDNA_SITE` overrides the vibedna.ai address. There is no telemetry and no analytics.

## Dependencies

One PyPI package: [`mcp`](https://pypi.org/project/mcp/), the official MCP Python SDK, pinned in `requirements.txt`.
The mod is TypeScript run by Claude Code itself. No native extensions, no fetch-on-install scripts.

## Turning it off

`install_mod.py --uninstall` removes the server entry, the plugin and the two settings keys. Each check of the mod
can be turned off alone (`JOURNAL_TOOLS_MAP=0`, `JOURNAL_LIVECOPY=0`, `JOURNAL_RULEDUPES=0`). There is no daemon
and no auto-start.

## Reporting a vulnerability

Send a private email to **admin@vibedna.ai** with a description, steps to reproduce and your assessment of impact.
We credit reporters in the release notes unless you ask us not to.

## Out of scope

- Errors that fail closed (the server returning an error, the hook staying silent)
- Performance on very large libraries
- Pointing `JOURNAL_ROOTS` at a sensitive system folder: the tool trusts the roots you give it

Vibedna, 2026
