# Journals DNA

**Your AI cannot skip your journal.**

Journals DNA gives every project one markdown journal (`<PROJECT>_JOURNAL.md`) that your AI reads before it acts and
writes to while it works. The next session, or another AI, picks up exactly where the last one stopped, and you can
share your work with anyone by sending the journal.

It runs on your machine. Your journals stay where they are, in plain markdown.

## What it does, in plain words

- **Journals your AI must read.** In Claude Code, the journals mod stops the first edit of a piece of your project
  until the AI has really read that piece's journal. A plain retry does not get through; reading the journal does.
- **A map before every change.** Before your AI edits a file, runs a command or briefs an agent, it sees a short map
  of that thing: which journal talks about it, who is working on it now, what was already decided, what already
  exists, the latest entries and what is still pending.
- **It warns when your AI repeats itself.** When the AI is about to build its own way of doing a job a tool you
  already have does, it is shown that tool and stopped once. When a reply proposes something your journals already
  have a verdict on, or lists as pending something a journal says shipped, the AI is told so in its next turn.
- **It warns about stale status.** Lines that state something that changes (an account is active, a service is
  live, a balance) are marked "check live before repeating it" in the map. When the AI writes an entry that states
  such a status without saying how it was checked, the entry is still saved and the AI gets a warning.
- **Your rules, in your words.** Write your rules as dated lines in a rules journal (`RULES_JOURNAL.md` or any
  `*_RULES_JOURNAL.md`). When an action shares the words of a rule, the rule is shown and the action stops once.
- **Opens in Obsidian.** One command builds a map of all your journals for Obsidian: a START HERE page, a table view
  of every journal, and a canvas by folder. New journals are born with Obsidian properties.

## What is inside

| Part | What it is |
|---|---|
| `server.py` | The journal MCP server: 35 tools to read, search, write and keep journals (works with any MCP client) |
| `quickmap.py`, `quick_hook.py` | The quick map and the checks the mod runs (local, no network, no AI) |
| `toolmap.py`, `tool_concepts.json` | "A tool already does this": matches an action to the tools and flows your journals list |
| `livecopy.py`, `ruledupes.py` | Warnings for a command on the wrong copy of a deployed folder, and for a rule written twice |
| `obsidian.py` | Builds the Obsidian map of your journals |
| `mod/` | The journals mod, a Claude Code plugin |
| `install_mod.py` | One command that installs the server and the mod in Claude Code, and undoes it |
| `examples/DEMO_PROJECT.md` | A small journal to try everything on (copy it as `DEMO_JOURNAL.md` into a test folder) |
| `BRAIN_MAP_TEMPLATE.md`, `RULES_TEMPLATE.md` | Copy-paste starting points |

## Install

Full steps, written so you can hand the file to your AI: [INSTALL.md](INSTALL.md). Short version, from this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python install_mod.py --dry-run          # Windows: .venv\Scripts\python install_mod.py --dry-run
.venv/bin/python install_mod.py                    # Windows: .venv\Scripts\python install_mod.py
```

Then open a new Claude Code session and ask: `journal_quick("<a word from your project>")`.

Other MCP clients (Cursor and others) can run `server.py` as a normal MCP server; the mod and its stops are a
Claude Code feature.

## The tools

| Group | Tools |
|---|---|
| Start and read | `journal_handoff_brief`, `journal_read` (line ranges), `journal_read_section`, `journal_list_sections`, `journal_list` |
| Find | `journal_quick`, `journal_search`, `journal_before_build`, `journal_recent_changes`, `journal_map` |
| Write | `journal_append`, `journal_update_section`, `journal_create`, `journal_decision_add`, `journal_capability_add` |
| Keep it true | `journal_verify` (re-run `check:` lines), `journal_audit`, `journal_contradictions`, `journal_overlap_check`, `journal_stats` |
| Setup | `journal_how_to`, `journal_index_refresh`, `journal_config_add_root`, `journal_install_rule`, `journal_get_claude_rule`, `journal_install_build_check`, `journal_backup_to_drive` |
| Store | `journal_pair`, `journal_market`, `journal_get`, `journal_library`, `journal_browse`, `journal_market_index`, `check_for_update`, `vibedna_info` |

## Open your journals in Obsidian

```bash
.venv/bin/python obsidian.py vault --root "<your projects folder>"            # dry run: lists what it would write
.venv/bin/python obsidian.py vault --root "<your projects folder>" --apply    # writes it
```

It writes `_obsidian/START HERE.md`, `_obsidian/Journals.base`, `_obsidian/Journals map.canvas` and a minimal
`.obsidian/` config in that folder, then you open the folder as a vault in Obsidian. Details in INSTALL.md.

## Your data

Everything is local: the journals are your files, the index lives in `~/.journal`. The quick map and the mod make no
network calls. The store tools (`journal_market`, `journal_get`, ...) and `check_for_update` talk to vibedna.ai only
when you call them. See [SECURITY.md](SECURITY.md).

Vibedna, vibedna.ai
