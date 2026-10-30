"""Live journals may start with an Obsidian YAML frontmatter block (2026-10-30), and nothing may break:
title, head, handoff brief, kind, aliases, search, reindex, append, update_section and create.

Everything runs in a temp JOURNAL_HOME and JOURNAL_ROOTS; the real index is never touched.
"""
from __future__ import annotations

import datetime
import importlib.util
import os
import re
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="journal-frontmatter-test-"))
_HOME = _TMP / "home"
_ROOT = _TMP / "projects"
os.environ["JOURNAL_HOME"] = str(_HOME)
os.environ.pop("JOURNAL_EXTRA_DOCS", None)

_spec = importlib.util.spec_from_file_location("journal_server_fm", Path(__file__).resolve().parents[1] / "server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

BLOCK = """---
type: journal
project: tone-garden
status: live
tags: [journal, project/tone-garden]
aliases: ["Tone Garden journal"]
updated: 2026-10-30T00:26:00
entries: 1259
---
"""
BODY = """# TONE GARDEN JOURNAL

Intro line one.
Intro line two.

## Current state

- the store is open

## Handoff for next session

- [ ] ship the pack

## Recent entries

## 2026-10-28 10:00 [ship] first entry

Shipped the zebracorn pack.

---

## 2026-10-29 11:00 [fix] second entry

Fixed the checkout.

---
"""


def _write(rel: str, text: str) -> Path:
    p = _ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def aa(monkeypatch):
    monkeypatch.setenv("JOURNAL_ROOTS", str(_ROOT))
    p = _write("TONE GARDEN/TONE_GARDEN_JOURNAL.md", BLOCK + BODY)
    srv._index_refresh_internal()
    return p


def _row(path: Path, cols: str = "kind, title, head, tags"):
    c = srv._conn()
    try:
        return c.execute(f"SELECT {cols} FROM journals WHERE path = ?", (str(path),)).fetchone()
    finally:
        c.close()


def _block_lines(text: str) -> list[str]:
    n, _ = srv._frontmatter_span(text)
    return text.splitlines()[:n]


# ─── parsing ───────────────────────────────────────────────────────────────

def test_lists_inline_and_block():
    fm = srv.parse_frontmatter_lists(BLOCK + BODY)
    assert fm["aliases"] == ["Tone Garden journal"]
    assert fm["tags"] == ["journal", "project/tone-garden"]
    assert fm["type"] == ["journal"] and fm["entries"] == ["1259"]
    block = "---\ntype: journal\naliases:\n  - Tone Garden journal\n  - 'AA, the shop'\ntags:\n- a\n- b\n---\n# T\n"
    fm = srv.parse_frontmatter_lists(block)
    assert fm["aliases"] == ["Tone Garden journal", "AA, the shop"] and fm["tags"] == ["a", "b"]
    assert srv._parse_frontmatter(block)["tags"] == "a, b"
    assert srv.parse_frontmatter_lists(BODY) == {}
    bom = "\ufeff" + BLOCK + BODY   # a file saved with a BOM (Windows editors)
    assert srv.parse_frontmatter_lists(bom)["aliases"] == ["Tone Garden journal"]
    assert srv._first_h1(bom) == "TONE GARDEN JOURNAL" and srv._head(bom).startswith("# TONE")


def test_rule_and_h1_are_not_frontmatter():
    text = "---\n# Old style title\n---\n\nbody\n"
    assert srv._frontmatter_span(text) == (0, 0)
    assert srv._first_h1(text) == "Old style title"
    assert srv._frontmatter_span("---\nno closing line\ntype: journal\n") == (0, 0)
    assert srv._frontmatter_span("---\n\n---\n# Title after two rules\n") == (0, 0)
    assert srv._head("---\n\n---\n# T\n").startswith("---")


def test_title_head_and_kind_after_refresh(aa):
    kind, title, head, tags = _row(aa)
    assert title == "TONE GARDEN JOURNAL"
    assert head.startswith("# TONE GARDEN JOURNAL") and "type: journal" not in head
    assert kind == "raw"
    assert tags == "journal, project/tone-garden"


def test_type_journal_never_reclassifies():
    assert srv._classify_kind("/x/journals-refined/A_JOURNAL.md", {"type": "journal"}) == "raw"
    assert srv._classify_kind("/x/skills/A_JOURNAL.md", {"type": "journal"}) == "raw"
    assert srv._classify_kind("/x/A_JOURNAL.md", {"type": "journal", "kind": "refined"}) == "refined"
    assert srv._classify_kind("/x/A_JOURNAL.md", {"type": "journal", "kind": "skill"}) == "skill"


def test_aliases_resolve_from_frontmatter(aa):
    names = srv._journal_aliases(str(aa), "")
    assert "Tone Garden journal" in names
    assert not any("[" in n or '"' in n for n in names), names
    assert srv._resolve("Tone Garden journal")["path"] == str(aa)


# ─── reading ───────────────────────────────────────────────────────────────

def test_handoff_brief_head_skips_frontmatter(aa):
    brief = srv.journal_handoff_brief(str(aa))
    head = brief.split("\n\n", 1)[0]
    assert head.startswith("# TONE GARDEN JOURNAL"), head
    assert "Intro line two." in head
    for key in ("type: journal", "entries: 1259", "aliases:", "updated:"):
        assert key not in brief
    assert "ship the pack" in brief


def test_search_still_finds_entries(aa):
    r = srv._journal_search_impl("zebracorn", limit=5)
    top = r["matches"][0]
    assert top["name"] == "TONE_GARDEN_JOURNAL.md"
    assert any("first entry" in e["heading"] for e in top["entries"]), top["entries"]
    first = next(e for e in top["entries"] if "first entry" in e["heading"])
    assert aa.read_text(encoding="utf-8").splitlines()[first["line"] - 1].startswith("## 2026-10-28 10:00")
    c = srv._conn()
    try:
        bodies = [b for (b,) in c.execute("SELECT body FROM entries_fts WHERE path = ?", (str(aa),)).fetchall()]
    finally:
        c.close()
    assert bodies and not any("type: journal" in b or "entries: 1259" in b for b in bodies)


def test_reindex_keeps_an_extra_doc_a_doc(monkeypatch):
    monkeypatch.setenv("JOURNAL_ROOTS", str(_ROOT))
    p = _write("docs/TOOL_JUICE.md", "# Tool juice\n\nwhat the tool does\n")
    c = srv._conn()
    try:
        c.execute("INSERT OR REPLACE INTO journals(path, name, project, kind, title) VALUES(?,?,?,?,?)",
                  (str(p), p.name, "docs", "doc", "Tool juice"))
        c.commit()
        p.write_text("# Tool juice v2\n\nmore\n", encoding="utf-8")
        srv._reindex_path(c, str(p))
        c.commit()
    finally:
        c.close()
    kind, title, head, tags = _row(p)
    assert kind == "doc" and title == "Tool juice v2" and head.startswith("# Tool juice v2")


def test_reindex_refreshes_metadata(aa):
    text = aa.read_text(encoding="utf-8")
    aa.write_text(text.replace("tags: [journal, project/tone-garden]", "tags: [journal, music]")
                  .replace("# TONE GARDEN JOURNAL", "# TONE GARDEN RENAMED"), encoding="utf-8")
    c = srv._conn()
    try:
        srv._reindex_path(c, str(aa))
        c.commit()
    finally:
        c.close()
    kind, title, head, tags = _row(aa)
    assert tags == "journal, music"
    assert title == "TONE GARDEN RENAMED" and head.startswith("# TONE GARDEN RENAMED")
    assert kind == "raw"


# ─── writing ───────────────────────────────────────────────────────────────

def test_append_keeps_block_and_bumps_updated_and_entries(aa):
    before = _block_lines(aa.read_text(encoding="utf-8"))
    r = srv.journal_append(str(aa), entry="Third entry about the shop layout", tag="note")
    assert r["ok"]
    text = aa.read_text(encoding="utf-8")
    after = _block_lines(text)
    assert [ln.split(":", 1)[0] for ln in after] == [ln.split(":", 1)[0] for ln in before]
    changed = {ln.split(":", 1)[0] for ln, old in zip(after, before) if ln != old}
    assert changed == {"updated", "entries"}
    assert "entries: 3" in after
    heading = re.search(r"^## (\d{4}-\d\d-\d\d) (\d\d:\d\d) \[note\] Third entry", text, re.M)
    assert heading, text[-300:]
    assert f"updated: {heading.group(1)}T{heading.group(2)}:00" in after
    assert text.endswith("Third entry about the shop layout\n\n---\n")
    assert not list(aa.parent.glob("*.tmp"))


def test_append_never_adds_a_block(monkeypatch):
    monkeypatch.setenv("JOURNAL_ROOTS", str(_ROOT))
    p = _write("PLAIN/PLAIN_JOURNAL.md", BODY)
    srv._index_refresh_internal()
    assert srv.journal_append(str(p), entry="plain entry", tag="note")["ok"]
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# TONE GARDEN JOURNAL") and srv._frontmatter_span(text) == (0, 0)


def test_update_section_keeps_block(aa):
    before = _block_lines(aa.read_text(encoding="utf-8"))
    r = srv.journal_update_section(str(aa), section="Current state", new_content="- the store is closed for a day")
    assert r["ok"] and not r.get("created")
    text = aa.read_text(encoding="utf-8")
    after = _block_lines(text)
    assert len(after) == len(before)
    assert {ln.split(":", 1)[0] for ln, old in zip(after, before) if ln != old} <= {"updated", "entries"}
    assert "entries: 2" in after
    assert srv._parse_frontmatter(text)["updated"].startswith(datetime.date.today().isoformat())
    assert "the store is closed for a day" in text and "type: journal" in text
    r = srv.journal_update_section(str(aa), section="Pending now", new_content="- [ ] one thing")
    assert r["ok"] and r.get("created")
    text = aa.read_text(encoding="utf-8")
    assert text.startswith("---\ntype: journal\n") and _block_lines(text)[1:6] == before[1:6]


def test_refresh_frontmatter_only_touches_two_values():
    text = BLOCK + BODY
    now = datetime.datetime(2026, 10, 31, 9, 41, 27)
    out = srv._refresh_frontmatter(text, now)
    assert out.replace("updated: 2026-10-31T09:41:00", "updated: 2026-10-30T00:26:00").replace(
        "entries: 2", "entries: 1259") == text
    assert srv._refresh_frontmatter(BODY, now) == BODY


def test_create_starts_with_frontmatter(monkeypatch):
    monkeypatch.setenv("JOURNAL_ROOTS", str(_ROOT))
    d = _ROOT / "NEW THING"
    d.mkdir(parents=True, exist_ok=True)
    r = srv.journal_create("NEW_THING_JOURNAL.md", str(d))
    assert r["ok"]
    text = Path(r["path"]).read_text(encoding="utf-8")
    fm = srv.parse_frontmatter_lists(text)
    assert list(fm) == ["type", "project", "status", "tags", "aliases", "updated", "entries"]
    assert fm["type"] == ["journal"] and fm["project"] == ["new-thing"] and fm["status"] == ["live"]
    assert fm["tags"] == ["journal", "project/new-thing"] and fm["aliases"] == ["New Thing journal"]
    assert fm["entries"] == ["0"]
    assert srv._first_h1(text) == "New Thing Journal"
    assert srv.journal_append(r["path"], entry="hello", tag="note")["ok"]
    assert srv._parse_frontmatter(Path(r["path"]).read_text(encoding="utf-8"))["entries"] == "1"
