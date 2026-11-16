"""growth.py: the page that plays how the journals grew."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import growth  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _own_journal_home(tmp_path, monkeypatch):
    """Never the real journal home: the meaning neighbours read its index and keep a file next to the map."""
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path / "journal-home"))


LO, HI = date(2015, 1, 1), date(2100, 1, 1)
TEXT = """# Shop journal

## Decided

One line each.
- **Prices end in 7** · date: 2026-03-02 · why: owner
- **No date on this one**

## 2026-03-01 09:30 [ship] Store is live
Five words in this body.

## 2026-03-02 [fix] Checkout button
Two words.

## 2099-13-40 broken date
skipped
"""


def test_parse_entries_and_cards():
    entries, cards = growth.parse_journal(TEXT, LO, HI)
    assert [(e[0].isoformat(), e[1], e[2], e[3]) for e in entries] == [
        ("2026-03-01", 570, growth.KIND_SHIP, 5), ("2026-03-02", 0, growth.KIND_FIX, 2)]
    assert cards == [date(2026, 3, 2)]


def test_pretty_names():
    assert growth.pretty("OWNER_VOICE_JOURNAL_DIRECTION") == "Owner Voice Direction"
    assert growth.pretty("SOCIAL_SYSTEM_JOURNAL_USER") == "Social System"
    assert growth.pretty("JOURNAL_MCP_JOURNAL") == "Journal MCP"
    assert growth.pretty("MyShop_JOURNAL") == "MyShop"


def test_month_files_fold_and_names_hide(tmp_path):
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text(TEXT, encoding="utf-8")
    b = tmp_path / "SHOP_JOURNAL_2026-02.md"
    b.write_text("## 2026-02-10 10:00 [work] Older month\nbody here\n", encoding="utf-8")
    c = tmp_path / "sub" / "OTHER_JOURNAL.md"
    c.parent.mkdir()
    c.write_text("## 2026-03-05 08:00 [work] Reads SHOP_JOURNAL twice, SHOP_JOURNAL\nx\n", encoding="utf-8")
    books = growth.collect([(tmp_path, a), (tmp_path, b), (tmp_path, c)])
    assert sorted(books) == ["OTHER_JOURNAL", "SHOP_JOURNAL"]
    assert len(books["SHOP_JOURNAL"]["entries"]) == 3
    data = growth.build_data(books)
    assert data["totals"] == {"journals": 2, "entries": 4, "decisions": 1, "words": 10}
    assert data["day0"] == "2026-02-10" and data["links"] == [[0, 1, 2]]
    assert [j["n"] for j in data["journals"]] == ["Shop", "Other"]
    hidden = growth.build_data(books, hide_names=True)
    assert [j["n"] for j in hidden["journals"]] == ["Project 1", "Project 2"]
    assert "Shop" not in json.dumps(hidden)
    out = growth.render(hidden, tmp_path / "out" / "page.html")
    page = out.read_text(encoding="utf-8")
    assert "/*DATA*/null" not in page and '"hidden":true' in page


def test_skip_leaves_a_journal_out(tmp_path):
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text(TEXT, encoding="utf-8")
    b = tmp_path / "RAW_LOG_JOURNAL.md"
    b.write_text("## 2026-03-03 10:00 [log] line" + chr(10) + "x" + chr(10), encoding="utf-8")
    assert sorted(growth.collect([(tmp_path, a), (tmp_path, b)])) == ["RAW_LOG_JOURNAL", "SHOP_JOURNAL"]
    assert sorted(growth.collect([(tmp_path, a), (tmp_path, b)], skip=["raw_log"])) == ["SHOP_JOURNAL"]


def test_live_rebuilds_only_when_a_journal_changes(tmp_path):
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text(TEXT, encoding="utf-8")
    out = tmp_path / "out" / "page.html"
    live = growth.Live([tmp_path], out, list_every=0)
    live.pairs = [(tmp_path, a)]
    live.listed_at = 10 ** 12
    assert live.tick() is True and out.exists()
    assert live.tick() is False
    with a.open("a", encoding="utf-8") as f:
        f.write(chr(10) + "## 2026-03-09 12:00 [work] One more </script> entry" + chr(10) + "body" + chr(10))
    assert live.tick() is True
    page = out.read_text(encoding="utf-8")
    assert page.count("</script>") == 2 and "One more <" in page
    data = growth.build_data(growth.collect(live.pairs))
    assert data["recent"][-1][2].startswith("[work] One more") and len(data["journals"][0]["k"]) == 8
    # the live page keeps the names hidden or invented when asked (2026-11-14: --serve ignored --demo-names)
    shown = growth.Live([tmp_path], tmp_path / "out" / "demo.html", list_every=0, demo=True)
    shown.pairs, shown.listed_at = [(tmp_path, a)], 10 ** 12
    assert shown.tick() is True
    demo = (tmp_path / "out" / "demo.html").read_text(encoding="utf-8")
    assert "Online Store" in demo and "Shop" not in demo and "One more" not in demo


def test_neighbours_file_and_quick_map_line(tmp_path):
    import neighbours
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text(TEXT + chr(10) + "## 2026-03-06 09:00 [work] See OTHER_JOURNAL and OTHER_JOURNAL" + chr(10) + "x" + chr(10), encoding="utf-8")
    c = tmp_path / "OTHER_JOURNAL.md"
    c.write_text("## 2026-03-05 08:00 [work] Reads SHOP_JOURNAL" + chr(10) + "x" + chr(10), encoding="utf-8")
    d = tmp_path / "ALONE_JOURNAL.md"
    d.write_text("## 2026-03-05 08:00 [work] Nothing named" + chr(10) + "x" + chr(10), encoding="utf-8")
    books = growth.collect([(tmp_path, a), (tmp_path, c), (tmp_path, d)])
    near = growth.neighbours(books)
    assert near["SHOP_JOURNAL"] == [["OTHER_JOURNAL", 3, "2026-03-05", 0, 0, "Reads SHOP_JOURNAL"]] and "ALONE_JOURNAL" not in near
    f = growth.write_neighbours(books, tmp_path / "out")
    assert neighbours.of("SHOP_JOURNAL_2026-02.md", f) == near["SHOP_JOURNAL"]
    line = neighbours.line_for(["SHOP_JOURNAL.md"], path=f)
    assert line.startswith("- NEIGHBOURS")
    assert 'SHOP_JOURNAL: OTHER_JOURNAL (names it 3 times; newest 03-05 "Reads SHOP_JOURNAL")' in line
    assert neighbours.line_for(["SHOP_JOURNAL.md", "OTHER_JOURNAL.md"], path=f) == ""
    assert neighbours.line_for(["ALONE_JOURNAL.md"], path=f) == ""
    assert neighbours.line_for(["SHOP_JOURNAL.md"], path=tmp_path / "missing.json") == ""


def test_neighbours_by_shared_decisions_and_by_meaning(tmp_path):
    import neighbours
    card = "- **Every price on the site ends in 7, never in 9** · date: 2026-03-02 · why: owner"
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text("## Decided\n" + card + "\n- **Ads follow the store prices** · see: ADS_JOURNAL 2026-03-02\n\n"
                 "## 2026-03-01 09:30 [ship] Store is live\nbody\n", encoding="utf-8")
    b = tmp_path / "LANDING_JOURNAL.md"
    b.write_text("## Decided\n" + card + "\n\n## 2026-03-03 10:00 [work] Hero section\nbody\n", encoding="utf-8")
    c = tmp_path / "ADS_JOURNAL.md"
    c.write_text("## 2026-03-04 11:00 [work] First ad set\nbody\n", encoding="utf-8")
    d = tmp_path / "MUSIC_JOURNAL.md"
    d.write_text("## 2026-03-05 12:00 [work] New loop pack\nbody\n", encoding="utf-8")
    books = growth.collect([(tmp_path, p) for p in (a, b, c, d)])
    near = growth.neighbours(books, meaning={("MUSIC_JOURNAL", "SHOP_JOURNAL"): 58, ("GONE_JOURNAL", "SHOP_JOURNAL"): 90})
    by = {n[0]: n for n in near["SHOP_JOURNAL"]}
    assert by["LANDING_JOURNAL"][1:5] == [0, "2026-03-03", 1, 0]      # the same decision kept in both
    assert by["ADS_JOURNAL"][1:5] == [1, "2026-03-04", 1, 0]          # a decision of one names the other
    assert by["MUSIC_JOURNAL"][1:5] == [0, "2026-03-05", 0, 58]       # same topics, never named
    assert "GONE_JOURNAL" not in by
    assert [n[0] for n in near["SHOP_JOURNAL"]][-1] == "LANDING_JOURNAL"   # ten points; ads 11, music 14.5
    assert neighbours.why(by["ADS_JOURNAL"]) == "names it 1 time, shares 1 decision"
    assert neighbours.why(by["MUSIC_JOURNAL"]) == "same topics"
    assert neighbours.why(["OLD_JOURNAL", 27, "2026-03-01"]) == "names it 27 times"   # a list from the first version
    f = growth.write_neighbours(books, tmp_path / "out", meaning={("MUSIC_JOURNAL", "SHOP_JOURNAL"): 58})
    line = neighbours.line_for(["MUSIC_JOURNAL.md"], path=f)
    assert 'MUSIC_JOURNAL: SHOP_JOURNAL (same topics; newest 03-01 "Store is live")' in line


def test_meaning_pairs_from_the_stored_vectors(tmp_path):
    np = __import__("pytest").importorskip("numpy")
    import sqlite3
    home = tmp_path / "home"
    home.mkdir()
    con = sqlite3.connect(str(home / "index.sqlite"))
    con.execute("CREATE TABLE entries_vec (path TEXT, line INTEGER, heading TEXT, h TEXT, vec BLOB, PRIMARY KEY(path, line))")
    rng = np.random.default_rng(7)
    topics = {"ADS": rng.normal(size=32), "MUSIC": rng.normal(size=32), "CODE": rng.normal(size=32)}
    files = {"SHOP_JOURNAL.md": "ADS", "ADS_JOURNAL_2026-02.md": "ADS", "ADS_JOURNAL.md": "ADS", "LOOPS_JOURNAL.md": "MUSIC",
             "SYNTH_JOURNAL.md": "MUSIC", "TOOL_JOURNAL.md": "CODE", "HOOK_JOURNAL.md": "CODE", "TINY_JOURNAL.md": "ADS"}
    for name, topic in files.items():
        for i in range(2 if name.startswith("TINY") else 6):
            v = (topics[topic] + 0.3 * rng.normal(size=32)).astype(np.float16)
            con.execute("INSERT INTO entries_vec VALUES (?,?,?,?,?)", ("C:/j/" + name, i, "h", "x", v.tobytes()))
    con.commit()
    con.close()
    keys = {"SHOP_JOURNAL", "ADS_JOURNAL", "LOOPS_JOURNAL", "SYNTH_JOURNAL", "TOOL_JOURNAL", "HOOK_JOURNAL", "TINY_JOURNAL"}
    pairs = growth.meaning_pairs(keys, home)
    assert set(pairs) == {("ADS_JOURNAL", "SHOP_JOURNAL"), ("LOOPS_JOURNAL", "SYNTH_JOURNAL"), ("HOOK_JOURNAL", "TOOL_JOURNAL")}
    assert all(60 <= n <= 100 for n in pairs.values())
    assert (home / "growth" / "neighbours_meaning.json").is_file() and growth.meaning_pairs(keys, home) == pairs
    assert growth.meaning_pairs(keys, tmp_path / "no-index-here") == {}


def test_demo_names_hide_every_real_name(tmp_path):
    a = tmp_path / "SHOP_JOURNAL.md"
    a.write_text(TEXT, encoding="utf-8")
    c = tmp_path / "OTHER_JOURNAL.md"
    c.write_text("## 2026-03-05 08:00 [work] Secret title here" + chr(10) + "x" + chr(10), encoding="utf-8")
    books = growth.collect([(tmp_path, a), (tmp_path, c)])
    data = growth.build_data(books, demo=True)
    names = [j["n"] for j in data["journals"]]
    assert sorted(names) == ["Online Store", "Paid Ads"] and names[0] == "Online Store"
    blob = json.dumps(data)
    assert "Shop" not in blob.replace("Online Store", "") and "Secret title" not in blob and data["demo"] is True
    assert growth.demo_names([5, 9, 1]) == ["Paid Ads", "Online Store", "Welcome Emails"]
    assert len(set(growth.demo_names(list(range(200))))) == 200
