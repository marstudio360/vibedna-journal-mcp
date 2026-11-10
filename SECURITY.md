# Journals DNA: Security Posture

What Journals DNA touches, where data goes, and how to report a vulnerability.

## What it is

A **local MCP server** (`server.py`, a Python stdio process started by your MCP client) plus, in Claude Code, the
**journals mod** (a plugin whose hooks run `quick_hook.py` before and after tool calls). The BETA adapters for
Codex, GitHub Copilot and Cursor (`mod-adapters/`) run the same `quick_hook.py` from each app's own hooks file, which
you copy in yourself. It opens no network listener
unless you set `JOURNAL_TRANSPORT=http`, which is meant only for cloud hosting, or set up the optional search by
meaning, whose service listens on `127.0.0.1` only.

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
  in `JOURNAL_INCLUDE_VAULT_PATH` (names, categories and field names, never values), the rule files in
  `JOURNAL_RULE_FILES`, the server list in `~/.journal/box_hosts.txt` or `JOURNAL_BOX_HOSTS`, the paid-run list in
  `~/.journal/paid_patterns.txt`, your own yes list in `~/.journal/yes_patterns.txt`, and the repos in
  `JOURNAL_COMPILE_CORPUS` (read with `git grep` when your rules are compiled).
- With `JOURNAL_AI_CHECKS` on: `~/.ssh/config`, only the Host blocks that name a host or address the command reaches.
- The default rules pack (on by default) reads only the command or text about to run or be written, and asks the
  file system whether a `.env` or key file it would overwrite exists. When a git rule matches, it runs `git status
  --porcelain`, `git clean -n` or `git rev-parse` locally (3 seconds at most) to see whether there is work to lose
  or which branch is checked out. Nothing leaves your machine.

## What it writes

- Journal files you ask it to create or update (`journal_create`, `journal_append`, `journal_update_section`,
  `journal_decision_add`, `journal_capability_add`). Appends use an atomic write.
- `~/.journal/` (index, the mod's per-session state, `quick_errors.log` when the hook fails, the judge's cache and
  cost log, the compiled rule tests, the mod's event log, the flood guard's call count, the checks' logs; with an app
  adapter, `adapter_queue/` for the briefs that wait for the next tool call).
- `~/journal-outbox/` (or `JOURNAL_OUTBOX`), only when an append targets a read-only journal.
- `~/.claude/CLAUDE.md` or `./CLAUDE.md`, only with `journal_install_rule(..., confirm=True)`; `~/.claude/settings.json`,
  only with `journal_install_build_check(confirm=True)` or `install_mod.py` (two env keys, backup first).
- `_obsidian/` and `.obsidian/` in a folder you name, only with `obsidian.py vault --apply`; a properties block at the
  top of journals, only with `obsidian.py add-frontmatter --apply`.
- `~/.journal/library/` (or the folder you pass), only when you call `journal_get` for a journal you own.

## Network

The journaling core, the quick map and the mod make no network calls of their own. Two optional parts talk to a
service, only when you set them up:
- The search by meaning (after `meaning.py build`) asks its own service on `127.0.0.1` (port 47311 by default), or
  the team embedding service you name in `JOURNAL_MEANING_URL`; it sends the question and the journal entries' text.
- The judge (`JOURNAL_JUDGE=on`) runs your own `claude` command, logged in on your plan, with the question and the
  candidate lines (journal lines, your rules, the reply, and with `JOURNAL_AI_CHECKS` on the command or text being
  checked). That command talks to its own service like any Claude Code session.

 The mod runs `git diff` locally, only after a
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
can be turned off alone (`JOURNAL_TOOLS_MAP=0`, `JOURNAL_LIVECOPY=0`, `JOURNAL_RULEDUPES=0`, `JOURNAL_ACTION_CHECK=off`,
`JOURNAL_DEFAULT_RULES=off` or `JOURNAL_DEFAULT_RULES_OFF=<rule,rule>`).
Background processes, all optional: the meaning service (one copy at most, started on the first search after
`meaning.py build`; `JOURNAL_MEANING_OFF=1` keeps it off), and with the judge on the rule compiler (one run at a time,
at the lowest priority, only after a rule line changed; `JOURNAL_AUTOCOMPILE=off` keeps it off) and the command check's program classifier (with `JOURNAL_AI_CHECKS` on). Nothing starts
at login.

## Reporting a vulnerability

Send a private email to **admin@vibedna.ai** with a description, steps to reproduce and your assessment of impact.
We credit reporters in the release notes unless you ask us not to.

## Out of scope

- Errors that fail closed (the server returning an error, the hook staying silent)
- Performance on very large libraries
- Pointing `JOURNAL_ROOTS` at a sensitive system folder: the tool trusts the roots you give it

Vibedna, 2026
