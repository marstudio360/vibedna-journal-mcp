# VibeDNA Journal MCP

One journal file per project that your AI reads at session start and updates as it works.

Journal gives every project one plain markdown file (`*_JOURNAL.md`). Your AI reads it when a session starts and appends to it as work ships: decisions with their reasons, bugs with root cause and fix, current state, roadmap, and a handoff note for the next session. Ranked full-text search finds an entry across every project's journal at once. One optional tool adds a rule to your `CLAUDE.md` so Claude Code keeps the habit without being asked.

- Runs locally over stdio. Python 3.10+ and the `mcp` package.
- The journaling core makes no network calls. Your journals stay on your disk.
- Optional marketplace tools browse and download journals from vibedna.ai, only when you call them.

Homepage: https://vibedna.ai/store/journal

## Tools (25)

**Catch up on a project**

| Tool | What it does |
|---|---|
| `journal_handoff_brief(name)` | Short catch-up: header plus the latest entries |
| `journal_read(name, max_kb)` | Full journal contents |
| `journal_read_section(name, section)` | One section, e.g. `Current state` or `Handoff for next session` |
| `journal_list_sections(name)` | The H2 sections of a journal |
| `journal_list(project, last_days)` | List the journals in the index |

**Log work as it ships**

| Tool | What it does |
|---|---|
| `journal_append(name, entry, tag)` | Timestamped entry |
| `journal_update_section(name, section, new_content, mode)` | Replace, append or prepend a section |
| `journal_create(name, project_dir, body)` | New journal with the standard sections |

**Search**

| Tool | What it does |
|---|---|
| `journal_search(query, project)` | Ranked full-text search (SQLite FTS5) across all journals, with snippets |
| `journal_recent_changes(last_hours)` | Journals updated lately |
| `journal_stats()` | Totals, biggest and freshest journals |
| `journal_browse(domain, tier, kind, tag)` | Browse the local library by metadata |
| `journal_market_index(kind)` | Local feed of journals of one kind, with metadata |
| `journal_overlap_check(name)` | Find journals that overlap with this one |

**Setup**

| Tool | What it does |
|---|---|
| `journal_index_refresh()` | Rescan the roots for journal files |
| `journal_config_add_root(path)` | Add a folder to scan |
| `journal_get_claude_rule()` | The recommended `CLAUDE.md` rule text |
| `journal_install_rule(scope, confirm)` | Install that rule (preview unless `confirm=True`) |
| `journal_backup_to_drive(name, remote, remote_folder)` | Copy journals to your own rclone remote (optional) |
| `check_for_update()` | Compare this copy with the published version |
| `vibedna_info()` | Product metadata |

**Marketplace (optional, reaches vibedna.ai)**

| Tool | What it does |
|---|---|
| `journal_market(query, domain)` | Browse the VibeDNA journal shelf |
| `journal_pair(token)` | Link this install to a vibedna.ai account |
| `journal_get(slug)` | Download a journal you own, or get a checkout link for one you don't |
| `journal_library()` | List the journals you own |

## Install

```bash
git clone https://github.com/marstudio360/vibedna-journal-mcp
cd vibedna-journal-mcp
pip install -r requirements.txt
```

`JOURNAL_ROOTS` is the list of folders to scan for journal files, separated by `;`. Without it, Journal scans `~/Desktop` and `~/Documents`.

### Claude Code

```bash
claude mcp add journal --scope user -e JOURNAL_ROOTS="/path/to/your/projects" -- python /absolute/path/to/vibedna-journal-mcp/server.py
```

Or in a project's `.mcp.json`:

```json
{
  "mcpServers": {
    "journal": {
      "command": "python",
      "args": ["/absolute/path/to/vibedna-journal-mcp/server.py"],
      "env": { "JOURNAL_ROOTS": "/path/to/your/projects" }
    }
  }
}
```

Then ask Claude: "Install the journal CLAUDE.md rule globally." That is the step that makes it read and write the journals on its own.

### Cursor

Add the same `mcpServers` block to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project).

### Claude Desktop

Add the same `mcpServers` block to `claude_desktop_config.json` (Settings > Developer > Edit Config), then restart Claude Desktop.

[INSTALL.md](./INSTALL.md) is a step-by-step guide written so you can paste it into an AI chat and let the AI do the install.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `JOURNAL_ROOTS` | `~/Desktop;~/Documents` | Folders to scan for `*JOURNAL*.md` files |
| `JOURNAL_HOME` | `~/.journal` | Where the search index and optional config live |
| `JOURNAL_TRANSPORT` | `stdio` | `http` serves streamable HTTP on `PORT`, for cloud hosting only |

## Journal scaffold

`journal_create` starts every journal with these sections:

```
## Vision / Why this exists
## Current state
## Roadmap
## Decisions log
## Incidents
## Handoff for next session
## Recent entries
```

## Security

See [SECURITY.md](./SECURITY.md) for what the server reads, writes and sends.

## License

MIT, see [LICENSE](./LICENSE). Copyright (c) 2026 VibeDNA.

Support: admin@vibedna.ai
