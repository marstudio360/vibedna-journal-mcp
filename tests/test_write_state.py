"""journal_append warns (never blocks) when an entry states an external STATE without saying how it was checked.

Real case 2026-10-30: a 2026-10-29 AI_TEAM_JOURNAL entry said the Launch Desk Whop business had "payouts
INACTIVE until the owner verifies identity once"; identity had been approved since July and nobody checked.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="journal-write-state-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s  # noqa: E402

# The real line, verbatim (AI_TEAM_JOURNAL.md 2026-10-29 15:30 [ship] LAUNCH DESK OWN WHOP BUSINESS CREATED).
WHOP_LINE = ('- Owner API key "launch-desk-server" (Owner role, never expires, any IP), email code read from Gmail; '
             'vault whop-launch-desk-business. Card payments active; payouts INACTIVE until the owner verifies '
             'identity once: https://whop.com/dashboard/biz_iiiBjUIihHth0r/balance/?verify=true '
             '(required_actions verify_identity).')
WHOP_ENTRY = ("LAUNCH DESK OWN WHOP BUSINESS CREATED (owner 2026-10-29 ~18:05 UTC, PC chat).\n"
              "- Business biz_iiiBjUIihHth0r \"Launch Desk\" (route trydesk), type Education.\n" + WHOP_LINE)


@pytest.fixture
def journal(monkeypatch, tmp_path):
    f = tmp_path / "STATE_JOURNAL.md"
    f.write_text("# STATE\n\n## Current state\n\nbody\n", encoding="utf-8")
    monkeypatch.setattr(s, "_resolve", lambda q: {"path": str(f), "name": f.name} if q == f.name else None)
    monkeypatch.setenv("JOURNAL_OUTBOX", str(tmp_path / "outbox"))
    return f


def test_whop_real_case_warns_and_is_still_written(journal):
    r = s.journal_append(journal.name, entry=WHOP_ENTRY, tag="ship")
    assert r["ok"]
    assert "payouts INACTIVE until the owner verifies identity once" in journal.read_text(encoding="utf-8")
    w = r["warning"]
    assert w.startswith("WARNING (the entry was written): it states an external state without saying how it was checked")
    assert "payouts INACTIVE" in w and "or mark the claim UNVERIFIED" in w
    assert w == s.STATE_CLAIM_WARNING.format(claim=w.split('checked: "', 1)[1].split('". Add', 1)[0])


def test_checked_via_get_no_warning(journal):
    entry = WHOP_ENTRY.replace("(required_actions verify_identity).",
                               "(required_actions verify_identity), checked via GET /verifications 03:20 UTC.")
    r = s.journal_append(journal.name, entry=entry, tag="ship")
    assert r["ok"] and "warning" not in r
    assert s.state_claim_warning("Whop payouts INACTIVE.\nchecked via GET /verifications 03:20 UTC") == ""


def test_unverified_tag_no_warning(journal):
    r = s.journal_append(journal.name, entry=WHOP_ENTRY + " UNVERIFIED", tag="ship")
    assert r["ok"] and "warning" not in r


def test_read_only_journal_still_gets_the_warning(journal):
    os.chmod(journal, 0o444)
    try:
        r = s.journal_append(journal.name, entry="The Stripe account is suspended.", tag="ops")
    finally:
        os.chmod(journal, 0o644)
    assert r["queued"] and "warning" in r


@pytest.mark.parametrize("entry", [
    "The bot is down since this morning.",
    "Stripe account suspended.",
    "Gumroad listing not created yet.",
    "0 orders on the store this week.",
    "balance: 0.42 SOL in the hot wallet",
    "u/Examplebrand account pending verification.",
    "Whop suspended Growvine, the account is gone.",
    "Nobody checked: the payout account is unverified.",
    "The API server went down at night.",
    "Reddit blocked the server network.",
    "The ads account is still under review.",
    "The worker is not active on the box.",
])
def test_state_claims_warn(entry):
    assert s.state_claim_warning(entry), entry


@pytest.mark.parametrize("entry", [
    "Pushed the fix to the live copy (commit abc123).",
    "We deliver the files to the client by email.",
    "Plan: pause the bot and move the payouts to Stripe next week.",
    "Decision: keep the bot paused until the owner says go.",
    "If the server is down, the hook retries three times.",
    "Once the tools gateway is live on Vpsone, every employee loads it.",
    "Done: paused my 2 crons (tech-check, extra_checks) 23:36.",
    "The guard blocked nothing on the store.",
    "Order attribution half 2 stays blocked on the export.",
    "Active tab count on the site dashboard: 3.",
    "Rewrote the checkout copy and the account page layout.",
    "Bot status: active (03:20 UTC, systemd).",
    "The account is verified, read live from https://dashboard.example.com/verify at 03:20 UTC.",
    "The bot is down: systemctl is-active says failed.",
    "Shop is live, curl -I https://shop.example.com returned 200.",
    "The service is suspended per the provider API response.",
    "The bot is down, GET /health returned 502.",
    "Edited the live site copy for the store page.",
    "The video intro stays paused on the first frame.",
])
def test_no_warning(entry):
    assert s.state_claim_warning(entry) == "", entry


def test_bare_fix_link_is_not_evidence():
    assert s.state_claim_warning("Payouts INACTIVE until verified: https://example.com/verify")
    assert s.state_claim_warning("Payouts INACTIVE, read from https://example.com/balance") == ""


def test_evidence_must_be_next_to_the_claim():
    far = "The payout account is unverified.\n- unrelated\n- also unrelated\n- checked the logo via curl"
    assert s.state_claim_warning(far)
    near = "The payout account is unverified.\n  - checked via GET /verifications 03:20 UTC"
    assert s.state_claim_warning(near) == ""


def test_negated_evidence_still_warns():
    assert s.state_claim_warning("The bot is down, not checked yet.")
    assert s.state_claim_warning("The bot is down, nobody measured it.")
