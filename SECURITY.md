# Journal MCP: Security Posture

This document describes what Journal MCP touches, where data goes, and how to report a vulnerability.

## What it is

Journal is a **local MCP server**. It runs as a Python stdio process started by your MCP client (Claude Code, Cursor, Claude Desktop). It opens no network listener unless you set `JOURNAL_TRANSPORT=http`, which is meant only for cloud hosting.

## What it reads

- The index scan (`journal_index_refresh`) only looks at files whose name matches `*JOURNAL*.md` (or `journal.md`) inside the folders in `JOURNAL_ROOTS` (default: `~/Desktop` and `~/Documents`).
- The journal tools accept a short name **or a full path**. Given a full path to an existing file, `journal_read` and the other journal tools operate on that file. The server trusts the path your AI client passes; it does not restrict full paths to the configured roots.
- `~/.journal/` (index DB, optional `config.toml`, optional `auth.json`).

## What it writes

- Journal files you ask it to create or update (`journal_create`, `journal_append`, `journal_update_section`).
- `~/.journal/index.sqlite` (the local search index).
- `~/.claude/CLAUDE.md`, only when you call `journal_install_rule(..., confirm=True)`. Without `confirm=True` it returns a preview.
- `~/.journal/library/` (or the folder you pass), only when you call `journal_get` for a journal you own.
- `~/.journal/auth.json`, only when you call `journal_pair`.

## Network

The journaling core (read, append, search, index, sections, handoff) makes no network calls. These tools do, and only when called:

| Tool | Goes to | Sends |
|---|---|---|
| `check_for_update` | `https://vibedna.ai/api/mcp/latest` | The product slug |
| `journal_market` | vibedna.ai | The search query |
| `journal_pair`, `journal_get`, `journal_library` | vibedna.ai | The pairing token from `~/.journal/auth.json` and the journal slug |
| `journal_backup_to_drive` | Your own rclone remote | Your journal files (the server shells out to `rclone copy`) |

`VIBEDNA_SITE` overrides the vibedna.ai address. There is no telemetry and no analytics.

## Dependencies

One PyPI package: [`mcp`](https://pypi.org/project/mcp/), the official MCP Python SDK. No native extensions, no compiled binaries, no fetch-on-install scripts.

## Turning it off

Remove the `journal` entry from your MCP client config and restart the client. There is no daemon and no auto-start.

## Reporting a vulnerability

Send a private email to **admin@vibedna.ai** with:

- A description of the issue
- Steps to reproduce
- Your assessment of impact

We credit reporters in the release notes unless you ask us not to.

## Out of scope

- Crashes or errors that fail closed (the MCP returning an error to the client)
- Performance on very large libraries
- Anything that requires you to point `JOURNAL_ROOTS` at a sensitive system folder: Journal trusts the roots you give it

VibeDNA, 2026
