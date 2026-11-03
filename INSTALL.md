# Install Journals DNA 1.4.0

**Journals DNA: your AI cannot skip your journal.** This file is self-contained: you can follow it yourself, or
open Claude Code in the unzipped folder and say "install this, following INSTALL.md". The AI should show you each
command before it runs it and ask before step 4.

## New in 1.4.0
- **A calm status line.** Under your prompt the mod shows `Journals DNA · active`, and one plain sentence only when
  something real happens ("reading your notes on this first", "saved to your journal", ...). The AI still gets the
  full reasons; you no longer see internal wording.
- **Newer word on old rules.** When the map shows a rule or decision older than a week, a newer entry that changes
  it is shown right under it as `NEWER WORD`, so an outdated rule is never followed as current. Needs the judge and
  the search by meaning (both optional, below).
- **Your replies checked against your own decisions (opt in).** With `JOURNAL_REPLY_GATE=on` and the judge on, the
  AI's finished reply is checked before the turn ends against your owner brief: your rules, what you already tried
  and lost, and the thread you already approved. A reply that proposes again something you rejected, or that says
  one of your tools works another way than its sheet, is sent back for a rewrite, with the exact words quoted.
- **Judged manual hints.** When a lesson written in a project journal may belong in one of your refined manuals,
  the hint now names a section only when the judge agrees a reader of that manual needs it.
- **Your tools, described by you.** List your tools once in `tools.json` (below). A message that names one carries
  what it does today, so the AI never describes it from memory.

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

## Search by meaning (optional)
Your AI then finds the entry that says the same thing even when the question uses other words or another language
("el cobro con tarjeta falla" finds "checkout retries a failed card once"). It runs on your computer's processor with
a small multilingual model (about 220 MB, downloaded once into `~/.journal/meaning-model`); your journals never
leave your machine. Without it, everything works with word search as before.
```
.venv/bin/pip install fastembed numpy
.venv/bin/python meaning.py build      # one vector per journal entry; prints progress and time left
.venv/bin/python meaning.py query "a question in your own words"
```
(Windows: `.venv\Scripts\pip install fastembed numpy`, then `.venv\Scripts\python meaning.py build`.)
After the build, one small background service (one copy at most) answers the map and `journal_search`; it starts by
itself and keeps new entries in sync. The small model finds most rephrasings, not all: a word with no close cousin in
the other language (for example "boletin" for "newsletter") can still need the word search.
Teams with a GPU machine can run `embed_server.py` there on a private address (a bigger model, better matches) and
set `JOURNAL_MEANING_URL` on every computer; the index remembers which model made its vectors.

## Your own tools (optional)
Create `tools.json` in your journal home (`~/.journal/tools.json`, or the folder `JOURNAL_HOME` points at), or put
it anywhere and set `JOURNAL_TOOLS_FILE` to its path:
```json
{
  "Mail Robot": {"names": ["mail robot", "mailbot"], "sheet": "Sends the newsletter through the email API, never through a browser."},
  "Shop Scanner": "Reads competitor prices once a day from their public pages."
}
```
- `names`: one or two words each, matched with small typos (default: the tool's own name).
- `sheet`: what the tool does today and how it works at its core, in one or two sentences.

A message that names a tool gets a `WHAT OUR TOOLS DO TODAY` block with its sheet (and, when the message is clearly
about one of its `Already exists` cards, that card with its newest entry). With the reply check on, a reply that
contradicts a sheet is sent back. Without the file nothing is listed and both stay quiet.

## Switch on the judge (optional)
Some checks are decided by a language model instead of word rules: which journal lines are really about your
message, the owner brief of each project, the newer word on old rules, the manual hints, the "a tool already does
this" pick and the reply check. The judge is the `claude` command of Claude Code, already logged in on your machine:
each check is one short call on your own plan (a few seconds; answers are cached). It is **off by default**, and
with it off (or without the `claude` command on the PATH) the checks that need it fall back to the word and meaning rules of 1.3.0.

To switch it on, add the keys to the `env` block of `~/.claude/settings.json` (the mod and the server read them
there), then open a new Claude Code session:
```json
{ "env": { "JOURNAL_JUDGE": "on", "JOURNAL_REPLY_GATE": "on" } }
```
`JOURNAL_REPLY_GATE=on` is the reply check before the turn ends; leave it out to keep the judge without it (the
reply check needs the judge). By default the judge uses the `claude` command's own default model. Quick picks are
faster with a small model: set `JOURNAL_JUDGE_MODEL` to a model name your `claude` command accepts (see
`claude --help`, option `--model`), and `JOURNAL_JUDGE_STRONG_MODEL` to a stronger one for the picks that decide
something (the tools pick and the reply check).

Without a judge the owner brief is made from your `## Decided` cards and your latest `[correction]` and
`[decision]` entries; with it, the judge writes it in the background (up to 16 lines: RULE, LOST, OPEN). To see
one: `.venv/bin/python owner_brief.py --show <path of a journal>`.

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
| `JOURNAL_MEANING_OFF=1` | Turn off the search by meaning |
| `JOURNAL_MEANING_URL` | A team embedding service (`embed_server.py` on a private address) instead of the local model |
| `JOURNAL_MEANING_PORT` | Port of the local meaning service (default 47311) |
| `JOURNAL_MEANING_MIN` | Lowest score shown as a meaning match (default 0.38 for the local model) |
| `JOURNAL_TOOLS_FILE` | Your tools list, if not `tools.json` in the journal home |
| `JOURNAL_JUDGE=on` | Switch the judge on (off by default) |
| `JOURNAL_REPLY_GATE=on` | Check each finished reply against your owner brief and tool sheets (needs the judge) |
| `JOURNAL_JUDGE_MODEL`, `JOURNAL_JUDGE_STRONG_MODEL` | Models for the judge's quick picks and its decisions (default: the `claude` command's own) |
| `JOURNAL_JUDGE_CMD` | The command the judge runs (default `claude`) |
| `JOURNAL_JUDGE_TIMEOUT` | Seconds before a judge call gives up (default 30; the check then works as without a judge) |
| `JOURNAL_BRIEF_DAYS` | How many days of corrections and decisions the owner brief reads (default 21) |

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
| The index, session state, owner briefs and your tools list | delete `~/.journal` |
| The Obsidian map | delete `_obsidian/` and `.obsidian/` in that folder |
| Everything else | delete `<folder>` |
Your journals are never changed by installing or uninstalling.

## If something is off
- "mcp package missing or too new": run step 1 again inside `<folder>`.
- The mod shows nothing: open a new session; check `JOURNAL_MCP_DIR` in `~/.claude/settings.json` points at
  `<folder>`; errors of the hook go to `~/.journal/quick_errors.log`.
- A stop you think is wrong: read the journal it names (that opens it), or turn that one check off with the
  setting above.
