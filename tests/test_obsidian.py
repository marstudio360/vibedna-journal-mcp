"""obsidian.py: Properties blocks for live journals and the _obsidian map, all on temp folders."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-obsidian-test-"))
os.environ.setdefault("JOURNAL_HOME", str(_TMP / "home"))
os.environ.setdefault("JOURNAL_ROOTS", str(_TMP / "projects"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import obsidian as o  # noqa: E402
import server as s  # noqa: E402
import pytest  # noqa: E402

LIVE = (
    "# Webweave\n\n## Current state\n\nruns\n\n## Handoff for next session\n\nnext\n\n"
    "## 2026-10-28 10:00 [ship] first\n\nbody names PIGMENT_STUDIO_JOURNAL.md\n\n"
    "## 2026-10-30 00:26 [fix] second\n\nbody\n"
)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "vault"
    (r / "web").mkdir(parents=True)
    (r / "pigment").mkdir()
    (r / "node_modules" / "x").mkdir(parents=True)
    (r / "journals-drafts").mkdir()
    (r / "src" / "deep").mkdir(parents=True)
    (r / "web" / "WEBWEAVE_JOURNAL.md").write_bytes(LIVE.encode("utf-8"))
    # CRLF + BOM, a colon heading that must not be linked, no Handoff
    (r / "pigment" / "PIGMENT_STUDIO_JOURNAL.md").write_bytes(
        b"\xef\xbb\xbf# Pigment\r\n\r\n## Current state: busy\r\n\r\nx\r\n\r\n## 2026-09-01 [note] old one\r\n")
    (r / "HAS_FM_JOURNAL.md").write_text("---\ntitle: kept\n---\n\n# Kept\n\n## Current state\n", encoding="utf-8")
    (r / "node_modules" / "x" / "PKG_JOURNAL.md").write_text("# no\n", encoding="utf-8")
    (r / "journals-drafts" / "sold-guide.md").write_text("---\nkind: refined\n---\n# Sold\n", encoding="utf-8")
    (r / "src" / "deep" / "main.py").write_text("print(1)\n", encoding="utf-8")
    return r


def _snapshot(r: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in r.rglob("*") if p.is_file()}


def test_find_journals_uses_the_server_rules(root):
    found = {p.name for _, p in o.find_journals([root])}
    assert found == {"WEBWEAVE_JOURNAL.md", "PIGMENT_STUDIO_JOURNAL.md", "HAS_FM_JOURNAL.md"}
    assert o.rules()[1] is s._is_journal_path


def test_project_slug():
    assert o.project_slug(Path("JOURNAL_MCP_JOURNAL.md")) == ("journal-mcp", "Journal MCP")
    assert o.project_slug(Path("AI_TEAM_JOURNAL.md")) == ("ai-team", "AI team")
    assert o.project_slug(Path("Tone Garden/journal.md")) == ("tone-garden", "Tone garden")
    assert o.project_slug(Path("SOCIAL_SYSTEM_JOURNAL_USER.md"))[0] == "social-system-user"


def test_dry_run_changes_nothing(root):
    before = _snapshot(root)
    rep = o.add_frontmatter([root], apply=False)
    assert rep["journals"] == 3
    assert sorted(Path(p).name for p in rep["would_add"]) == ["PIGMENT_STUDIO_JOURNAL.md", "WEBWEAVE_JOURNAL.md"]
    assert [Path(p).name for p in rep["has_frontmatter"]] == ["HAS_FM_JOURNAL.md"]
    assert rep["added"] == []
    assert _snapshot(root) == before
    o.build_vault(root, apply=False)
    assert _snapshot(root) == before


def test_apply_adds_the_block_once_and_keeps_the_body(root):
    web = root / "web" / "WEBWEAVE_JOURNAL.md"
    pal = root / "pigment" / "PIGMENT_STUDIO_JOURNAL.md"
    fm = root / "HAS_FM_JOURNAL.md"
    web0, pal0, fm0 = web.read_bytes(), pal.read_bytes(), fm.read_bytes()
    rep = o.add_frontmatter([root], apply=True)
    assert len(rep["added"]) == 2 and not rep["errors"] and not rep["changed"]

    web1 = web.read_bytes()
    block = web1[: len(web1) - len(web0)].decode("utf-8")
    assert web1.endswith(web0)
    assert block == (
        "---\ntype: journal\nproject: webweave\nstatus: live\ntags: [journal, project/webweave]\n"
        'aliases: ["Webweave journal"]\nupdated: 2026-10-30T00:26:00\nentries: 2\n---\n'
    )
    pal1 = pal.read_bytes()
    assert pal1.startswith(b"\xef\xbb\xbf---\r\ntype: journal\r\n")
    assert pal1.endswith(pal0[3:])
    assert b"updated: 2026-09-01T00:00:00\r\nentries: 1\r\n---\r\n" in pal1
    assert fm.read_bytes() == fm0

    meta = s._parse_frontmatter(web1.decode("utf-8"))
    assert meta["type"] == "journal" and meta["project"] == "webweave"
    assert s._classify_kind(str(web), meta) == "raw"

    snap = _snapshot(root)
    rep2 = o.add_frontmatter([root], apply=True)
    assert rep2["added"] == [] and len(rep2["has_frontmatter"]) == 3
    assert _snapshot(root) == snap
    assert not [p for p in root.rglob("*") if p.name.endswith((".obsidian-tmp", ".tmp"))]


def test_file_changed_while_writing_is_left_alone(root, monkeypatch):
    web = root / "web" / "WEBWEAVE_JOURNAL.md"
    real_fsync = os.fsync

    def append_meanwhile(fd):
        real_fsync(fd)
        with open(web, "a", encoding="utf-8") as fh:
            fh.write("\n## 2026-10-30 01:00 [late] another session wrote this\n")

    monkeypatch.setattr(o.os, "fsync", append_meanwhile)
    rep = o.add_frontmatter([root / "web"], apply=True)
    assert [Path(p).name for p in rep["changed"]] == ["WEBWEAVE_JOURNAL.md"] and rep["added"] == []
    text = web.read_text(encoding="utf-8")
    assert not text.startswith("---") and text.endswith("another session wrote this\n")
    assert not [p for p in web.parent.iterdir() if p.name.endswith(".obsidian-tmp")]


def test_big_and_read_only_files_are_skipped(root, monkeypatch):
    monkeypatch.setattr(o, "MAX_BYTES", 100)
    rep = o.add_frontmatter([root], apply=True)
    assert [Path(p).name for p, _ in rep["too_big"]] == ["WEBWEAVE_JOURNAL.md"]
    assert not (root / "web" / "WEBWEAVE_JOURNAL.md").read_text(encoding="utf-8").startswith("---")
    monkeypatch.setattr(o, "MAX_BYTES", 5 * 1024 * 1024)
    web = root / "web" / "WEBWEAVE_JOURNAL.md"
    os.chmod(web, 0o444)
    try:
        rep = o.add_frontmatter([root / "web"], apply=True)
        assert [Path(p).name for p in rep["read_only"]] == ["WEBWEAVE_JOURNAL.md"] and rep["added"] == []
    finally:
        os.chmod(web, 0o666)


_LINK = re.compile(r"\[\[([^\]]+?)\]\]")


def test_vault_outputs(root):
    rep = o.build_vault(root, apply=True)
    assert rep["written"] and rep["journals"] == 3
    out = root / o.OUT_DIR
    assert {p.name for p in out.iterdir()} == {"START HERE.md", "Journals.base", "Journals map.canvas"}
    assert not (root / ".obsidian" / "workspace.json").exists()

    # START HERE: every link points to an existing file, and a heading link only to a clean heading it has
    md = (out / "START HERE.md").read_text(encoding="utf-8")
    links = _LINK.findall(md)
    assert links
    for link in links:
        target = link.split("\\|")[0].split("|")[0]
        path, _, heading = target.partition("#")
        f = root / (path + ".md")
        assert f.is_file(), link
        if heading:
            assert not set(heading) & set(":|#^[]%")
            assert f"## {heading}\n" in f.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "web/WEBWEAVE_JOURNAL#Current state" in md and "web/WEBWEAVE_JOURNAL#Handoff for next session" in md
    assert "PIGMENT_STUDIO_JOURNAL#" not in md  # "Current state: busy" is not clean, and no Handoff
    assert "`WEBWEAVE_JOURNAL.md` line 15: \\[fix\\] second" in md
    assert chr(0x2014) not in md and chr(0x2013) not in md

    # Canvas: JSON Canvas 1.0 shape
    canvas = json.loads((out / "Journals map.canvas").read_text(encoding="utf-8"))
    assert set(canvas) == {"nodes", "edges"}
    ids = [n["id"] for n in canvas["nodes"]]
    assert len(ids) == len(set(ids))
    files = [n for n in canvas["nodes"] if n["type"] == "file"]
    groups = [n for n in canvas["nodes"] if n["type"] == "group"]
    assert {n["label"] for n in groups} == {"web", "pigment", "(root)"}
    for n in canvas["nodes"]:
        assert {"id", "type", "x", "y", "width", "height"} <= set(n)
    for n in files:
        assert (root / n["file"]).is_file()
        g = next(g for g in groups if g["x"] <= n["x"] and g["y"] <= n["y"]
                 and n["x"] + n["width"] <= g["x"] + g["width"] and n["y"] + n["height"] <= g["y"] + g["height"])
        assert g["label"] == (n["file"].split("/")[0] if "/" in n["file"] else "(root)")
    web_node = next(n for n in files if n["file"] == "web/WEBWEAVE_JOURNAL.md")
    assert web_node["subpath"] == "#Current state"
    assert "subpath" not in next(n for n in files if n["file"].startswith("pigment/"))
    by_id = {n["id"]: n for n in files}
    edges = [(by_id[e["fromNode"]]["file"], by_id[e["toNode"]]["file"]) for e in canvas["edges"]]
    assert edges == [("web/WEBWEAVE_JOURNAL.md", "pigment/PIGMENT_STUDIO_JOURNAL.md")]

    # Base: basic structure without a YAML parser
    base = (out / "Journals.base").read_text(encoding="utf-8")
    top = [ln.split(":")[0] for ln in base.splitlines() if ln and not ln.startswith(" ")]
    assert top == ["filters", "properties", "views"]
    # live journals carry no frontmatter (decision 2026-10-30): the live base reads file properties only
    assert "file.name.lower().contains(\"journal\")" in base and "file.mtime" in base and "note." not in base
    assert "file.hasTag(\"journal\")" in o.make_base()
    assert re.findall(r"^  - type: (\w+)", base, re.M) == ["table", "table", "table"]
    assert re.findall(r"^    name: (.+)$", base, re.M) == ["By updated", "Stale", "Biggest"]
    assert 'now() - "14d"' in base and "\t" not in base
    sold = o.make_base()
    assert re.findall(r"^    name: (.+)$", sold, re.M) == ["By updated", "By status", "Stale"] and "groupBy:" in sold

    # Obsidian config
    app = json.loads((root / ".obsidian" / "app.json").read_text(encoding="utf-8"))
    flt = app["userIgnoreFilters"]
    assert any("node_modules" in f and f.startswith("/") for f in flt)
    assert "src/" in flt and "web/" not in flt
    cores = json.loads((root / ".obsidian" / "core-plugins.json").read_text(encoding="utf-8"))
    for k in ("properties", "bases", "canvas", "graph", "backlink", "outline", "global-search"):
        assert cores[k] is True


def test_vault_keeps_existing_obsidian_settings(root):
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text(json.dumps({"userIgnoreFilters": ["mine/"], "vimMode": True}),
                                                 encoding="utf-8")
    o.build_vault(root, apply=True)
    o.build_vault(root, apply=True)
    app = json.loads((root / ".obsidian" / "app.json").read_text(encoding="utf-8"))
    assert app["vimMode"] is True and app["userIgnoreFilters"][0] == "mine/"
    assert len(app["userIgnoreFilters"]) == len(set(app["userIgnoreFilters"]))


def test_outputs_are_never_indexed_as_journals(root):
    o.build_vault(root, apply=True)
    o.add_frontmatter([root], apply=True)
    made = [p for p in (root / o.OUT_DIR).rglob("*")] + [p for p in (root / ".obsidian").rglob("*")]
    assert made
    assert not [p for p in made if s._is_journal_path(p)]
    found = []
    s._scan_root(root, found)
    assert not [r for r in found if o.OUT_DIR in r["path"] or ".obsidian" in r["path"]]
    assert {r["name"] for r in found if r["kind"] == "raw"} == {
        "WEBWEAVE_JOURNAL.md", "PIGMENT_STUDIO_JOURNAL.md", "HAS_FM_JOURNAL.md"}


def test_yaml_scalars_are_safe():
    assert o._yaml_scalar("live") == "live"
    assert o._yaml_scalar("yes") == "'yes'"
    assert o._yaml_scalar('file.hasTag("journal")') == "'file.hasTag(\"journal\")'"
    assert o._yaml_scalar("it's: x") == "'it''s: x'"


def test_archive_moves_old_months_in_two_steps_and_keeps_living_sections(tmp_path):
    """Owner GO 2026-10-30: split TONE_GARDEN_JOURNAL.md (2.5 MB) by month. Living sections stay, a sub-section of an
    old entry moves with it, nothing is lost, an entry appended between the steps is kept, CRLF is kept."""
    j = tmp_path / "SHOP_JOURNAL.md"
    text = ("# SHOP\r\n\r\n## Pending now\r\n- [ ] a\r\n\r\n## 2026-08-01 10:00 [ship] old one\r\nbody\r\n\r\n"
            "## A sub-section of the old entry\r\nmore\r\n\r\n## 2026-09-02 11:00 [fix] sept\r\nx\r\n\r\n"
            "## Handoff for next session\r\nlive handoff\r\n\r\n## 2026-10-03 12:00 [ship] october\r\ny\r\n")
    j.write_bytes(text.encode())
    dry = o.archive_write(j, "2026-10")
    assert dry["moving_blocks"] == 3 and set(dry["months"]) == {"2026-08", "2026-09"} and j.read_bytes() == text.encode()
    o.archive_write(j, "2026-10", apply=True)
    assert j.read_bytes() == text.encode()  # step 1 never touches the journal
    a8 = (tmp_path / "SHOP_JOURNAL_2026-08.md").read_bytes().decode()
    assert "old one" in a8 and "A sub-section of the old entry" in a8 and "sept" not in a8
    with open(j, "ab") as fh:  # another session appends between the steps
        fh.write(b"\r\n## 2026-10-04 09:00 [ship] appended later\r\nz\r\n")
    rep = o.archive_trim(j, apply=True)
    assert rep["ok"], rep
    out = j.read_bytes().decode()
    for keep in ("## Pending now", "## Handoff for next session", "october", "appended later", "[[SHOP_JOURNAL_2026-08]]"):
        assert keep in out, keep
    for gone in ("old one", "A sub-section of the old entry", "[fix] sept"):
        assert gone not in out, gone
    assert "\r\n" in out and "\n\n## 2026" not in out.replace("\r\n", "\r\n")
    assert (tmp_path / "_archive" / "SHOP_JOURNAL.full_" ).parent.exists()


def test_archive_trim_refuses_when_a_month_file_lost_an_entry(tmp_path):
    j = tmp_path / "SHOP_JOURNAL.md"
    j.write_bytes(b"# S\n\n## 2026-08-01 10:00 [ship] old\nbody\n\n## 2026-10-03 12:00 [ship] new\ny\n")
    o.archive_write(j, "2026-10", apply=True)
    (tmp_path / "SHOP_JOURNAL_2026-08.md").write_text("# emptied by mistake\n", encoding="utf-8")
    rep = o.archive_trim(j, apply=True)
    assert not rep["ok"] and "missing" in rep["why"]
    assert b"[ship] old" in j.read_bytes()
