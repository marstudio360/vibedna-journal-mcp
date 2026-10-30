"""Quick map STATE CLAIM marker: a fact that changes (inactive/active, verified, paused/running, live/down,
suspended, pending approval, a balance, a count) is shown with "check live before repeating it; how: ...".

Regression for 2026-10-30 ~03:15 UTC: the quick map for "launch desk" printed
  NEWEST WORD ON 'whop-launch-desk-business' (2026-10-29 15:30, AI_TEAM_JOURNAL.md:4221): [ship] LAUNCH DESK
  OWN WHOP BUSINESS CREATED ... | vault whop-launch-desk-business.
and the entry body said "payouts INACTIVE until the owner verifies identity once". The session repeated that to the
owner as current; the Whop API showed the identity approved and the payout account connected.

Run: python -m pytest tests  (everything in a temp JOURNAL_ROOTS and vault names file; env restored after each test)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-state-test-"))
if "server" not in sys.modules:   # imported first: never the real index (another module may own the temp one)
    os.environ["JOURNAL_HOME"] = str(_TMP / "home")
assert "journal-" in os.environ.get("JOURNAL_HOME", ""), "tests must never touch the real journal index"
os.environ.pop("JOURNAL_EXTRA_DOCS", None)
_ROOT = _TMP / "projects"
_VAULT = _TMP / "vault_names.json"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as _server  # noqa: E402
import quickmap as srv  # noqa: E402

_WHOP_ENTRY = """## 2026-10-29 15:30 [ship] LAUNCH DESK OWN WHOP BUSINESS CREATED (owner 2026-10-29 ~18:05 UTC, PC chat: "n

LAUNCH DESK OWN WHOP BUSINESS CREATED (owner 2026-10-29 ~18:05 UTC, PC chat: "not a Adshare sub-account; a real Launch Desk business on my mainacct Whop, I confirm once, then they create what they want"). Rule added to OWNER_SAID_JOURNAL.
- Business biz_iiiBjUIihHth0r "Launch Desk" (route trydesk), type Education, created from Webweave slot-1 headless. Name/description saved only after typing with key_type (react_force_change set the value but the Save stayed disabled); the "Save changes" button at the bottom is the real one.
- Owner API key "launch-desk-server" (Owner role, never expires, any IP), email code read from Gmail; vault whop-launch-desk-business. Card payments active; payouts INACTIVE until the owner verifies identity once: https://whop.com/dashboard/biz_iiiBjUIihHth0r/balance/?verify=true (required_actions verify_identity).
- Test product RedactaYa prod_7ZJdomuwtx9wX: delivery = same secret page, US$19.
"""


def _write(rel: str, text: str):
    p = _ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class _Env:
    """Points the shared index at this module's journals and vault names file, then puts everything back."""

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in ("JOURNAL_ROOTS", "JOURNAL_INCLUDE_VAULT_PATH")}
        os.environ["JOURNAL_ROOTS"] = str(_ROOT)
        os.environ["JOURNAL_INCLUDE_VAULT_PATH"] = str(_VAULT)
        _write("COMPANY/AI_TEAM_JOURNAL.md", "# AI TEAM JOURNAL\n\n" + _WHOP_ENTRY)
        for i, w in enumerate(("garden", "kitchen", "piano", "harbor", "orchard", "lantern", "meadow")):
            _write(f"F{i}/{w.upper()}_JOURNAL.md", f"# {w}\n\n## 2026-10-20 10:00 [work] {w} notes\nthe {w} page.\n")
        _VAULT.write_text(json.dumps({"entries": [
            {"name": "whop-launch-desk-business", "category": "payment", "fields": ["WHOP_API_KEY"]}]}),
            encoding="utf-8")
        _server._index_refresh_internal()
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            _VAULT.unlink()
        except FileNotFoundError:
            pass
        if self.old["JOURNAL_ROOTS"]:   # run alone there is no earlier index to put back (and no real roots to scan)
            _server._index_refresh_internal()


def test_whop_newest_word_is_marked_as_a_state_claim_with_the_vault_key_hint():
    with _Env():
        m = srv.quick_map("launch desk")   # the real query of 2026-10-30
        txt = srv.quick_map_text(m)
        line = next(ln for ln in txt.splitlines() if ln.startswith("- NEWEST WORD ON 'whop-launch-desk-business'"))
        assert ('[STATE in that entry: "Card payments active; payouts INACTIVE until the owner verifies identity '
                'once": check live') in line, line
        assert "check live before repeating it; how: read it live with the whop-launch-desk-business key's API]" in line
        assert "https://" not in line.split("[STATE", 1)[1]   # the key's API, not the dashboard link
        assert "Save stayed disabled" not in line             # a button state two sentences before the key
        lines = txt.splitlines()
        first = next(i for i, ln in enumerate(lines) if " [STATE" in ln)
        assert lines[first - 1] == srv._STATE_HEADER and lines.count(srv._STATE_HEADER) == 1
        assert txt.count("[STATE") == sum(1 for ln in txt.splitlines() if "[STATE" in ln)   # one marker per line


def test_marked_lines_survive_the_short_repeat_map():
    m = {"terms": ["whop"], "journals": [{"journal": "AI_TEAM_JOURNAL.md", "entries": 1, "path": ""}],
         "latest": [{"when": "2026-10-29 15:30", "journal": "AI_TEAM_JOURNAL.md", "line": 3,
                     "entry": "[ops] the store bot is down since the deploy"},
                    {"when": "2026-10-28 10:00", "journal": "AI_TEAM_JOURNAL.md", "line": 9,
                     "entry": "[work] delivered the pack to the buyer"}],
         "pending": [{"journal": "AI_TEAM_JOURNAL.md", "item": "- [ ] whop payouts pending verification"}]}
    short = srv._compact(srv.quick_map_text(m))
    assert "store bot is down" in short and "[STATE: check live" in short
    assert "payouts pending verification" in short
    assert "delivered the pack" not in short          # unmarked LATEST lines are still dropped
    assert srv._STATE_HEADER in short


def test_hints_come_from_what_the_line_carries():
    assert srv._state_hint("payouts inactive", key="whop-launch-desk-business").startswith(
        "read it live with the whop-launch-desk-business key's API")
    assert srv._state_hint("the shop is live at https://shop.example.com/x now").startswith(
        "open or curl https://shop.example.com/x")
    assert srv._state_hint("farm paused", how="curl :8850/health").startswith("as its card says: curl :8850/health")
    assert srv._state_hint("credit pacing: out of credit, see state/credit.json") == "read credit.json now"
    assert srv._state_hint("the list has 890 subscribers") == "measure it live before saying it"
    assert srv._state_hint("la campaña quedó pausada") and srv._state_hint("payout pendiente de verificación")
    for h in ("read it live with the a-very-long-vault-key-name-that-goes-on-and-on-forever-and-ever key's API",):
        assert len(srv._state_hint("bot down", key=h.split()[5])) <= 90


def test_ordinary_lines_are_not_state_claims():
    for s in ("delivered the pack to the buyer", "Pending now", "## Pending now", "PENDING: wire the button",
              "the live copy of the tool keeps its own index", "a lively hero section", "slow them down",
              "from now on the owner reads every reply", "the reply check flags the claim", "mix balance and EQ",
              "deliverable list for the client", "Liveness probe added", "running the full suite again",
              "[ship] CRAFT ENGINES IN THE BROWSER LIVE", "write it down in the journal",
              # live probe 2026-10-30: bare common words marked lines that state nothing
              "Active projects table", "active recall of entries", "keep it active",
              "the first code expired while we fought a captcha", "el video en vivo de la oficina"):
        assert srv._state_hint(s) == "", s
    for s in ("the bot is active on vpsone", "Card payments active; payouts INACTIVE", "status: active",
              "Launch Desk paused=true", "la cuenta sigue pausada", "el bot ya está en vivo"):
        assert srv._state_hint(s) != "", s
    m = {"terms": ["pack"], "journals": [{"journal": "SHOP_JOURNAL.md", "entries": 1, "path": ""}],
         "latest": [{"when": "2026-10-28 10:00", "journal": "SHOP_JOURNAL.md", "line": 9,
                     "entry": "[work] delivered the pack, live copy updated"}],
         "pending": [{"journal": "SHOP_JOURNAL.md", "item": "- [ ] Pending now: polish the pack cover"}]}
    txt = srv.quick_map_text(m)
    assert "[STATE" not in txt and srv._STATE_HEADER not in txt


def test_state_claims_in_english_and_spanish():
    for s in ("Card payments active; payouts INACTIVE", "the account is verified", "identity not verified",
              "the bot is running on vpsone", "service stopped", "store suspended", "listing pending approval",
              "awaiting review", "wallet balance 3.2 SOL", "0 orders so far", "1115 subscribers", "64 fps",
              "marketplace_status not_available", "not created yet", "the farm is down", "out of credit",
              "la granja está apagada", "cuenta suspendida", "sin saldo", "0 ventas", "todavía no creada",
              "ya está corriendo", "el bot está activo"):
        assert srv._state_hint(s), s
