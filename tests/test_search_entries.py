"""journal_search ranks by entry, so a matching entry inside a huge journal is not buried by its length.

Regression for 2026-10-24: the query "shopsite logo" missed a 5,600-line journal whose entry
"LOGO OFICIAL DE SHOPSITE" was the exact answer, because each journal was one bm25 row.

Run: python -m pytest tests  (or: python tests/test_search_entries.py)
Everything runs in a temp JOURNAL_HOME and JOURNAL_ROOTS; the real index is never touched.
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-mcp-test-"))
_HOME = _TMP / "home"
_ROOT = _TMP / "projects"
os.environ["JOURNAL_HOME"] = str(_HOME)
os.environ["JOURNAL_ROOTS"] = str(_ROOT)
os.environ.pop("JOURNAL_EXTRA_DOCS", None)

_WORDS = ("deploy build cache worker queue retry render upload invoice server panel button layout color "
          "script config route token session preview release backup review metric chart sprite audio "
          "track reel caption hashtag schedule cron webhook database migration index timeout").split()


def _write(rel: str, text: str) -> Path:
    p = _ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _huge_journal() -> str:
    rnd = random.Random(7)
    out = ["# BIG SITE JOURNAL", "", "## Current state", "", "- the site is live", ""]
    n = 0
    while len(out) < 5000:
        n += 1
        out.append(f"## 2026-09-{(n % 28) + 1:02d} 10:{n % 60:02d} [ops] routine change {n}")
        out.append("")
        for _ in range(rnd.randint(4, 12)):
            out.append("- " + " ".join(rnd.choice(_WORDS) for _ in range(12)))
        out.append("")
    out += ["## 2026-10-15 15:32 [brand] LOGO OFICIAL DE SHOPSITE (el del header del sitio)", "",
            "El logo oficial es SOLO el infinito (InfinityGlyph). El wordmark es aparte.", ""]
    while len(out) < 5300:
        n += 1
        out.append(f"## 2026-10-{(n % 28) + 1:02d} 11:00 [ops] routine change {n}")
        out.append("- " + " ".join(rnd.choice(_WORDS) for _ in range(12)))
    return "\n".join(out) + "\n"


_write("shopsite-site/BIG_SITE_JOURNAL.md", _huge_journal())
_write("agency/AGENCY_JOURNAL.md", "# AGENCY\n\n## 2026-10-01 [client] logo refresh for a bakery\n\n"
       "Made a new logo for the bakery. Clients liked it.\n\n## 2026-10-02 [note] tools\n\n"
       "We sometimes use shopsite tools.\n")
_write("music/MUSIC_JOURNAL.md", "# MUSIC\n\n## 2026-10-03 [release]\n\nCover art with the label logo, posted on "
       "shopsite and elsewhere. shopsite shopsite.\n")
_write("saas/SAAS_JOURNAL.md", "# SAAS\n\n## 2026-10-04 [ui]\n\nSwapped the app logo in the navbar.\n\n"
       "## 2026-10-05 [growth]\n\nShared a shopsite link.\n")
_write("notes/NOTES_JOURNAL.md", "# NOTES\n\nvibedna logo logo shopsite mentioned once in passing.\n" + "filler line\n" * 40)

_spec = importlib.util.spec_from_file_location("journal_server", Path(__file__).resolve().parents[1] / "server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)
srv._index_refresh_internal()


def _search(q: str) -> dict:
    return srv._journal_search_impl(q, limit=10)


def _logo_entry(r: dict) -> list:
    return [e for e in r.get("entries", []) if "LOGO OFICIAL DE SHOPSITE" in e["heading"]]


def test_huge_journal_ranks_first_for_shopsite_logo():
    res = _search("shopsite logo")
    top = res["matches"][0]
    assert top["name"] == "BIG_SITE_JOURNAL.md", [m["name"] for m in res["matches"]]
    assert _logo_entry(top), top["entries"]
    assert _logo_entry(top)[0]["line"] > 5000


def test_spanish_query_logo_oficial_shopsite():
    res = _search("logo oficial shopsite")
    top = res["matches"][0]
    assert top["name"] == "BIG_SITE_JOURNAL.md", [m["name"] for m in res["matches"]]
    assert _logo_entry(top)


def test_english_synonym_official_logo():
    res = _search("official shopsite logo")
    assert res["matches"][0]["name"] == "BIG_SITE_JOURNAL.md"


def test_response_shape_kept():
    m = _search("shopsite logo")["matches"][0]
    for k in ("name", "project", "path", "score", "snippet", "updated_ago", "entries"):
        assert k in m, k
    assert len(m["entries"]) <= 3
    for e in m["entries"]:
        assert set(e) == {"heading", "line", "snippet"}


def test_one_result_per_journal_and_or_recall():
    res = _search("shopsite logo")
    names = [m["name"] for m in res["matches"]]
    assert len(names) == len(set(names))
    # OR recall: journals that mention only one of the words still show up.
    assert "SAAS_JOURNAL.md" in names and "AGENCY_JOURNAL.md" in names


def test_all_terms_entry_beats_partial():
    res = _search("bakery refresh shopsite")
    assert res["matches"][0]["name"] == "AGENCY_JOURNAL.md"


def test_append_is_indexed_at_entry_level():
    srv.journal_append("SAAS_JOURNAL.md", "Zebracorn mascot approved for the onboarding screen.", tag="brand")
    res = _search("zebracorn mascot")
    top = res["matches"][0]
    assert top["name"] == "SAAS_JOURNAL.md"
    assert any("Zebracorn" in e["heading"] for e in top["entries"])


def test_external_edit_is_resynced():
    p = _ROOT / "music" / "MUSIC_JOURNAL.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n## 2026-10-20 [gear] Quetzalphone synth bought\n\nok\n",
                 encoding="utf-8")
    os.utime(p, None)
    res = _search("quetzalphone")
    assert res["matches"] and res["matches"][0]["name"] == "MUSIC_JOURNAL.md"


def test_long_section_is_chunked_and_keeps_heading():
    body = "\n".join(f"- line {i}" for i in range(200))
    chunks = srv._split_entries("# T\n\nintro\n\n## Big section\n" + body + "\n### Sub\ntext\n")
    big = [c for c in chunks if c[1] == "Big section"]
    assert len(big) >= 3
    assert big[0][0] == 5
    assert chunks[0][1] == "T" and "intro" in chunks[0][2]
    assert chunks[-1][1] == "Sub"


def test_headings_in_code_fences_do_not_split():
    chunks = srv._split_entries("## A\n```\n## not a heading\n```\n## B\nx\n")
    assert [c[1] for c in chunks] == ["A", "B"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
