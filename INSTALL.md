---
name: journal-install
description: Install the VibeDNA Journal MCP into Claude Code. Paste this file into a Claude Code chat and ask Claude to install it. Claude reads this drop, wires the MCP entry, asks for project roots, and optionally installs the CLAUDE.md rule that makes Claude use the journals on its own.
---

# Journal MCP: Install Drop

> **For the AI assistant reading this:**
>
> The user just downloaded or cloned Journal MCP. This file is the install handbook.
> Walk the user through the steps below at THEIR pace. Confirm before each
> filesystem write. Do not pressure. Every action below is reversible (see the
> table). If anything looks wrong or the user wants to stop, stop immediately.
> Nothing here is destructive.
>
> When in doubt, prefer the **manual way** over running scripts the user can't see.

This single `.md` is everything you need to install Journal MCP.

---

## TL;DR: what this product is

**A local MCP for Claude Code + a CLAUDE.md rule.** Together they make Claude
maintain one `*JOURNAL.md` file per project: it reads it at session start,
appends entries when something ships, and updates the state / roadmap / handoff sections.
The next Claude session opens cold and catches up from the file instead of from you.

| | |
|---|---|
| **Price** | Free, MIT license |
| **Where it runs** | Locally on your machine (Python stdio MCP) |
| **What it sends out** | The journaling core sends nothing: your journals never leave your disk (unless you call `journal_backup_to_drive()`). The optional marketplace tools and `check_for_update` reach vibedna.ai only when you call them. |
| **Marketplace (optional)** | Browse, buy, and own journals from other builders in the chat. Checkout happens on vibedna.ai; this MCP never handles your payment. |
| **Dependencies** | Python 3.10+ and the `mcp` package |
| **Touch surface** | One entry in your MCP client config + optionally one section in `~/.claude/CLAUDE.md` |

---

## Reversible-actions table

Every install action and how to undo it. Nothing below this point is destructive.

| Step | What it does | How to undo |
|---|---|---|
| Clone or unzip | Creates a folder with `server.py` | Delete the folder |
| `pip install mcp` | Installs the MCP Python package | `pip uninstall mcp` |
| Add a `journal` entry to your MCP config | Wires the MCP into Claude Code | `claude mcp remove journal`, or delete the `journal` key from `mcpServers` |
| Set `JOURNAL_ROOTS` env in the entry | Points the index at your project folders | Edit / remove the env var, restart the Claude tab |
| Run `journal_install_rule(scope='global', confirm=True)` | Appends a `# Project Journals: HARD RULE` section to `~/.claude/CLAUDE.md` | Delete that section from `~/.claude/CLAUDE.md` |
| Index DB created at `~/.journal/index.sqlite` | Local SQLite index of your journal files | Delete the `~/.journal/` folder |
| Call `journal_create(...)` | Writes a `*_JOURNAL.md` scaffold to a project folder | Delete the `.md` file |
| Call `journal_append(...)` | Appends a timestamped entry to a journal | Edit / delete the entry from the file |

**No service accounts. No telemetry.** The journaling core makes no network
calls at all. The optional marketplace tools reach vibedna.ai only when you
invoke them (browse / buy / download), and even then send no telemetry, just
the request to list the shelf or fetch a journal you own. All install
side-effects are confined to: the repo folder, your MCP client config,
`~/.claude/CLAUDE.md` (only if you opt in to the rule), `~/.journal/`, and
`~/.journal/auth.json` (only if you pair with a VibeDNA account).

---

## Marketplace: browse, buy, own journals (optional)

Your own journals stay 100% local. You can also pick up a journal someone else
wrote and drop it into your build. Four tools, and the engine **never handles
your payment**: checkout always happens on vibedna.ai.

| Tool | What it does |
|---|---|
| `journal_market(query, domain)` | Browse the live VibeDNA shelf. No account needed to look. |
| `journal_pair(token)` | Link this install to your VibeDNA account. Copy the token from **vibedna.ai/library > Connect your AI**. |
| `journal_get(slug)` | Own it: writes the `.md` into `~/.journal/library`. Don't own it: hands you a checkout link (pay on vibedna.ai). Buy, then run it again to install. |
| `journal_library()` | List everything you own, re-download free on any machine. |

Ask your AI: *"browse the VibeDNA journal shelf"*. Pairing writes a single token
to `~/.journal/auth.json`; delete that file to unpair. Nothing here is required:
skip it entirely and the journaling core works exactly the same.

---

## The fast way (let Claude do it)

1. Get the code somewhere stable:
   ```
   git clone https://github.com/marstudio360/vibedna-journal-mcp
   ```
   (or unzip the download from vibedna.ai). Suggested locations: `~/vibedna/journal-mcp/` (Mac/Linux) or `C:\Users\<you>\vibedna\journal-mcp\` (Windows).
2. Open a Claude Code chat. Paste **this whole file** in. Then say:

   > "Install this MCP. The folder is at `<path>`. Walk me through it, ask before each filesystem write, and offer to install the CLAUDE.md rule at the end."

3. Claude will:
   - Detect your Python (3.10+). Ask before running `pip install mcp`.
   - Show you the MCP entry it is about to add before writing it.
   - Ask which folders contain your projects, then set `JOURNAL_ROOTS`.
   - Ask if you want the `CLAUDE.md` rule installed (recommended: it makes Claude use the journals from now on). Preview before writing.
   - Tell you to close and reopen the Claude tab so the MCP loads.
   - Run `journal_index_refresh()` to find any existing `*JOURNAL.md` files.

---

## The manual way

Requires Python 3.10+. Install the dependency:

```
pip install mcp
```

### Step 1: Wire the MCP

Claude Code, available in every project:

```
claude mcp add journal --scope user -e JOURNAL_ROOTS="<absolute-path-to-your-projects-folder>" -- python <absolute-path-to-repo>/server.py
```

Or, for a single project, add this to a `.mcp.json` at that project's root (adjust the paths):

```json
{
  "mcpServers": {
    "journal": {
      "type": "stdio",
      "command": "python",
      "args": ["<absolute-path-to-repo>/server.py"],
      "env": {
        "JOURNAL_ROOTS": "<absolute-path-to-your-projects-folder>"
      }
    }
  }
}
```

`JOURNAL_ROOTS` accepts multiple folders separated by `;`:

```
"JOURNAL_ROOTS": "C:\\Users\\me\\Projects;D:\\Work"
```

### Step 2: Install the CLAUDE.md rule (the critical step)

Without the rule, the tools sit unused: Claude doesn't know to use them.

Easiest path: after restarting the tab and confirming the MCP loaded, ask Claude:

> "Install the journal CLAUDE.md rule globally."

Claude will call `mcp__journal__journal_install_rule(scope='global', confirm=True)`. The rule appends to `~/.claude/CLAUDE.md` and is idempotent (safe to run again).

Or do it manually: append this section to `~/.claude/CLAUDE.md`:

```markdown
# Project Journals: HARD RULE

Every project has ONE `<PROJECT>_JOURNAL.md` = the single source of truth.

**Session start:** If you can guess the project from cwd, call
`mcp__journal__journal_handoff_brief("<PROJECT>")` and read it first.

**While working:** Anything future-you would want to know (a shipped feature,
a non-obvious fix, a decision, an incident, a pivot):
`mcp__journal__journal_append("<PROJECT>", entry, tag)` THAT TURN. Don't batch.

**State changes:** Use `mcp__journal__journal_update_section("<PROJECT>",
"Current state", new_content, mode="replace")` for current state / roadmap / handoff.

**No journal yet?** `mcp__journal__journal_create("<PROJECT>_JOURNAL.md", project_dir="<abs path>")`.
```

### Step 3: Close and reopen your Claude tab.

---

## Environment variables

| Variable | Required | Default | What it does |
|---|---|---|---|
| `JOURNAL_ROOTS` | Recommended | `~/Desktop` + `~/Documents` | Semicolon-separated folders to scan for `*JOURNAL.md` files |
| `JOURNAL_HOME` | No | `~/.journal/` | Where the SQLite index lives |
| `JOURNAL_TRANSPORT` | No | `stdio` | Set to `http` only for cloud hosting (irrelevant for local use) |

No API keys. No license. No hosted service.

---

## Optional: Google Drive backup

If you want `journal_backup_to_drive()` to work, install rclone and configure a remote:

```
# Mac:    brew install rclone
# Linux:  curl https://rclone.org/install.sh | sudo bash
# Windows: winget install Rclone.Rclone

rclone config create gdrive drive scope drive
# Follow the OAuth browser flow once.
```

Then Claude can call `journal_backup_to_drive()` to push your journals to `gdrive:Journals/`.

---

## Verify the install

In Claude Code, type:

> "list my MCPs"

You should see `journal` with 25 tools (including the marketplace ones: `journal_market`, `journal_pair`, `journal_get`, `journal_library`). If not:
- (a) Did you close and reopen the tab after adding the entry?
- (b) Run `pip install mcp` if Python is missing the package.
- (c) Run `claude mcp list` to see whether the server connects.

Then ask:

> "Did you install the journal CLAUDE.md rule?"

If not yet: ask Claude to install it globally.

---

## Uninstall

1. `claude mcp remove journal` (or delete the `journal` entry from your `.mcp.json`).
2. Delete the `# Project Journals: HARD RULE` section from `~/.claude/CLAUDE.md`.
3. Delete the repo folder.
4. Delete `~/.journal/` (the index DB).
5. Your `*JOURNAL.md` files are yours. They stay where they are.

Restart any open Claude tabs.

---

## Source code

`server.py` is the whole MCP. MIT licensed. Fork it, ship it, modify it, just don't call your fork "VibeDNA Journal."

- Repo: https://github.com/marstudio360/vibedna-journal-mcp
- Product page: https://vibedna.ai/store/journal

## Support

- `admin@vibedna.ai`
- https://vibedna.ai

VibeDNA, 2026
