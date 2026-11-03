# Changelog

## 1.4.0 (2026-11-03)

Journals DNA: your AI keeps your decisions in mind when it answers, not only when it edits, and it stops quoting old
rules as if they were current.

**A calm status line**
- Under your prompt the mod shows `Journals DNA · active`, reset at every message, and one plain sentence only when
  something real happens: reading your notes first, using a tool you already have, found what you already decided,
  saved to your journal, fixing a reply that went against your notes. The AI still gets the full reasons.

**Newer word on old rules**
- When the map shows a rule, decision or correction older than a week, a search by meaning looks for newer entries
  and the judge says which one changes it; that one is shown right under it as `NEWER WORD`.
- Cards in the map and in `journal_search` carry the newest state-changing entry about the same thing, and a card
  that says "not deployed" while a later ship entry says deployed is flagged.

**The reply check against your own decisions (opt in)**
- Each project gets an owner brief (`owner_brief.py`): your rules, what was already tried and lost, and the open
  thread you approved. It is shown first in the map of your message.
- With `JOURNAL_REPLY_GATE=on` and the judge on, the finished reply is checked before the turn ends; a reply that
  proposes again what you rejected, or contradicts the sheet of one of your tools, is sent back for a rewrite. A
  break counts only with the reply's own words quoted.

**Judged manual hints**
- `journal_append` points a lesson at a section of one of your refined manuals only when the judge agrees a reader
  of that manual needs it (similarity alone pointed unrelated fixes at manuals).

**Also**
- Your own tools in `tools.json` (or `JOURNAL_TOOLS_FILE`): a message that names one carries what it does today.
  Empty by default.
- The judge (`judge.py`) is your `claude` command, off by default (`JOURNAL_JUDGE=on`); without it the checks fall
  back to the word and meaning rules of 1.3.0. No model name is built in: it uses the command's default unless you set one.
- Exact identifiers (an IP, host:port, @account, a hex id, a version) are searched as written first.
- A journal read in the last 30 minutes opens its gate, whatever message it was read in; a guard named after a piece
  (`shop-gate`) is not the piece; shouting in capitals is not read as names; a name you say you do not want is left
  out of the meaning search.
- Reading a journal file by hand gets a short note naming the journal tool call that does it in one step.

## 1.3.0 (2026-11-01)

Journals DNA: your AI finds what your journals mean, not only the words you used, and it never repeats an old
decision as if it were still true.

**Search by meaning (optional)**
- Every journal entry gets one meaning vector from a small multilingual model that runs on your computer's processor
  (no GPU, no account, your journals never leave your machine). A question in other words or in another language
  finds the entry that says the same thing. `journal_search`, `journal_quick` and the map show these as
  "SAME MEANING" lines first, mixed with the word search by rank.
- Turn it on with `pip install fastembed numpy` and `python meaning.py build`. Without it everything works as before
  with word search. One small background service holds the model (one copy at most, one indexer at a time).
- Teams with a GPU machine can run `embed_server.py` on a private address and point every computer at it with
  `JOURNAL_MEANING_URL` (a bigger model, better results); the index remembers which model made its vectors.

**It stops rebuilding what already exists**
- "Already built": when your AI is about to write a new script, or launch an agent to build something, whose job a
  `[ship]`, `[feature]` or `[build]` entry already did, it is shown that entry and the scripts it names, and stopped
  once. Found by meaning, no cards to write by hand.

**Old decisions never pass as current**
- A `## Decided` card that a later decision replaced is shown with "CHANGED LATER" and the newer sentence first.
- A card whose price or number a later entry states differently (for example a card says $99 and later entries say
  $27) is shown with "NEWER VALUE": the latest entry wins, your AI checks the live source and marks the old card
  SUPERSEDED in the same turn. Cards that list many prices are left alone (a new number there is usually another item).

**Big journals stay fast**
- `obsidian.py archive`: moves the older months of a big journal into one file per month, in two separate runs
  (write with backup and manifest, then a verified trim that keeps anything appended in between).

## 1.2.0 (2026-10-30)

Journals DNA: your AI cannot skip your journal. Everything since 1.0.6, in plain words.

**Your AI reads before it acts**
- New: the journals mod, a Claude Code plugin, installed with one command (`install_mod.py`, with `--dry-run` and
  `--uninstall`). It also registers the journal server in Claude Code.
- Before an edit, a command that writes, or an agent launch, your AI sees the map of what it is about to touch. The
  first touch of a piece named in a `## Brain map` table stays stopped until that piece's journal was really read in
  the session; a plain retry does not pass.
- New tool `journal_quick` and `server.py --quick <word or file>`: for any word, file or topic, its journals, its
  Brain map row (who is on it now, what to read first), decisions, what already exists, the latest entries and
  what is pending.
- "A tool already does this": when your AI is about to write or run its own script for a job one of your tools
  does, it is shown that tool and stopped once.
- Your rules: dated lines in any `RULES_JOURNAL.md`, `*_RULES_JOURNAL.md` or `OWNER_SAID_JOURNAL.md` are shown when
  an action shares their words, and stop once. Writing a rule that is already there gets a warning.
- A command on a folder that the journals say is an old twin of the live copy is stopped once.

**It catches repeats and stale status**
- The map marks lines that state something that changes (active, live, paused, a balance, a count) with "check
  live before repeating it" and how to check it.
- `journal_append` warns (the entry is still written) when an entry states an outside status without saying how
  and when it was checked.
- After each reply, if your AI listed as pending something a journal says shipped, or proposed something your
  journals already have a verdict on, it is told so in its next turn (never drawn in your chat).
- Names in a command's output that your journals already ruled on come back as a short note.
- When a newer entry says a piece was replaced, the map shows that first.

**Less noise**
- A piece's map shows once per session, not on every file of it. Background task notices and agent reports are
  not treated as your messages. Launching an agent is never stopped (its map rides along as context). Git
  bookkeeping (add, commit, status, log) gets no map. Throwaway git worktrees (`-wt-` folders), test fixtures and
  files a website serves are not indexed.

**Obsidian**
- New `obsidian.py vault`: START HERE page, a table view of every journal, and a canvas map by folder, plus a
  minimal `.obsidian` config. `obsidian.py add-frontmatter` gives older journals Obsidian properties (dry run by
  default).
- New journals are born with Obsidian properties; reads, search and appends handle them, and appends keep
  `updated` and `entries` current with an atomic write.

**More tools and easier calls**
- New tools: `journal_verify` (re-run `check:` lines under a claim), `journal_audit`, `journal_contradictions`,
  `journal_map`. 35 tools in all.
- Journal tools take the journal as `name_or_path`, `project`, `journal`, `name` or `path`; a missing argument gives
  one plain line with an example.
- `journal_read` reads line ranges (`offset`/`limit` or `start_line`/`end_line`); `journal_list_sections` pages and
  filters long journals; `journal_search` returns the best entries of each journal.
- An append to a read-only journal is queued in an outbox file instead of failing.

## 1.0.6 (2026-10-22)

- New "Decided" section: `journal_decision_add(name, decision, why, aliases, see, date)` records what the owner decided as one line, with every word someone might use for it.
- `journal_search`: each result carries `current_state` and `already_decided`; a search with few matches returns a hint to try other words.
- `journal_before_build`, the before-build hook and the start brief show the decisions too.
- Better before-build matching; new synonym groups; docs fixes.

## 1.0.5 (2026-10-22)

- Built-in manual for any AI, "Already exists" registry, `journal_before_build` and an optional before-build hook.
- Search with synonyms in two languages; start brief with pending work first; "database is locked" fix.

## 1.0.4 (2026-10-20)

- Search never answers from an old copy: changed journals are re-read before each search.

## 1.0.3 (2026-10-06)

- Purchased journals and drafts are readable again after the 1.0.2 hardening.

## 1.0.2 (2026-10-06)

- Security: read/append/update accept only journal files; `journal_create` rejects `../`; the connect token travels in a header.
