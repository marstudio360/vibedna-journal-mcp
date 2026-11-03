"""Tests run on temporary journal homes; the meaning service on this machine answers from the REAL journals.
2026-11-01: with the PC service up, 5-6 prompt-hook tests in test_quick_map.py failed on "SAME MEANING" lines from
real entries. Off for every test; a test of the meaning layer turns it back on with monkeypatch (meaning.OFF)."""
import os

os.environ["JOURNAL_MEANING_OFF"] = "1"
# The relevance judge (judge.py) calls the claude command: never from tests (slow, uses the subscription, not repeatable),
# unless asked: JOURNAL_LIVE_JUDGE_TESTS=1 runs the judge's real cases (tests/test_owner_brief_20261103.py).
if not os.environ.get("JOURNAL_LIVE_JUDGE_TESTS"):
    os.environ["JOURNAL_JUDGE"] = "off"
# The real home before any test file points JOURNAL_HOME at a temporary one (test_arg_aliases does, for the whole
# run): live checks read entry bodies from it, never write.
os.environ.setdefault("JOURNAL_REAL_HOME", os.environ.get("JOURNAL_HOME") or os.path.join(os.path.expanduser("~"), ".journal"))
