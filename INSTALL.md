# Install Journals DNA 1.2.0

**Journals DNA: your AI cannot skip your journal.** This file is self-contained: you can follow it yourself, or
open Claude Code in the unzipped folder and say "install this, following INSTALL.md". The AI should show you each
command before it runs it and ask before step 4.

## What you need
- Python 3.10 or newer (`python3 --version`; on Windows `py --version`).
- Claude Code, for the journals mod (the stops and the map before every change). Any other MCP client can still run
  the journal server on its own (step 6).
- About 1 MB of disk. No account, no API key, no network for the journals themselves.

Paths below use `<folder>` for the folder you unzipped (the one with `server.py` in it). On Windows, every
`.venv/bin/` becomes `.venv\Scripts\`, and `python3` becomes `py`.

## 1. Make a private Python for the tool
From `<folder>`:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
This pins the MCP library to a version with FastMCP (`mcp>=1.28.1,<2`). A global `pip install` is refused on many
systems; the `.venv` avoids that and keeps your other Python projects untouched.

## 2. Tell it where your journals live (optional)
By default it scans `~/Desktop` and `~/Documents` for files named `*JOURNAL*.md`. To scan other folders, set
`JOURNAL_ROOTS` (folders separated by `;`) or add them later with the `journal_config_add_root` tool, which writes
`~/.journal/config.toml`.

## 3. Check the install before changing anything
```bash
.venv/bin/python install_mod.py --dry-run
```
It prints every change and writes nothing:
- `claude mcp add journal -s user -- <folder>/.venv/bin/python <folder>/server.py` (the journal server, user scope)
- `claude plugin marketplace add <folder>/mod` and `claude plugin install journals@journals-dna` (the journals mod)
- two keys in the `env` block of `~/.claude/settings.json`: `JOURNAL_MCP_DIR` (this folder) and `JOURNAL_PYTHON`
  (the `.venv` Python), so the mod can find the tool.

## 4. Install
```bash
.venv/bin/python install_mod.py
```
It asks once, writes a timestamped backup of `~/.claude/settings.json` first, and changes nothing else in it.
Running it again changes nothing. If the `claude` command is not on your PATH, it still writes the two keys and
prints the three `claude` commands for you to run where Claude Code works.

Open a **new** Claude Code session. Check:
- `claude mcp list` shows `journal` as connected;
- `claude plugin list` shows `journals@journals-dna` enabled;
- ask your AI: `journal_quick("<a word from your project>")`.

## 5. Try it on the demo journal
```bash
mkdir -p demo && cp examples/DEMO_PROJECT.md demo/DEMO_JOURNAL.md
JOURNAL_ROOTS="$PWD/demo" .venv/bin/python server.py --quick checkout
```
(Windows PowerShell: `mkdir demo; copy examples\DEMO_PROJECT.md demo\DEMO_JOURNAL.md; $env:JOURNAL_ROOTS="$PWD\demo"; .venv\Scripts\python server.py --quick checkout`.)

You get the Checkout row of the Brain map (who is on it, which journal to read first), the decision about prices,
what already exists, the latest entry and the pending tax line. Then add a `## Brain map` table to one of your own
journals (see `BRAIN_MAP_TEMPLATE.md`): the mod stops the first edit of a file its keys name until that journal
was read in the session.

## 6. Other MCP clients (no mod)
Add the server to your client's MCP config, with the `.venv` Python by its full path:
```json
{ "mcpServers": { "journal": { "command": "<folder>/.venv/bin/python", "args": ["<folder>/server.py"] } } }
```
The tools work the same; the stops before edits are a Claude Code feature.

## Open your journals in Obsidian
One command builds a map of every journal under a folder:
```bash
.venv/bin/python obsidian.py vault --root "<your projects folder>"            # dry run
.venv/bin/python obsidian.py vault --root "<your projects folder>" --apply    # write
```
It writes, in that folder:
- `_obsidian/START HERE.md`: how an AI should read the vault, a table of every journal with links to its Current
  state and Handoff, and the newest entries;
- `_obsidian/Journals.base`: a table view of all journals (by last update, stale over 14 days, biggest);
- `_obsidian/Journals map.canvas`: the journals grouped by folder, with lines where one journal names another;
- `.obsidian/app.json` and `.obsidian/core-plugins.json` (code folders hidden, Bases and Canvas on). It never
  writes your workspace layout.

Open that folder as a vault in Obsidian. Run the command again whenever you want the map up to date.

New journals made with `journal_create` are born with Obsidian properties (type, project, status, tags, aliases,
updated, entries), and appends keep them current. Older journals can get the same block with
`.venv/bin/python obsidian.py add-frontmatter --root "<folder>"` (dry run; add `--apply` to write). Leave it off for
journals that another tool syncs or appends to, because 8 new lines at the top shift every `FILE.md:line`
reference.

## Optional settings (environment variables)
| Setting | What it does |
|---|---|
| `JOURNAL_ROOTS` | Folders to scan, separated by `;` |
| `JOURNAL_HOME` | Where the index and session state live (default `~/.journal`) |
| `JOURNAL_RESCAN_MINUTES` | How often the index looks for new journal files in the roots (default 10; `journal_index_refresh` does it at once) |
| `JOURNAL_BRAND_NAMES` | Your own brand or company names, separated by `,`. A reply naming them is read as context, never as a pending thing |
| `JOURNAL_INCLUDE_VAULT_PATH` | A names-only JSON index of your secrets vault (`{"entries": [{"name", "category", "fields"}]}`, never values). The map then shows which key exists for a word. Off unless set |
| `JOURNAL_TOOL_DOCS` | Extra docs that list your tools (globs separated by `;`), for "a tool already does this" |
| `JOURNAL_EXTRA_DOCS` | Extra markdown docs searched next to the journals |
| `JOURNAL_ALIASES` | Extra synonym groups: `a,b,c;d,e` |
| `JOURNAL_OUTBOX` | Where entries for a read-only journal are queued (default `~/journal-outbox`) |
| `JOURNAL_TOOLS_MAP=0`, `JOURNAL_LIVECOPY=0`, `JOURNAL_RULEDUPES=0` | Turn off one check of the mod |

## Rules your AI follows
Write rules as dated lines in `RULES_JOURNAL.md` (or `OWNER_SAID_JOURNAL.md`, or any `*_RULES_JOURNAL.md`); see
`RULES_TEMPLATE.md`. Each line starts with `- 2026-` and says the rule and its reason.

## Run the tests (optional)
```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```
Everything runs in temporary folders; your journals and `~/.journal` are not touched.

## Undo
| What | How |
|---|---|
| Server, mod and settings keys | `.venv/bin/python install_mod.py --uninstall` (`--dry-run` first to see it) |
| The index and session state | delete `~/.journal` |
| The Obsidian map | delete `_obsidian/` and `.obsidian/` in that folder |
| Everything else | delete `<folder>` |
Your journals are never changed by installing or uninstalling.

## If something is off
- "mcp package missing or too new": run step 1 again inside `<folder>`.
- The mod shows nothing: open a new session; check `JOURNAL_MCP_DIR` in `~/.claude/settings.json` points at
  `<folder>`; errors of the hook go to `~/.journal/quick_errors.log`.
- A stop you think is wrong: read the journal it names (that opens it), or turn that one check off with the
  setting above.
