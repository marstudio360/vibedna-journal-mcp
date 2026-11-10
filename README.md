# Journals DNA

**Your AI cannot skip your journal.**

Journals DNA gives every project one markdown journal (`<PROJECT>_JOURNAL.md`) that your AI reads before it acts and
writes to while it works. The next session, or another AI, picks up exactly where the last one stopped, and you can
share your work with anyone by sending the journal.

It runs on your machine. Your journals stay where they are, in plain markdown.

## What it does, in plain words

- **Journals your AI must read.** In Claude Code, the first time your AI touches a piece of your project, the
  journals mod hands it that piece's journal brief with the call: the handoff, the current state, what is pending,
  what was decided, what exists, the rules and the newest entries. No extra turn, no skipping it.
- **A map before every change.** Before your AI edits a file, runs a command or briefs an agent, it sees a short map
  of that thing: which journal talks about it, who is working on it now, what was already decided, what already
  exists, the latest entries and what is still pending.
- **It warns when your AI repeats itself.** When the AI is about to build its own way of doing a job a tool you
  already have does, it is shown that tool. When a reply proposes something your journals already have a verdict
  on, or lists as pending something a journal says shipped, the AI is told so in its next turn.
- **It warns about stale status.** Lines that state something that changes (an account is active, a service is
  live, a balance) are marked "check live before repeating it" in the map. When the AI writes an entry that states
  such a status without saying how it was checked, the entry is still saved and the AI gets a warning.
- **Your rules, in your words.** Write your rules as dated lines in a rules journal (`RULES_JOURNAL.md` or any
  `*_RULES_JOURNAL.md`). When an action shares the words of a rule, the rule is shown next to it (with
  `JOURNAL_AI_CHECKS` on, the action also stops once).
  With the judge on, each rule about an exact pattern becomes a test written once, which then checks every command
  and file write for free; rules that need judgment are shown as a reminder next to the commands they are about.
- **Finds what you meant, in any language (optional).** A small model on your own processor gives every entry a
  meaning, so a question in other words or another language finds the entry that says the same thing. Your journals
  never leave your computer.
- **Old decisions never pass as current.** When a later entry replaced a decision, or states a different price or
  number for it, the decision is shown with that newer line first and your AI checks the live source and updates it.
- **It stops rebuilding what already exists.** Before your AI writes a new script or briefs an agent to build
  something a shipped entry already did, it is shown that entry (with `JOURNAL_AI_CHECKS` on, it is also stopped
  once).
- **Your decisions guard the reply (optional).** Each project gets an owner brief: your rules, what you already tried
  and lost, and the thread you approved. With the reply check on, each thing a reply proposes or states is checked
  against your journals: when it proposes again what you rejected or already did, states what a journal contradicts,
  or calls missing something that already exists, your AI writes a short correction right away.
- **Cheap by default.** No AI reads each command or edit unless you ask for it (`JOURNAL_AI_CHECKS`); the briefs,
  your exact rule tests, the reminders, an optional guard against flooding a shared server and an optional guard
  that holds paid runs until you say yes cost nothing. The background rule compile is light: it starts only when a
  rule line changed, at the lowest priority.
- **Old rules carry their newer word.** A rule or decision older than a week is shown with the newer entry that
  changed it, so your AI never follows an outdated rule as current.
- **A calm status line.** Under your prompt: `Journals DNA · active`, and one plain sentence only when something
  real happens.
- **Opens in Obsidian.** One command builds a map of all your journals for Obsidian: a START HERE page, a table view
  of every journal, and a canvas by folder. New journals are born with Obsidian properties.

## What is inside

| Part | What it is |
|---|---|
| `server.py` | The journal MCP server: 35 tools to read, search, write and keep journals (works with any MCP client) |
| `quickmap.py`, `quick_hook.py` | The quick map and the checks the mod runs (local, no network; no AI unless you switch the judge on) |
| `judge.py`, `owner_brief.py` | Optional: the judge (your `claude` command decides what is really relevant) and the owner brief of each project |
| `rulecompile.py`, `cmdguard.py` | Your rules as exact tests and reminders (written once by the judge, run with no AI), the shared server flood guard and the paid-run guard |
| `actioncheck.py`, `newest.py` | Optional AI check of each command, tool call and write (off by default), and "the newest word wins" before any stop |
| `modreport.py` | What the mod did and what it cost, from its own logs |
| `toolmap.py`, `tool_concepts.json` | "A tool already does this": matches an action to the tools and flows your journals list |
| `livecopy.py`, `ruledupes.py` | Warnings for a command on the wrong copy of a deployed folder, and for a rule written twice |
| `obsidian.py` | Builds the Obsidian map of your journals |
| `meaning.py`, `builtmap.py` | Search by meaning (optional, local model) and the "already built" check |
| `embed_server.py` | Optional: one shared embedding service on a team GPU machine |
| `mod/` | The journals mod, a Claude Code plugin |
| `install_mod.py` | One command that installs the server and the mod in Claude Code, and undoes it |
| `examples/DEMO_PROJECT.md` | A small journal to try everything on (copy it as `DEMO_JOURNAL.md` into a test folder) |
| `BRAIN_MAP_TEMPLATE.md`, `RULES_TEMPLATE.md` | Copy-paste starting points |

## New in 1.5.0

- The first touch of a piece carries its journal brief instead of a stop: no extra turn.
- Your rules become exact tests, written once by the judge and run on every command and write with no AI; a broken
  rule stops the call once, the same call again passes. Judgment rules come back as reminders, once per session.
- No AI check of each call by default (`JOURNAL_AI_CHECKS=risky` or `all` to switch it on).
- The reply check reads what the reply proposes and states, and asks for a short correction, never a repeat.
- Nothing waits after a finished reply: the end-of-turn check gets 12 seconds at most.
- An optional flood guard for shared servers (`box_hosts.txt`), one setting for the model that decides stops
  (`JOURNAL_VERDICT_MODEL`), and `modreport.py` to see what the mod did and cost.
- An optional paid-run guard: what you list in `paid_patterns.txt` is stopped until your latest message says yes.
  Off without the file.
- The background rule compile is light by design: only a changed rule line starts it, at the lowest priority
  (`JOURNAL_AUTOCOMPILE=off` turns it off).
- Fix: a plain `RULES_JOURNAL.md` is read as rules.

## Install

One install sets up both parts: the journal server and the journals mod (the Claude Code plugin that makes your AI
read the journal before it acts). Full steps, written so you can hand the file to your AI, with every file the
installer writes and how to undo it: [INSTALL.md](INSTALL.md). Short version, from this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python install_mod.py --dry-run          # Windows: .venv\Scripts\python install_mod.py --dry-run
.venv/bin/python install_mod.py                    # Windows: .venv\Scripts\python install_mod.py
```

The dry run prints every change and writes nothing; the second command installs the server and the mod (two keys in
`~/.claude/settings.json`, backed up first, plus the server and plugin entries the `claude` command keeps). Then
restart Claude Code (close it and open a new session) and ask: `journal_quick("<a word from your project>")`.
To undo it all: `install_mod.py --uninstall`.

The mod works in Claude Code only. Other MCP clients (Cursor and others) can run `server.py` as a normal MCP server
and get the 35 tools without the mod.

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
network calls of their own: the optional search by meaning talks only to its service on your computer (or to your
team's embedding service when you set one), and the optional judge runs your own `claude` command on your plan. The
store tools (`journal_market`, `journal_get`, ...) and `check_for_update` talk to vibedna.ai only when you call them.
See [SECURITY.md](SECURITY.md).

Vibedna, vibedna.ai
