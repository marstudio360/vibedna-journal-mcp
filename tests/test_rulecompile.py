import importlib
import json


def _load(tmp_path, monkeypatch, rules):
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path))
    (tmp_path / "compiled_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    import rulecompile
    importlib.reload(rulecompile)
    return rulecompile


DASH = {"kind": "mechanical", "on": "write", "pattern": "[\\u2013\\u2014]", "unless": "", "paths": "",
        "say": "no long dashes", "where": "CLAUDE.md:16", "rule": "no dashes"}
BRAND = {"kind": "mechanical", "on": "write", "pattern": "(?-i:\\bBrightLeaf\\b)", "unless": "", "paths": "",
         "say": "one capital", "where": "C:25", "rule": "brand"}
COPY = {"kind": "mechanical", "on": "write", "pattern": "\\bmastered\\b", "unless": "", "paths": "(?i)\\.html?$",
        "say": "not mastered", "where": "C:180", "rule": "mastered"}
VERCEL = {"kind": "mechanical", "on": "command", "pattern": "\\bvercel\\s+--prod\\b", "unless": "", "paths": "",
          "say": "ship instead", "where": "C:120", "rule": "vercel"}
JUDGE = {"kind": "judgment", "on": None, "pattern": None, "unless": "", "paths": "", "say": "", "where": "x", "rule": "y"}


def test_write_tests_catch_and_pass(tmp_path, monkeypatch):
    rc = _load(tmp_path, monkeypatch, {"a": DASH, "b": BRAND, "c": COPY, "d": JUDGE})
    assert rc.check("a new tool \u2014 fast", "write", "x/README.md")
    assert not rc.check("a new tool, fast", "write", "x/README.md")
    assert rc.check("Welcome to BrightLeaf", "write", "site/page.tsx")


def test_addresses_are_not_words(tmp_path, monkeypatch):
    rc = _load(tmp_path, monkeypatch, {"b": BRAND})
    assert not rc.check('"site": "D:/BrightLeaf/website"', "write", "C:/u/.claude/settings.json")
    assert not rc.check("see https://x.com/BrightLeaf/page", "write", "notes.md")


def test_path_scope(tmp_path, monkeypatch):
    rc = _load(tmp_path, monkeypatch, {"c": COPY})
    assert rc.check("Every pack is mastered", "write", "app/public/pack.html")
    assert not rc.check('print("mastered: " + v)', "write", "tools/check.py")


def test_command_tests_and_judgment_rules_have_no_test(tmp_path, monkeypatch):
    rc = _load(tmp_path, monkeypatch, {"v": VERCEL, "d": JUDGE})
    assert rc.check("npx vercel --prod --yes", "command")
    assert not rc.check("npm run ship", "command")


def test_proof_rejects_a_test_that_stops_fine_commands():
    import rulecompile
    d = {"pattern": "git", "unless": "", "on": "command", "hit": ["git push"], "miss": ["ls"]}
    fine = ["git log"] * 50 + ["ls"] * 950
    assert "real fine commands" in rulecompile._prove(d, fine)
    d2 = {"pattern": "vercel\\s+--prod", "unless": "", "on": "command", "hit": ["vercel --prod"], "miss": ["npm run ship"]}
    assert rulecompile._prove(d2, fine) == ""
