# Changelog

## 1.5.0 (2026-11-06)

Journals DNA: your AI gets the memory with the call instead of a stop, your rules check every command for free, and
nothing waits after a reply.

**The journal brief comes with the call**
- The first touch of a piece your Brain map names (an edit, a command, a read) carries that piece's journal brief:
  Handoff, current state, pending, decided, already exists and rules sections, plus the six newest entry headings,
  read straight from the file (about 20 ms). The call goes through and the brief counts as the session's read of
  that journal. Only when the journal file is missing is the touch stopped until it is read, as before.

**Your rules as exact tests and reminders (`rulecompile.py`, needs the judge)**
- The judge reads each of your rules once (15 per call). A rule about an exact pattern in a command or in written
  text becomes a test, kept only when it catches its own examples of breaking the rule and passes its examples of
  doing it right (and, when the data is there, stops almost none of your real commands and none of your own repos'
  text by mistake). Write tests can be limited to some files (for example customer pages only); paths and addresses
  inside written text are never judged as words.
- The tests run on every command and file write with no AI. A break is stopped once with the rule and the right way;
  the same call again within 30 minutes passes, and then no other check stops it a second time.
- Rules that need judgment can get a reminder pattern: the rule is shown next to the commands it is about, once per
  session per rule, never as a stop.
- New or changed rules compile in the background after your next message (one at a time, no visible window). It is
  light by design: only a change in the rule LINES starts it (a hash in `rules_hash.txt`; a new dated entry in a
  rules journal starts nothing), it runs at the lowest priority (idle on Windows, `nice 19` elsewhere), and a run
  with nothing new reads no log, no repo and asks no judge; your repos are read only when a new write test needs
  its proof. `JOURNAL_AUTOCOMPILE=off` turns it off. With the judge off nothing is compiled and nothing is spent.
- Rules come from `OWNER_SAID_JOURNAL.md`, `RULES_JOURNAL.md` and any `*_RULES_JOURNAL.md`, plus the files you list
  in `JOURNAL_RULE_FILES` (for example your `CLAUDE.md`). Nothing else is read as a rule.

**Cheaper by default**
- The AI check of each command, MCP tool call and file write (`actioncheck.py`) is off. `JOURNAL_AI_CHECKS=risky`
  checks the risky ones (servers, deletes, deploys, money, keys, messages, posts), `all` checks every call. With it
  off, the "a tool already does this" list and the map of what you are about to do are notes, never stops.
- With the judge on, what stays: the cheap picks of the journal lines that fit your message, and the end-of-turn
  reply check (with `JOURNAL_REPLY_GATE=on`).
- `JOURNAL_VERDICT_MODEL`: the model that decides every stop, apart from the quick picks. Unset, stops use the
  `claude` command's own default model and never fall back to the quick or strong model (a small model deciding
  stops stopped 93 to 97% of what it read in our measurements). No model name is built in.
- Every judge call is logged with its tokens and cost (`~/.journal/judge_usage.jsonl`); `judge.py spend [hours]`
  totals them by check. `modreport.py [hours]` adds the briefs handed over, the exact stops, the judge stops and the
  replies sent back (`~/.journal/mod_events.jsonl` and the checks' own logs).

**The reply check reads what the reply proposes and states**
- The end-of-turn check lists up to five proposals and claims of the reply, searches your journals for each (by
  meaning when the search by meaning is set up), adds the "already exists" lines and tool sheets about them, and two
  verdicts decide at once (either counts). A wrong item gets a short correction from your AI in your language, never
  the whole reply again.
- The newest word wins before any stop (`newest.py`): lines written after the one a stop rests on, about the same
  piece, are found by meaning, and a stop they lift falls. Your messages of the session, in order, go with it.
- When the search by meaning is set up but does not answer, the reply is not passed as checked: your AI is told it
  was not checked.

**Nothing waits after a finished reply**
- The end-of-turn check gets 12 seconds at most (past that the reply goes out unchecked); the note for the next turn
  runs in the background. A command's check gets 45 seconds.

**A server flood guard (`cmdguard.py`, optional)**
- List your shared servers in `box_hosts.txt` in the journal home (or `JOURNAL_BOX_HOSTS`): the 7th ssh, scp, sftp
  or rsync call to them within 60 seconds, across all sessions on the computer, is stopped once; the same call again
  passes. Nothing is counted without the list.

**A paid-run guard (`cmdguard.py`, optional)**
- List what spends money in `paid_patterns.txt` in the journal home, one regular expression per line: a command or
  MCP tool call that matches is stopped until your latest message says yes (`yes`, `go ahead`, `do it`, `approved`,
  plus your own words in `JOURNAL_APPROVAL_WORDS`); a plain retry does not pass. Only the parts of a command that
  run something are matched: reading or searching a paid name (`grep`, `cat`, `ls`...) never asks. Nothing ships in
  the list and nothing is checked without the file.

**Also**
- The mod can start a command of yours at each new session (`JOURNAL_ON_SESSION_START`, a JSON array, never waited
  for). Unset by default.
- The search by meaning stays off until `meaning.py build` ran (or `JOURNAL_MEANING_URL` is set): no service is
  started on a computer that does not have it.
- An edit of an existing file no longer runs the "a tool already does this" check (new files, commands and agent
  briefs still do), and a file's map is not run again for 30 minutes in the same session once it let the edit
  through.
- Fix: a plain `RULES_JOURNAL.md` (the name `RULES_TEMPLATE.md` suggests) is read as rules; 1.4.0 read only
  `OWNER_SAID_JOURNAL.md` and names ending in `_RULES_JOURNAL.md`.

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
