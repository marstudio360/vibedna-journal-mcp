# Brain map template

Paste this section into one of your journals (any `*_JOURNAL.md`). One row per piece you want your AI to read about
before it touches it.

```markdown
## Brain map

| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Checkout | checkout, cart, payments.py | the shop team | SHOP_JOURNAL.md | hosted payment page only |
| Mail | mail, newsletter, send_mail.py | nobody right now | MAIL_JOURNAL.md | list size is counted live |
```

- **Piece**: the name you use for it.
- **Keys**: words and file names people use for it, separated by commas. A key matches whole words only.
- **Working on it now**: who or what is in flight, so the next person or AI sees it. "nobody right now" is a fine answer.
- **Read first**: the journal to read before touching the piece.
- **Notes**: one line that saves a question.

Ask one word to see a row: `.venv/bin/python server.py --quick checkout`, or `journal_quick("checkout")` in your AI.
The map also serves to share your work: anyone who opens the journal sees where each piece lives and who has it.
