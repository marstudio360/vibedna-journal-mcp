# DEMO JOURNAL

A small journal to try Journals DNA on. It is named DEMO_PROJECT.md so it is not indexed where it sits; copy it
into a test folder as DEMO_JOURNAL.md to try the quick map and the Obsidian map (INSTALL.md, step 5).

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Checkout | checkout, cart, payments.py | the shop team | DEMO_JOURNAL.md | hosted payment page only |
| Newsletter | newsletter, mailing list, send_mail.py | nobody right now | DEMO_JOURNAL.md | list size is counted live |

## Decided
- **Checkout prices come from the price list file only.** · why: one place to change a price · aliases: checkout, price, pricing, price list · date: 2026-10-01

## Already exists
- **Receipt mailer: sends the checkout receipt after a paid order** · how: send_mail.py receipt <order id> · status: working · keys: checkout, receipt, mail, order

## Current state
- Checkout is live on the hosted payment page (checked 2026-10-20 10:00 UTC by opening the checkout page).

## Handoff for next session
- [x] Card retry on a failed payment
- [ ] Add the tax line to the checkout receipt
- Next step: the tax line goes in send_mail.py, template receipt.html.

## 2026-10-20 10:00 [ship] checkout retries a failed card once

The retry lives in payments.py. Tested with a declined test card: the second try passes.

---
