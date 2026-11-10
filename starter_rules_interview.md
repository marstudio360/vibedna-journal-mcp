# Starter rules interview

The journals mod ships with a default rules pack (`default_rules.json`, on with no setup): it stops once a secret
written into a file or a commit, a destructive delete, `git reset --hard` over unsaved work, `DROP` / `TRUNCATE` /
`DELETE` without `WHERE`, a force push to main or master, and overwriting or deleting `.env` and key files. It stops
publishing to production, spending money and messaging customers or posting until your latest message says yes.

The pack cannot know YOUR money, YOUR outward actions or YOUR production branch. The start prompt asks three
questions, once, and the AI writes the answers where the mod already reads them. Nothing here needs a judge or an
AI call afterwards: the lines below are read on every command, for free.

## The three questions (the start prompt asks them in this order, one message)

1. **What costs you money?** Paid APIs, scripts or tools that spend per run, cloud machines, ad budgets.
2. **What must never go out without your yes?** Mails, posts, messages to customers, price changes, anything public.
3. **What is your production branch, and the command that deploys to production?** For example `main` and
   `npm run ship`, or `production` and `./deploy.sh prod`.

If an answer is "nothing" or "I don't know", write nothing for it: the default pack still covers the common cases.

## How the AI turns the answers into rules

Each answer becomes up to two things: a dated line in `RULES_JOURNAL.md` (the human-readable rule, which the mod
shows when the AI's work shares its words) and, when the answer names an exact command, one pattern line in a file in
the journal home (`~/.journal/` unless `JOURNAL_HOME` is set), which the mod checks exactly on every command.

| Answer | Line in `RULES_JOURNAL.md` | Exact pattern (one Python regex per line) |
|---|---|---|
| 1. What costs money | `- <date>: No paid run of <thing> without telling me the estimated cost first and getting my yes.` | `paid_patterns.txt`: stopped until the latest message says yes; a plain retry does not pass |
| 2. What never goes out without a yes | `- <date>: Nothing goes to <who> (<what>) without my yes on the final text.` | `yes_patterns.txt`: same yes rule, with the message "on your list of actions that need your yes" |
| 3. Production branch | `- <date>: <branch> is production; work on a branch and never force push to <branch>.` | `JOURNAL_MAIN_BRANCHES=<branch>,main` in the mod's environment (force push protection) |
| 3. Deploy command | `- <date>: Deploy to production only with <command>, and only after my yes.` | `yes_patterns.txt`: the deploy command |

`RULES_JOURNAL.md` lives in a journal root (any folder the journal tool scans). Create it if it does not exist:

```markdown
# Rules

- 2026-03-05: No paid run of the image generator (scripts/gen_images.py) without telling me the estimated cost first and getting my yes.
- 2026-03-05: Nothing goes to customers (newsletter, order mails, social posts) without my yes on the final text.
- 2026-03-05: production is the live branch; work on a branch and never force push to production.
- 2026-03-05: Deploy to production only with npm run ship, and only after my yes.
```

`~/.journal/paid_patterns.txt` for the same answers:

```text
# what spends money (one regex per line)
\bscripts/gen_images\.py\b
\breplicate\.run\b
```

`~/.journal/yes_patterns.txt`:

```text
# what needs my yes (one regex per line)
\bnpm\s+run\s+ship\b
\bgit\s+push\s+\S+\s+production\b
\bpython\s+\S*send_newsletter\.py\b
```

## Rules for writing a pattern

- Match the command that RUNS the thing, never its name in general: `\bscripts/gen_images\.py\b`, not `images`.
  Reads and searches (`grep`, `cat`, `ls`, `git log`...) are skipped by the mod, so `grep gen_images` never asks.
- Escape dots and slashes that are literal (`\.`), use `\b` at word edges, `\s+` between words.
- Check each pattern before saving it: `python default_rules.py "<the command>"` shows what the pack catches, and the
  pattern must not match the user's normal commands (`npm run build`, `npm test`, `git push origin my-branch`).
- One rule per line. Lines starting with `#` are notes.

## Yes words

A yes is any of: yes, yeah, yep, go ahead, do it, approved, ship it, publish it, send it, go for it, confirmed,
proceed. Add your own words, in any language, in `JOURNAL_APPROVAL_WORDS` (comma-separated), for example
`JOURNAL_APPROVAL_WORDS=oui,si,vamos`. The yes must be in the user's latest message.

## Turning rules off

- The whole default pack: `JOURNAL_DEFAULT_RULES=off`.
- Single rules: `JOURNAL_DEFAULT_RULES_OFF=secrets,force_push` with any of: `secrets`, `destructive_rm`, `git_discard`,
  `sql_destroy`, `force_push`, `secret_files`, `publish`, `spend`, `message`, `user_yes`.
- A stop-once rule is never a wall: the same call again passes.
