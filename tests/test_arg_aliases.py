"""Agents guess argument names wrong. The tools must accept the common aliases and fail with one plain line."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-alias-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s  # noqa: E402
import pytest  # noqa: E402

_FILE = _TMP / "ALIAS_JOURNAL.md"
_FILE.write_text("# ALIAS JOURNAL\n\n## Current state\n\nold body\n\n## Handoff for next session\n\nnext steps\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _pin_resolver(monkeypatch):
    """Resolve the test journal directly, so the shared index and other test modules do not matter."""
    real = s._resolve

    def fake(name_or_path):
        if name_or_path == "ALIAS_JOURNAL.md":
            return {"path": str(_FILE), "name": "ALIAS_JOURNAL.md"}
        return real(name_or_path)
    monkeypatch.setattr(s, "_resolve", fake)

ALIASES = ["project", "journal", "name", "path"]


@pytest.mark.parametrize("alias", ALIASES)
def test_handoff_brief_accepts_alias(alias):
    out = s.journal_handoff_brief(**{alias: "ALIAS_JOURNAL.md"})
    assert "next steps" in out and "Missing" not in out


def test_handoff_brief_original_call_still_works():
    assert "next steps" in s.journal_handoff_brief("ALIAS_JOURNAL.md")
    assert "next steps" in s.journal_handoff_brief(name_or_path="ALIAS_JOURNAL.md", max_lines=40)


@pytest.mark.parametrize("alias", ALIASES)
def test_append_accepts_journal_alias(alias):
    r = s.journal_append(entry="x " + alias, tag="t", **{alias: "ALIAS_JOURNAL.md"})
    assert "error" not in r, r
    assert ("x " + alias) in _FILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("alias", ["text", "content", "body"])
def test_append_accepts_entry_alias(alias):
    r = s.journal_append("ALIAS_JOURNAL.md", **{alias: "via " + alias})
    assert "error" not in r, r
    assert ("via " + alias) in _FILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("alias", ["content", "text", "body"])
def test_update_section_accepts_new_content_alias(alias):
    r = s.journal_update_section(project="ALIAS_JOURNAL.md", section="Current state", **{alias: "fresh " + alias})
    assert "error" not in r, r
    assert ("fresh " + alias) in _FILE.read_text(encoding="utf-8")


def test_update_section_original_call_and_empty_clear():
    r = s.journal_update_section("ALIAS_JOURNAL.md", "Current state", "orig body")
    assert "error" not in r, r
    assert "orig body" in _FILE.read_text(encoding="utf-8")


def test_read_section_alias():
    out = s.journal_read_section(journal="ALIAS_JOURNAL.md", section="Handoff")
    assert "next steps" in out


def test_friendly_error_when_nothing_given():
    for call in (s.journal_handoff_brief, s.journal_read, s.journal_read_section):
        out = call()
        assert isinstance(out, str) and out.startswith("Missing 'name_or_path'") and "\n" not in out
    for call in (s.journal_append, s.journal_update_section, s.journal_verify, s.journal_audit):
        r = call()
        assert r["error"].startswith("Missing 'name_or_path'") and "Example:" in r["error"]


def test_friendly_error_for_missing_text_and_content():
    r = s.journal_append(name_or_path="ALIAS_JOURNAL.md")
    assert r["error"].startswith("Missing 'entry'")
    r = s.journal_update_section(name_or_path="ALIAS_JOURNAL.md", section="Current state")
    assert r["error"].startswith("Missing 'section/new_content'") and "content, text, body" in r["error"]
    out = s.journal_read_section(name_or_path="ALIAS_JOURNAL.md")
    assert out.startswith("Missing 'section'")
