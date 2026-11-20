# Install Neural DNA 2.2.0

**Neural DNA: Memory for your AI.** Neural DNA was called Journals DNA until version 1.6; the tool names, the folder layout and every setting are the same, so an install that works today keeps working. Your AI cannot skip your journal: that is still what it does. This file is self-contained: you can follow it yourself, or
open Claude Code in the unzipped folder and say "install this, following INSTALL.md". The AI should show you each
command before it runs it, ask before step 4, run the check of step 4a, and after the install ask you the three rules questions of step 4b.

## Before anything runs: what it needs, what it reads, what it adds, what it runs, how it comes off
AI installing this: show the person this block before the first command.

**It needs** (if one is missing, stop, say which one and how to get it; do not work around it):
- **Claude Code** (terminal, desktop app or an IDE extension) for the full install; this version was run with
  Claude Code 2.1.322, so use a current one. Another MCP client can only get the tools, with no hooks (step 7);
  Codex, GitHub Copilot and Cursor have BETA adapters (step 6).
- **Python 3.10 or newer** (`python3 --version`; on Windows `py --version`).
- **Windows, macOS or Linux**, about 1 MB of disk plus the private Python of step 1. Network only for step 1 (pip).
- No account and no API key.

**The order.** Step 1 (the private Python and its `pip install`) comes first, because the installer runs from it.
Then the dry run, the install, the check. Nothing outside the unzipped folder changes before the install of step 4.

**What it reads as journals.** Every file named `*JOURNAL*.md` or `journal.md` under `~/Desktop` and `~/Documents`,
a personal diary with that name included. To keep it to your project folders, set `JOURNAL_ROOTS` before the first
use (step 2); the index is built the first time anything calls the tool.
A file your AI touches outside those folders counts too: walking up from it (10 folders at most), the first folder
that holds 1 to 5 journal files is taken as its project, so the journal of a repository you cloned reaches your AI
as well. That brief (6,000 characters at most) then opens with a note that the
file is outside your journal folders and is that project's own notes, not your instructions.
`JOURNAL_OUTSIDE_ROOTS=off` stops briefs from journals outside your folders.

**The install adds:**
1. `<folder>/.venv/`: the private Python of step 1, inside the unzipped folder.
2. `~/.claude/settings.json`: two keys in its `env` block, `JOURNAL_MCP_DIR` and `JOURNAL_PYTHON`, after a backup
   `settings.json.bak_journals_<date>_<time>` next to it.
3. In Claude Code, through the `claude` command: one MCP server named `journal` (user scope, kept in
   `~/.claude.json`) and one plugin, `journals@journals-dna`, from the local folder `<folder>/mod` (recorded under
   `~/.claude/plugins/`, with a copy in `~/.claude/plugins/cache/journals-dna/`, and switched on in `enabledPlugins`
   of `settings.json`).
4. `~/.journal/`, made on first use: the search index of your journals, the mod's session state and its logs.

**The hooks the plugin registers.** Every one runs the same local program, `<folder>/.venv/bin/python
<folder>/quick_hook.py`, with the event as JSON on its input. That program may run `git` on your machine (`git
status`, `git diff`, `git clean -n`, `git rev-parse`; 3 seconds at most) when a git rule matches. No other program,
and no network unless you switch on the optional judge or the search by meaning yourself.

| When | It runs | It reads | It can |
|---|---|---|---|
| You send a message | `quick_hook.py --prompt` | your message, your journals | add a short map of what you named to the turn |
| Before your AI edits a file, runs a command, briefs an agent, calls another tool or reads a project file | `quick_hook.py` | the tool's name and input (file path, command, the first 4 KB of written text, an agent brief, another MCP tool's arguments up to 3,000 characters), your journals | add that project's journal brief or map to the call, and stop a call in the cases listed under "What can stop a call or a reply" |
| After your AI reads a journal | `quick_hook.py` | which journal was read and what the read returned (40,000 characters at most), to know the read worked | record it for the session |
| After a shell command | `quick_hook.py --output` | the text the command returned | add a note when it names something your journals already ruled on |
| When a reply is finished | `quick_hook.py --reply` | the reply | carry a note into the next turn |
| Before the turn ends | `quick_hook.py --stop` | the reply and the tool calls of the turn (from the session's transcript file) | send the reply back once when it says done right after a change nothing looked at |
| At session start and when the prompt is built | nothing (unless you set your own command in `JOURNAL_ON_SESSION_START`) | nothing | show the status line `Neural DNA · active` and add the paragraph below to your AI's instructions |

The hooks fail open: a hook that errors or takes too long lets the call go on unchecked. The limits are 30 seconds
for your message, 45 for a tool call and 12 for the end of a turn; the usual time is under half a second.
The hooks write only inside `~/.journal/`. The session state there keeps your last eight messages of each session
as typed (600 characters each) for 3 days, so a yes or a correction is read in context; keys in logged commands are
replaced by `<redacted>`, your messages are not. A journal is written only when your AI calls a journal tool such as
`journal_append`.

**The paragraph the plugin adds to your AI's instructions, word for word:**

> JOURNALS (one brain). Every project keeps its context in a *_JOURNAL.md.
> Before touching, building or answering about anything, call journal_quick("<word or file>") and read what it
> points to: what was decided, what exists, what is in flight. The journals mod shows the map by itself when you
> touch a mapped piece, and hands you that piece's journal brief with the call: read it before you act.
> Before writing or running your own script for a job, use the tool that already does it: the mod lists them
> ("TOOLS THAT ALREADY DO THIS"); if none fits, say in one line why.

**What can stop a call or a reply, all of it:**
- The default rules pack. It stops once (the same call again passes): a secret written into a file or commit, a
  delete that wipes a drive, your home or a whole project, losing unsaved git work, `DROP` / `TRUNCATE` / `DELETE`
  without `WHERE`, a force push to main, overwriting `.env` or key files. It waits for a yes before publishing to
  production, spending money, or messaging customers and posting. Two limits of the yes rules, said plainly: they
  look at shell commands and file writes only (a call to another MCP tool is not checked), and any yes word in your
  latest message opens them for that message (`yes`, `go ahead`, `do it`, `proceed`, `approved` and the like).
  Off: `JOURNAL_DEFAULT_RULES=off`.
- The journals gate. A touch of a project that has a journal gets the brief and goes through. Two cases are denied:
  a piece your Brain map names whose journal file is not on disk (a plain retry is denied again, the third try goes
  through with a note), and a journal file that exists but has nothing to hand over (no handoff, state, rules or
  dated entries, such as a new or free-text file): that touch is denied until your AI reads the file once.
- The done check. A finished reply goes back once when it says done right after a change nothing looked at. Off:
  `JOURNAL_DONE_CHECK=off`.
- Only if you set them up: your own exact rule tests, the paid-run guard, the shared-server guard, the AI checks.

**One switch turns the whole mod off:** remove the key `JOURNAL_MCP_DIR` from the `env` block of
`~/.claude/settings.json` and open a new session. No hook runs, the paragraph is not added and the status line does
not show; the journal tools keep working. Put the key back to switch it on.
The journal server keeps its own short instructions for as long as it is registered, as every MCP server does.
Word for word: "Project journals: one <PROJECT>_JOURNAL.md per project is the single source of truth. Start with
journal_handoff_brief(project). Search with journal_search before answering how/why/did-someone. Before building
anything call journal_before_build(task) and extend what already exists. Log work in the same turn with
journal_append; record reusable things with journal_capability_add. Current state, Pending now and Handoff are
replaced whole (journal_update_section mode=replace). Leave the Handoff so the next session can continue from the
brief alone. Full manual: journal_how_to()."

**Network.** The hooks make no network call. These tools go out, only when your AI calls them: `check_for_update`,
`journal_market`, `journal_pair`, `journal_get` and `journal_library` (vibedna.ai; `journal_get` with `confirm=True`
can open a checkout page in your browser), `journal_verify` and `journal_audit(check_urls=True)` (the URLs written in
your journal), `journal_backup_to_drive` (your own rclone remote). The optional search by meaning asks its own
service on `127.0.0.1`; only if you name a team service in `JOURNAL_MEANING_URL` do the question and the entry text
go to that address. There is no telemetry. SECURITY.md has the table.

**What writes outside `~/.journal`, only when your AI calls it.** The journal tools write the journal files you ask
for. `journal_get` saves a journal you own into `~/.journal/library/` or the folder you pass. An append to a
read-only journal goes to `~/journal-outbox/`. And two tools change your setup, only when you ask for them:
`journal_install_rule` adds one section ("Project Journals: HARD RULE") to `~/.claude/CLAUDE.md` or to a project's
`CLAUDE.md`, and `journal_install_build_check` adds one hook to `~/.claude/settings.json`. Both only show a preview
unless called with `confirm=True`, both copy your file first (`.bak_journals_<date>_<time>`), and the uninstall
takes both back out (the rule section only while it is still word for word as added). The install itself never
calls them.

**The install never touches:** the text of your journals, your rule files (`CLAUDE.md`, `AGENTS.md`), your AI's own
memory, your code, any key of `settings.json` other than the ones named above (the two `env` keys and this plugin's
entry in `enabledPlugins`), any other plugin or MCP server.

**One command removes what was added:** `<folder>/.venv/bin/python install_mod.py --uninstall` takes out the two
keys, the server entry, the plugin, its marketplace and Claude Code's cache copy of it, and what the two tools above
added. It says "Removed" only
when each step worked, and lists any step left for you. **What stays until you delete it:** `~/.journal/` (index and
logs), the unzipped folder with its `.venv`, the `settings.json.bak_journals_*` backups (one per change), and the
rule section in a project's own `CLAUDE.md` if you ever had the tool add one there. Your journals stay.

**The files are listed.** `MANIFEST.sha256` holds the SHA-256 of every file of this package, and the check of step 4a
compares them (`sha256sum -c MANIFEST.sha256` does the same on Linux, `shasum -a 256 -c MANIFEST.sha256` on macOS).
The dry run of step 3 prints this same footprint with your real paths.

## The two parts
Neural DNA is two parts, and the normal install sets up both with one command (`install_mod.py`, steps 3 and 4):
- **the journal server** (`server.py`, 35 tools to read, search and write your journals), and
- **the journals mod** (a Claude Code plugin in `mod/`): it is what makes your AI read the journal before it acts.
  Without the mod your AI only has the tools and may never call them.

The mod is made for **Claude Code** (terminal, desktop app and IDE extensions). Codex, GitHub Copilot and Cursor get
the same journal brief through their own hooks with the BETA adapters in `mod-adapters/` (step 6). Other MCP clients
get the 35 tools without the mod (step 7).

## The four moves
Every install of Neural DNA is these four commands, in this order, after step 1. An AI that installs it for you follows exactly
these and shows you each one before it runs it:
0. **The private Python** (step 1) comes first: the installer runs from it, so the dry run cannot run before it.
1. **Dry run** (step 3): `.venv/bin/python install_mod.py --dry-run` prints every change and writes nothing.
2. **Install** (step 4): `.venv/bin/python install_mod.py` asks once, then applies.
3. **Check** (step 4a): `.venv/bin/python install_mod.py --check` says whether it is installed and answering.
4. **Uninstall** ("Undo (uninstall)" below): `.venv/bin/python install_mod.py --uninstall` leaves your setup as it
   was.

## It adds, it never replaces
- Your journals, your rule files (`CLAUDE.md`, `AGENTS.md`, a rules folder) and your AI's own memory are never
  edited, moved or replaced. The dry run, the install and the check each list the ones they found, so you can see
  they are known and left alone.
- The install writes two keys in `~/.claude/settings.json` (after a timestamped backup), one MCP server entry and
  one plugin. Nothing else. Running it again changes nothing.
- Yours wins. A default rule of ours only ever stops once or waits for your yes, and you can switch any of them off
  (`JOURNAL_DEFAULT_RULES_OFF=<rule id>`, or `JOURNAL_DEFAULT_RULES=off` for the whole pack). Your own rule files are
  read as rules when you list them in `JOURNAL_RULE_FILES`; they are read, never rewritten.
- Nothing of yours is replaced unless you ask for it in words, and the uninstall removes exactly what the install
  added.

## What you need
- Python 3.10 or newer (`python3 --version`; on Windows `py --version`).
- Claude Code, for the journals mod (the journal briefs and the map before every change). Codex, GitHub Copilot and
  Cursor can use the BETA adapters (step 6); any other MCP client can still run the journal server on its own, without
  the mod (step 7).
- About 1 MB of disk. No account, no API key, no network for the journals themselves.

Paths below use `<folder>` for the folder you unzipped (the one with `server.py` in it). On Windows, every
`.venv/bin/` becomes `.venv\Scripts\`, and `python3` becomes `py`.

## 1. Make a private Python for the tool
From `<folder>`:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
`requirements.txt` pins `mcp==1.30.0` (the official MCP library, with FastMCP) and the 28 packages it pulls in, each
by exact version, the set the test suite ran on; it carries no hashes. A global `pip install` is refused on many
systems; the `.venv` avoids that and keeps your other Python projects untouched.

## 2. Tell it where your journals live (optional)
By default it scans `~/Desktop` and `~/Documents` for files named `*JOURNAL*.md`. To scan other folders, set
`JOURNAL_ROOTS` (folders separated by `;`) or add them later with the `journal_config_add_root` tool, which writes
`~/.journal/config.toml`.

## 3. Dry run: see every change before anything is written (server and mod)
```bash
.venv/bin/python install_mod.py --dry-run
```
It prints every change and writes nothing. These are the changes step 4 makes, all of them:
- **`~/.claude/settings.json`**, written by `install_mod.py` itself: two keys in its `env` block, `JOURNAL_MCP_DIR`
  (this folder) and `JOURNAL_PYTHON` (the `.venv` Python), so the mod can find the tool. Before writing, it saves a
  copy next to it as `settings.json.bak_journals_<date>_<time>`; nothing else in the file is changed.
- **The journal server**, through `claude mcp add journal -s user -- <folder>/.venv/bin/python <folder>/server.py`
  (Claude Code keeps user-scope servers in `~/.claude.json`).
- **The journals mod**, through `claude plugin marketplace add <folder>/mod` and `claude plugin install
  journals@journals-dna` (Claude Code records the local marketplace and the plugin under `~/.claude/plugins/`, keeps
  a copy of the plugin in `~/.claude/plugins/cache/journals-dna/`, and switches it on in the `enabledPlugins` block of
  `~/.claude/settings.json`).

Your journals are not touched. The index in `~/.journal` is made later, on first use.

## 4. Install
```bash
.venv/bin/python install_mod.py
```
It asks once (`Apply these changes? [y/N]`), then makes the changes above. An AI running this in a shell with no
keyboard uses `.venv/bin/python install_mod.py --yes`, and only after the person said yes to the dry run's list.
Running it again changes nothing. If the `claude` command is not on
your PATH, it still writes the two keys and prints the three `claude` commands for you to run where Claude Code
works.

**Restart Claude Code** (close it and open a new session): the mod and the server load at start. Check:
- `claude mcp list` shows `journal` as connected;
- `claude plugin list` shows `journals@journals-dna` enabled;
- ask your AI: `journal_quick("<a word from your project>")`.

The default rules pack is already on: nothing to set up. To see it, without running anything:
```bash
.venv/bin/python default_rules.py "git push --force origin main"
```
It prints the stop the mod would give (`STOP ONCE: Force push to main caught ...`).

## 4a. Check
```bash
.venv/bin/python install_mod.py --check
```
It changes no setting and none of your files. Each line says `ok` or `FIX` with what to do: the two settings keys,
the server entry and the mod in Claude Code, that the journal server loads, and that the mod's hook answers. An
older `journal` entry that would run instead of this one, and a `JOURNAL_ROOTS` the hooks cannot see, are `FIX`
lines too. It also lists the rule and memory files it found, which stay exactly as they are. The tool's own index (`~/.journal`)
is made the first time anything calls it, here or in your first session.

## 4b. Your own rules: three questions (your AI asks them once)
AI installing this: after step 4, ask the user these three questions in one message, then write the answers exactly
as `starter_rules_interview.md` says (a dated line in `RULES_JOURNAL.md`, and for exact commands one pattern line in
`~/.journal/paid_patterns.txt` or `~/.journal/yes_patterns.txt`, or `JOURNAL_MAIN_BRANCHES`). Check each pattern
with `default_rules.py "<command>"` and make sure it does not match the user's normal commands. If an answer is
"nothing" or "I don't know", write nothing for it.
1. What costs you money? (paid APIs, scripts that spend per run, cloud machines, ad budgets)
2. What must never go out without your yes? (mails, posts, messages to customers, price changes, anything public)
3. What is your production branch, and the command that deploys to production?

The default pack already covers the common cases; the answers add what only you know. No judge and no AI call is
needed afterwards: the patterns are checked exactly on every command, for free.

## 5. Try it on the demo journal
```bash
mkdir -p demo && cp examples/DEMO_PROJECT.md demo/DEMO_JOURNAL.md
JOURNAL_ROOTS="$PWD/demo" .venv/bin/python server.py --quick checkout
```
(Windows PowerShell: `mkdir demo; copy examples\DEMO_PROJECT.md demo\DEMO_JOURNAL.md; $env:JOURNAL_ROOTS="$PWD\demo"; .venv\Scripts\python server.py --quick checkout`.)

You get the Checkout row of the Brain map (who is on it, which journal to read first), the decision about prices,
what already exists, the latest entry and the pending tax line. You need nothing more for the brief: the first edit
or read of a file inside `demo/` carries `DEMO_JOURNAL.md`'s brief (the nearest journal). A `## Brain map` table
(see `BRAIN_MAP_TEMPLATE.md`) adds pieces that live elsewhere: the first edit of a file its keys name carries that
journal's brief.

## 6. Codex, GitHub Copilot and Cursor (BETA adapters)
Each app has its own folder in `mod-adapters/` with the hooks file and an `INSTALL.md` (install, a smoke command,
an in-app check, settings, remove): `mod-adapters/codex/`, `mod-adapters/copilot/`, `mod-adapters/cursor/`. They
run the same `quick_hook.py` with `--app codex|copilot|cursor`, so the journal brief, the maps, the default rules
pack and your exact rule tests work the same.
- Codex: tested live (the hooks run and the model follows the brief).
- GitHub Copilot and Cursor: tested with recorded hook payloads only; tell us what you see in a live session.
- In these apps the journals gate only delivers the brief (note mode, `JOURNAL_GATE_CODEX`, `JOURNAL_GATE_COPILOT`,
  `JOURNAL_GATE_CURSOR` = `note` by default); the other stops stay stops.
- GitHub Copilot cannot add text before a tool runs: there the brief arrives right after the tool, in the same turn.
Add the journal server to the app the way the app adds MCP servers (step 7) so your AI can read and write journals.

## 7. Other MCP clients (no mod)
Add the server to your client's MCP config, with the `.venv` Python by its full path:
```json
{ "mcpServers": { "journal": { "command": "<folder>/.venv/bin/python", "args": ["<folder>/server.py"] } } }
```
The tools work the same; the briefs and stops before edits need the mod (Claude Code) or an adapter (step 6).

## See your memory grow
```bash
.venv/bin/python growth.py --serve 4747 --open
```
One page opens in your browser (`http://127.0.0.1:4747`, this computer only). It plays how your journals grew, then
stays live: when your AI writes an entry, its dot arrives on the open page within seconds. Stop it with Ctrl+C.
- `.venv/bin/python growth.py --open` writes the page once to `~/.journal/growth/memory_growth.html` and opens it. The
  page is one file with no network calls, so it also opens from disk.
- `--root <folder>` (repeatable) scans other folders than your journal roots; `--skip WORD` leaves out journals
  whose file name holds that word; `--out <file>` writes the page somewhere else.
- `--hide-names` writes "Project 1, Project 2 ..." and `--demo-names` writes invented project names, for a page you
  show to other people. With either, no journal name and no entry title is in the page.
- Page options, added to its address: `?t=0.5` opens paused halfway, `?names=0` hides the labels, `?autoplay=0`
  waits for you.

Each build also writes `~/.journal/growth/neighbours.json`, the list behind the NEIGHBOURS line of the quick map, so
the list is as fresh as the last build (a list older than 7 days says so in the line). Naming each other and shared
decisions need nothing more. "Talk about the same things" uses the meaning index when you have built one ("Search by
meaning" below) and is left out when you have not. With no list there is no NEIGHBOURS line and everything else
works the same.

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
leave your machine. Without it, everything works with word search as before; until you run the build below, the
search by meaning stays off and no service is started.
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
`claude --help`, option `--model`), `JOURNAL_JUDGE_STRONG_MODEL` to a stronger one for the picks that decide
something (the tools pick, which rules a text can break), and `JOURNAL_VERDICT_MODEL` for the model that decides
every stop (a reply sent back; with `JOURNAL_AI_CHECKS` on, a command, tool call or write stopped). It never falls
back to the two models above: left unset, stops are decided by the `claude` command's own default model. Set it only
to a capable model: on our own computer a small model deciding stops stopped 93 to 97% of what it read, nearly all of
it wrongly.

The reply check holds the end of the turn for 12 seconds at most; when it needs longer, the reply goes out unchecked
rather than leaving you waiting.

## Your rules as exact tests and reminders (needs the judge)
With the judge on, your rules (every dated or `- ` line of your rules journals, plus the files you list in
`JOURNAL_RULE_FILES`, for example your `CLAUDE.md`) are compiled in the background after your next message whenever a
rule line changed. It is light by design, so it runs fine on your own computer: a new dated entry in a rules
journal starts nothing (only the rule lines count, compared by a hash in `~/.journal/rules_hash.txt`), the compile
runs at the lowest priority with no window, and a run with nothing new reads no log, no repo and asks no judge.
`JOURNAL_AUTOCOMPILE=off` turns the background compile off (then run it by hand). To run it yourself and see the
result:
```bash
.venv/bin/python rulecompile.py build          # only new or changed rules are read
.venv/bin/python rulecompile.py stats          # how many became exact tests, reminders, judgment, info
.venv/bin/python rulecompile.py try "git push --force origin main"
```
- A rule about an exact pattern becomes a test, kept only when it catches the judge's own examples of breaking the
  rule and passes its examples of doing it right. With `JOURNAL_AI_CHECKS` on, a command test must also pass almost
  all of your real commands that passed the check before; with `JOURNAL_COMPILE_CORPUS` pointing at your own repos, a
  write test that catches their existing text is kept only when the judge agrees those lines break the rule.
- The tests run on every command and file write with no AI. A call that breaks one is stopped once, with the rule
  and the right way; the same call again within 30 minutes passes.
- A rule that needs judgment can get a reminder instead: it is shown next to the commands it is about, once per
  session per rule, and never stops anything.
- One judge call reads 15 rules, once. The result lives in `~/.journal/compiled_rules.json`. With the judge off
  nothing is compiled and nothing is spent; the tests already compiled keep running.

## Check each command with the AI (optional, off by default)
`JOURNAL_AI_CHECKS=risky` sends the risky calls (servers, deletes, deploys, money, keys, messages, posts, a bare
`python`) to the judge before they run: it reads your closest rules and journal entries, what the command reaches
(your ssh config, the journal lines that name its hosts) and the commands of the last 10 minutes, and stops the
call when it goes against them, with the right way. `JOURNAL_AI_CHECKS=all` checks every command, MCP tool call and
file write. It needs the judge; commands and tool calls also need the search by meaning (without it they are not
checked). Each checked call takes a few seconds and two judge calls on your plan; a stop passes when the same call
is run again unchanged.

## Protect a shared server (optional)
Create `box_hosts.txt` in your journal home, one host, ssh alias or address per line (a trailing `*` matches any
suffix), or set `JOURNAL_BOX_HOSTS=build-server,10.0.0.7`:
```
# the servers several sessions share
build-server*
10.0.0.7
```
The 7th ssh, scp, sftp or rsync call to them within 60 seconds, counted across all sessions on this computer, is
stopped once with a note to group the calls; the same call again passes. Without the file nothing is counted.

## The default rules pack (on by default)
`default_rules.json` and `default_rules.py`: exact tests, no AI, no setup, nothing sent anywhere. What stops once
and what waits for your yes is listed in "New in 1.6.0" at the end of this file. A stop-once rule passes when the same call is run
again unchanged; a yes-gated one runs once your latest message says yes (`yes`, `go ahead`, `do it`, `approved`,
`ship it`, `send it`, `proceed` and the like, plus your own words in `JOURNAL_APPROVAL_WORDS`). Two limits, said
plainly: the yes rules look at shell commands and file writes only, so a call to another MCP tool (a posting or
mail tool, for example) is not checked by them; and any of those yes words anywhere in your latest message opens
them for that message, whatever the yes was about. To see what the pack says about
a command or a file before you run it:
```bash
.venv/bin/python default_rules.py "rm -rf ~/projects/shop"
.venv/bin/python default_rules.py --write config.py my_draft.py   # what it says about writing that text to config.py
```
- Off: `JOURNAL_DEFAULT_RULES=off`. One rule off: `JOURNAL_DEFAULT_RULES_OFF=` any of `secrets`, `destructive_rm`,
  `git_discard`, `sql_destroy`, `force_push`, `secret_files`, `publish`, `spend`, `message`, `user_yes`.
- `JOURNAL_MAIN_BRANCHES=production,main`: the branches a force push must never rewrite (default `main,master`).
- `~/.journal/yes_patterns.txt`: your own actions that need a yes, one regular expression per line (step 4b writes
  it); `~/.journal/paid_patterns.txt` is the paid-run list below.
- When one of your own exact rule tests already stops a command, the pack stays quiet: one stop per call.
- Measured on about 5,000 real commands of a busy developer machine: no stop with a clean repository; it costs well
  under a millisecond per command (a `git status` only when a git rule matches).

## Stop paid runs until you say yes (optional)
Off until you create `paid_patterns.txt` in your journal home (`~/.journal/paid_patterns.txt`): one regular
expression per line for what spends money (a paid API's address, a cloud GPU run, an MCP tool that generates media);
lines starting with `#` are notes. Nothing ships in it and nothing is checked without it.
```
# what spends money
\bmodal\s+run\b
api\.paid-example\.com
mcp__media__generate
```
A command or MCP tool call that matches is stopped until your latest message says yes (`yes`, `go ahead`, `do it`,
`approved`; add your own words in any language with `JOURNAL_APPROVAL_WORDS=word1,word2`). A plain retry does not
pass: your AI must tell you what it is and the estimated cost, and wait for your yes. Commands that only read or
search (`grep`, `cat`, `ls`, `git log`...) never match, so looking at a paid script is fine.

## See what the mod did and what it cost
```bash
.venv/bin/python modreport.py 24       # last 24 hours: AI calls and cost, briefs, exact stops, judge stops, replies sent back
.venv/bin/python judge.py spend 24     # the judge's calls by check
```

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
| `JOURNAL_MEANING_OFF=1` | Turn off the search by meaning (it is also off until `meaning.py build` ran or `JOURNAL_MEANING_URL` is set) |
| `JOURNAL_MEANING_URL` | A team embedding service (`embed_server.py` on a private address) instead of the local model |
| `JOURNAL_MEANING_PORT` | Port of the local meaning service (default 47311) |
| `JOURNAL_MEANING_MIN` | Lowest score shown as a meaning match (default 0.38 for the local model) |
| `JOURNAL_TOOLS_FILE` | Your tools list, if not `tools.json` in the journal home |
| `JOURNAL_JUDGE=on` | Switch the judge on (off by default) |
| `JOURNAL_REPLY_GATE=on` | Check each finished reply against your owner brief and tool sheets (needs the judge) |
| `JOURNAL_JUDGE_MODEL`, `JOURNAL_JUDGE_STRONG_MODEL` | Models for the judge's quick picks and its decisions (default: the `claude` command's own) |
| `JOURNAL_VERDICT_MODEL` | The model that decides every stop (default: the `claude` command's own; never the quick or strong model) |
| `JOURNAL_AI_CHECKS` | `off` (default), `risky` or `all`: the AI check of each command, MCP tool call and file write |
| `JOURNAL_ACTION_CHECK=off` | Turn the AI check module off even when `JOURNAL_AI_CHECKS` is set |
| `JOURNAL_RULE_FILES` | Rule files outside your journals (your `CLAUDE.md`, an `AGENTS.md`), separated by `;` on Windows and `:` elsewhere |
| `JOURNAL_OWNER_LEARN` | `off` turns off the learn check (a correction of yours with no entry written goes back once) |
| `JOURNAL_OWNER_CALLS` | `off` turns off the owner calls check (what a reply hands you against your Decided cards, and unwritten promises) |
| `JOURNAL_EXISTS_PROBE` | `off` turns off the exists check on your message |
| `JOURNAL_ALARM_JUDGE` | `off` turns off the judge that reads an alarm of the reply check before it is said (it only runs with the judge on) |
| `JOURNAL_ALARM_JUDGE_MODEL` | The model that reads those alarms (default: the verdict model) |
| `JOURNAL_JUDGE_LEAN` | `off` starts the judge's program the old way, with its side work at start |
| `JOURNAL_DONE_CHECK` | `off` turns off the check of "done" said right after a change nothing looked at |
| `JOURNAL_NEIGHBOURS` | Another place for the neighbours list (default `~/.journal/growth/neighbours.json`) |
| `JOURNAL_COMPILE_MODEL` | The model that compiles your rules into tests (default: the stop model) |
| `JOURNAL_COMPILE_CORPUS` | Your own git repos (same separator) whose text proves the write tests |
| `JOURNAL_BOX_HOSTS` | Shared servers for the flood guard, separated by `,` (or `box_hosts.txt` in the journal home) |
| `JOURNAL_APPROVAL_WORDS` | Your own words that count as yes, separated by `,`, for the paid-run guard (on only with `paid_patterns.txt` in the journal home) and the default pack's publish, spend and message rules |
| `JOURNAL_DEFAULT_RULES=off` | Turn the default rules pack off (on by default) |
| `JOURNAL_DEFAULT_RULES_OFF` | Single default rules off, separated by `,` (`secrets`, `destructive_rm`, `git_discard`, `sql_destroy`, `force_push`, `secret_files`, `publish`, `spend`, `message`, `user_yes`) |
| `JOURNAL_MAIN_BRANCHES` | Branches a force push must not rewrite, separated by `,` (default `main,master`) |
| `JOURNAL_GATE_CODEX`, `JOURNAL_GATE_COPILOT`, `JOURNAL_GATE_CURSOR` | The journals gate in the BETA adapters: `note` (default, the brief only) or `deny` |
| `JOURNAL_AUTOCOMPILE=off` | Turn off the background rule compile (default on, needs the judge; light by design) |
| `JOURNAL_ON_SESSION_START` | A command the mod starts at each new session, as a JSON array (`["python3", "/path/backup.py"]`); never waited for |
| `JOURNAL_JUDGE_CMD` | The command the judge runs (default `claude`) |
| `JOURNAL_JUDGE_TIMEOUT` | Seconds before a judge call gives up (default 30; the check then works as without a judge) |
| `JOURNAL_BRIEF_DAYS` | How many days of corrections and decisions the owner brief reads (default 21) |

## Rules your AI follows
Write rules as dated lines in `RULES_JOURNAL.md` (or `OWNER_SAID_JOURNAL.md`, or any `*_RULES_JOURNAL.md`); see
`RULES_TEMPLATE.md`. Each line starts with `- 2026-` and says the rule and its reason. Rules you keep outside your
journals (a `CLAUDE.md`) count too when you list them in `JOURNAL_RULE_FILES`. With the judge on, the rules about an
exact pattern become free tests (see "Your rules as exact tests and reminders").

## Run the tests (optional)
```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```
Everything runs in temporary folders; your journals and `~/.journal` are not touched.

## Undo (uninstall)
| What | How |
|---|---|
| Server, mod and settings keys | `.venv/bin/python install_mod.py --uninstall` (add `--dry-run` first to see it). It runs `claude mcp remove journal -s user`, `claude plugin uninstall journals@journals-dna` and `claude plugin marketplace remove journals-dna`, then removes the two `env` keys from `~/.claude/settings.json` (and the `env` block if it is left empty) plus any `enabledPlugins` / `extraKnownMarketplaces` entry left for this plugin only, with a backup first. Restart Claude Code afterwards |
| The index, session state, owner briefs, compiled rules, logs, your tools list and your pattern files | delete `~/.journal` |
| An app adapter | follow "Remove" in `mod-adapters/<app>/INSTALL.md` |
| The Obsidian map | delete `_obsidian/` and `.obsidian/` in that folder |
| Everything else | delete `<folder>` |
Your journals, your rule files and your AI's own memory are never changed by installing or uninstalling.

## If something is off
- "mcp package missing or too new": run step 1 again inside `<folder>`.
- The mod shows nothing: open a new session; check `JOURNAL_MCP_DIR` in `~/.claude/settings.json` points at
  `<folder>`; errors of the hook go to `~/.journal/quick_errors.log`.
- A stop you think is wrong: read the journal it names (that opens it), or turn that one check off with the
  setting above. An exact rule stop, a default rule stop-once or an AI check stop passes when the same call is run
  again unchanged. A default rule that waits for your yes runs once your latest message says yes; to turn it off
  for good, `JOURNAL_DEFAULT_RULES_OFF=<its id>` (the ids are listed in "The default rules pack").

# What changed in each version
The full list is in CHANGELOG.md.

## New in 2.2.0
Five checks that ran in our own copy since mid November are now in yours. All of them are exact tests: no AI call,
nothing to pay, and each can be switched off.
- **The learn check.** When your last message corrects your AI or sets a direction (whole words such as "always",
  "never", "I do not like", "it has to be", "I told you", in English or Spanish) and no entry tagged as yours
  (`[correction]`, `[decision]`, `[rule]`, `[owner-order]`, `[owner-said]`, `[verdict]`) was written to a journal in
  play during that turn, the reply goes back once: "save it now, then tell him in one line that it is saved". A
  journal tool call or a direct edit of a journal or rules file in the turn counts as written. A plain message costs
  nothing; a direction costs about 20 ms. `JOURNAL_OWNER_LEARN=off` turns it off. Every send-back is kept in
  `~/.journal/owner_learn_log.jsonl`.
- **The owner calls check.** A reply line that hands you something ("waits for your yes", "your call", a red
  blocked mark) is matched against your Decided cards; when a card gives that kind of call to someone else, the
  reply goes back with the card. A "from now on" with no rule written in the turn goes back too.
  `JOURNAL_OWNER_CALLS=off` turns both off.
- **The exists check.** A message that asks whether something exists ("do we have", "is there", "did we build",
  "tenemos", "hay") gets the entries your journals record as shipped, built or approved about it, before your AI
  answers. A finished reply that says a thing does not exist, or offers to create one, while such an entry names it,
  gets one correction line. A long message is read only on the sentences that ask. `JOURNAL_EXISTS_PROBE=off` turns
  off the part on the message.
- **The verdict check.** A reply that proposes something a sentence in your journals says was withdrawn, rejected
  or ruled out gets a note for the next turn, never a stop. Notes are kept in `~/.journal/verdict_check_log.jsonl`.
- **The moved-names check.** A reply that names a service, vendor or product whose move an entry TITLE records
  ("moved from X to Y", "X replaced by Y") without naming where it went gets a note. With the judge on, the alarm
  judge reads that note before it is said, like the other two.

## New in 2.1.0
- **Your message reaches your AI sooner (with the judge on).** Before each message the mod asks the judge which of
  your decisions apply and which entries mean the same. Those calls now start lean (four documented settings of the
  `claude` command: no update or status checks, no feature flags, no auto memory, no wait for MCP servers) and run
  side by side. Measured on our own machine: one judge call 3.5 s before, 2.1 s now; a message with two projects in
  play waited about 9.5 s for its map before, about 3 s now. `JOURNAL_JUDGE_LEAN=off` puts the old start back.
- **The alarm judge (with the judge on).** The reply check that runs after your AI's reply is shown matches words
  ("you listed it as still to do, but the journals say it shipped", "this runs on something that was shut down").
  Before such an alarm is said, the judge reads the reply sentence, the alarm and the entry it cites, and cancels it
  when the two are not about the same thing. One call per alarm, three at most, never waited for. No verdict in
  time keeps the alarm. `JOURNAL_ALARM_JUDGE=off` turns it off; every verdict is kept in
  `~/.journal/alarm_judge_log.jsonl`.
- **A thing you ask about keeps its map.** A name with a "no" just before it used to be read as "do not show me
  this"; inside a question it is now what you are asking about. And the decisions you recorded about a thing you name
  come with the message even when the rest of that thing's map is left out as off-topic.
- **A map that is late says so.** When the map of a message is cut at its time limit, your AI gets one line telling
  it the map did not arrive and to run `journal_quick` first.
- **Journal tools through a connector count.** A journal read or save made through a connector
  (`mcp__<server>__local_journal_journal_quick`) now opens the gate and shows as saved, like the tool's own.
- **Fix:** an entry tagged `[incident]`, `[bug]`, `[plan]`, `[idea]` or `[todo]` is never taken for a delivery
  because of a word in its title; and a ship entry that itself says the thing is not done no longer counts as done.

## New in 2.0.0
- **A new name.** Journals DNA is now Neural DNA: Memory for your AI. Only the name changed: the 35 tools
  (`journal_quick`, `journal_append` and the rest), the folder layout, the plugin (`journals@journals-dna`) and every
  `JOURNAL_*` setting are the same.
- **See your memory grow.** `growth.py` turns your journals into one page: every dated entry is a dot, every journal
  a cluster, the decisions you kept are bright dots, and a line joins two journals that name each other. It plays
  how your memory grew, then stays live: new entries arrive on the open page. See "See your memory grow" below.
- **The projects around a project.** The map your AI gets before it acts now carries one more line, NEIGHBOURS: the
  journals around the one in play and why (they name each other, they share a decision, they talk about the same
  things), each with its newest entry. A change that reaches the project next door is seen before it is made.
- **"Done" has to be looked at.** When your AI's reply says done, fixed or live (English or Spanish) and the last
  thing it did was a change that nothing looked at afterwards (no test, no build, no page request, no read-back),
  the reply goes back once for the one line that proves it, or for a plain "not verified yet". No AI involved,
  nothing to pay. Replayed on 1,533 real turns it sent back 26 (1.7%). `JOURNAL_DONE_CHECK=off` turns it off; every
  stop is kept in `~/.journal/done_check_log.jsonl`.
- **A check command.** `install_mod.py --check` says whether the install is complete and answering (step 4a).
- **Coming from an earlier version.** If an earlier install guide had you put a `journal` entry in a `.mcp.json`
  (in your home folder or a project), Claude Code uses that entry before the one this install adds, so the older
  copy keeps running in sessions opened from that folder. The dry run, the install and the check now name such an
  entry and how to remove it. They also name a `JOURNAL_ROOTS` or `JOURNAL_HOME` set only in a server entry: the
  mod's hooks run with the env block of `~/.claude/settings.json` and never see a server entry, so the value has to
  be there too (or list the folders as `roots` in `~/.journal/config.toml`, which the server and the hooks both
  read). The installer does not edit those files for you.

## New in 1.6.0
- **A rules pack that is on from the first minute, with no setup and no AI cost.** Exact tests written by us, run on
  every command and file write, no judge, no settings. They **stop once** (the same call again passes, so a wrong
  stop never blocks you):
  - a secret written into a file, a commit message or a post: API keys and tokens (`sk-...`, `ghp_...`, `AKIA...`,
    `xox...`, private key blocks and the like) and `password = "..."` literals in code. Real `.env` files are where
    secrets belong and are skipped; `.env.example` is not, because it goes to git;
  - deletes that wipe: `rm -rf` of a drive, your home folder, a whole project or a system folder (`node_modules`,
    `dist`, caches and other build output pass);
  - losing unsaved git work: `git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f` when they would
    really throw changes away (the mod asks `git status` first);
  - `DROP TABLE` / `DATABASE` / `SCHEMA`, `TRUNCATE` and `DELETE` without `WHERE` run through a database client;
  - a force push to `main` or `master`;
  - overwriting or deleting an existing `.env`, `credentials.json`, `id_rsa`, `*.pem` or `*.key` file.

  These **wait for a yes in your latest message** (a plain retry does not pass): publishing to production
  (`vercel` with `--prod`, `netlify deploy --prod`, `npm publish`, a PyPI or crates upload, `gh release create`,
  `firebase deploy`, `fly deploy`...), spending money (a Stripe live charge, an ads budget change, a new cloud VM or
  GPU) and messaging customers or posting (email APIs, `sendmail`, social network posts, SMS).
  Settings: `JOURNAL_DEFAULT_RULES=off` turns the pack off; `JOURNAL_DEFAULT_RULES_OFF=secrets,force_push` turns
  single rules off; `JOURNAL_MAIN_BRANCHES=production,main` names the branches a force push must not rewrite;
  `~/.journal/yes_patterns.txt` adds your own actions that need a yes. Details: "The default rules pack" below.
- **Three questions make the pack yours.** After the install your AI asks you what costs money, what must never go
  out without your yes, and your production branch and deploy command, then writes the answers where the mod reads
  them (`starter_rules_interview.md`, step 4b). No judge needed afterwards: the answers are exact patterns.
- **The journal brief comes on the first touch of any file in a project that has a journal**, with no Brain map.
  The rule: from the file's folder up to your journal root, the first folder that holds 1 to 5 `*_JOURNAL.md` files
  is that file's project, and its journal brief comes with the call once per session. A Brain map row still wins.
- **A running service or timer is never taken as proof.** When a command or its output names a systemd service or
  timer, or a cron script, the mod shows the newest incident, pause or kill-switch entry your journals have about it
  and says to check its log (`journalctl -u <unit> -n 20`) before saying it runs.
- **BETA adapters for Codex, GitHub Copilot and Cursor** (`mod-adapters/<app>/INSTALL.md`): the same journal brief
  through each app's own hooks, from the same core. Codex was tested live (the hooks run and the model follows the
  brief); GitHub Copilot and Cursor were tested with recorded hook payloads only. In these apps the journals gate
  only delivers the brief (note mode); the other stops (this rules pack, your exact rule tests, the paid-run and
  server flood guards) stay stops.
- **Fix:** a short message of yours (like "ok") now counts as your latest message, so an older "yes" cannot open the
  paid-run guard or the publish, spend and message rules.

## New in 1.5.0
- **No round trip on the first touch.** When your AI first touches a piece your Brain map names, the mod hands it
  that piece's journal brief with the call (Handoff, current state, pending, decisions, what exists, rules and the
  newest entries), and the call goes through. Before, the call was stopped until the AI had read the journal, which
  cost a whole extra turn every time.
- **Your rules become exact tests, written once.** With the judge on, the judge reads each of your rules once. When a
  rule is about an exact pattern (a command you never want run, a word or character your copy must not carry), it
  writes a test for it, and keeps the test only when it proves itself on examples. The tests then run on every
  command and every file write with no AI, for free. A call that breaks one is stopped once; the same call again
  passes, so a wrong test never blocks you.
- **Reminders at the right command.** Rules that need judgment ("heavy builds run on the build server") are shown
  next to the commands they are about, once per session per rule. A reminder never stops anything.
- **Cheaper by default: no AI check on each call.** The AI check of each command, tool call and file write is off.
  Switch it on with `JOURNAL_AI_CHECKS=risky` (servers, deletes, deploys, money, keys, messages and posts) or `all`.
  With the judge on, the AI still reads your finished reply once per turn (with `JOURNAL_REPLY_GATE=on`) and picks
  the journal lines that fit your message.
- **A reply check that reads what the reply states and proposes.** Each proposal and claim in the finished reply is
  checked against your journals (by meaning, when the search by meaning is set up), against what already exists and
  against your rules, and the newest entry about the same piece wins. When something is wrong, your AI writes only a
  short correction (you already read the reply), never the whole reply again.
- **Nothing waits after a finished reply.** The end-of-turn check gets 12 seconds at most; past that the reply goes
  out unchecked. The note for the next turn is worked out in the background.
- **A server flood guard (optional).** List your shared servers in `box_hosts.txt`: the 7th ssh, scp, sftp or rsync
  call to them within a minute, from all your sessions together, is stopped once. Nothing is counted until you list
  a server.
- **One setting for the model that decides a stop.** `JOURNAL_VERDICT_MODEL` names the model that decides every stop,
  apart from the quick picks, and it never falls back to them: unset, stops are decided by your `claude` command's
  own default model, even when you set a small model for the picks. No model name is built in.
- **See what the mod did and what it cost.** `modreport.py` prints the AI calls and their cost, the briefs handed
  over, the exact stops and the replies sent back; `judge.py spend` lists the cost by check.
- **A paid-run guard (optional).** List what spends money in `paid_patterns.txt` (one pattern per line): a matching
  command or tool call is stopped until your latest message says yes. Without the file nothing is checked.
- **The rule compile stays light.** It starts only when a rule line really changed (not when a dated entry was added
  to a rules journal), runs at the lowest priority, and a run with nothing new reads nothing and asks no judge.
  `JOURNAL_AUTOCOMPILE=off` turns it off.
- **Fix:** a plain `RULES_JOURNAL.md` (the name `RULES_TEMPLATE.md` suggests) is read as rules now; 1.4.0 read only
  `OWNER_SAID_JOURNAL.md` and names ending in `_RULES_JOURNAL.md`.

Earlier versions: see `CHANGELOG.md`.
