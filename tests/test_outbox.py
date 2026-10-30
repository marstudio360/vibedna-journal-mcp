"""A read-only journal (a mirror a sync overwrites) must not fail journal_append: the entry goes to the outbox."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-outbox-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def journal(monkeypatch, tmp_path):
    f = tmp_path / "MIRROR_JOURNAL.md"
    f.write_text("# MIRROR\n\n## Current state\n\nbody\n", encoding="utf-8")
    monkeypatch.setattr(s, "_resolve", lambda q: {"path": str(f), "name": f.name} if q == f.name else None)
    monkeypatch.setenv("JOURNAL_OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.setenv("JOURNAL_FROM", "builder")
    yield f
    os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


def test_read_only_journal_goes_to_the_outbox(journal):
    os.chmod(journal, stat.S_IREAD)
    before = journal.read_text(encoding="utf-8")
    r = s.journal_append(journal.name, entry="Box finding\nsecond line", tag="learned", section_header="Learned")
    assert r["ok"] and r["queued"]
    assert r["message"] == "queued for the master journal (it lands on the next sync)"
    assert journal.read_text(encoding="utf-8") == before
    lines = (journal.parent / "outbox" / "MIRROR_JOURNAL.md.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["journal"] == "MIRROR_JOURNAL.md" and rec["tag"] == "learned"
    assert rec["entry"] == "Box finding\nsecond line" and rec["section_header"] == "Learned"
    assert rec["from_role"] == "builder" and rec["at"].endswith("+00:00") and rec["id"]
    s.journal_append(journal.name, entry="another", tag="ship")
    assert len((journal.parent / "outbox" / "MIRROR_JOURNAL.md.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_writable_journal_is_written_not_queued(journal):
    r = s.journal_append(journal.name, entry="normal entry", tag="fix")
    assert r["ok"] and not r.get("queued")
    assert "[fix] normal entry" in journal.read_text(encoding="utf-8")
    assert not (journal.parent / "outbox").exists()


def test_outbox_default_is_under_home(monkeypatch):
    monkeypatch.delenv("JOURNAL_OUTBOX", raising=False)
    assert s._outbox_dir() == Path.home() / "journal-outbox"
