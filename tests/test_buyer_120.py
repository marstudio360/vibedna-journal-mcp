"""Journals DNA 1.2.0, the buyer's view: a fresh folder of invented journals, nothing else on the machine.

Each test runs the package the way a buyer meets it: the server's --quick command, the hook as a separate process
(the way the journals mod calls it), the Obsidian map builder, and the settings a buyer can turn on.

Run: python -m pytest tests   (everything in a temp JOURNAL_HOME and JOURNAL_ROOTS)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="journals-dna-buyer-"))
HOME, ROOT = _TMP / "home", _TMP / "projects"


def _env(**extra) -> dict:
    env = dict(os.environ, JOURNAL_HOME=str(HOME), JOURNAL_ROOTS=str(ROOT), PYTHONIOENCODING="utf-8")
    env.pop("JOURNAL_INCLUDE_VAULT_PATH", None)
    env.pop("JOURNAL_BRAND_NAMES", None)
    env.update(extra)
    return env


def _write(rel: str, text: str) -> Path:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


_write("SHOP/SHOP_JOURNAL.md", """# SHOP JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Checkout | checkout, cart, payments.py | the shop team | SHOP/SHOP_JOURNAL.md | hosted payment page only |

## Current state
- Checkout runs on the hosted payment page.

## Handoff for next session
- [ ] add the tax line to the receipt

## 2026-10-20 10:00 [ship] checkout retries a failed card once
The retry lives in payments.py.

---
""")
_write("SHOP/SHOP_RULES_JOURNAL.md", "# SHOP RULES\n\n"
       "- 2026-03-06: Every price shown to customers comes from the price list file, so a price changes in one place.\n")
_write("starter/journals-vault/Library/BOOK_JOURNAL.md", "# BOOK JOURNAL\n\n## Current state\n- draft 2\n")


def _run(args: list[str], stdin: str = "", **extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(PKG), env=_env(**extra), timeout=120)


def test_one_version_everywhere():
    v = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    import re
    sv = re.search(r'^VERSION = "([^"]+)"', (PKG / "server.py").read_text(encoding="utf-8"), re.M).group(1)
    plugin = json.loads((PKG / "mod/journals/.claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    market = json.loads((PKG / "mod/.claude-plugin/marketplace.json").read_text(encoding="utf-8"))["plugins"][0]["version"]
    assert v == sv == plugin == market, (v, sv, plugin, market)
    assert f'"version": VERSION' in (PKG / "server.py").read_text(encoding="utf-8")   # vibedna_info reads the same constant


def test_quick_command_shows_the_piece_decided_and_pending():
    r = _run(["server.py", "--quick", "checkout"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "Checkout" in out and "the shop team" in out, out
    assert "SHOP_JOURNAL.md" in out, out


def test_hook_process_hands_the_journal_brief_with_the_first_edit():
    # 1.5.0: the first edit of a mapped piece carries its journal's brief and goes through (1.2.0 to 1.4.0 stopped it
    # until the journal was read, which cost a whole extra turn every time); the brief counts as the read
    call = {"session_id": "buyer-1", "reports_reads": True, "tool_name": "Edit",
            "tool_input": {"file_path": str(ROOT / "SHOP" / "payments.py"), "content": "x = 1\n"}}
    first = _run(["quick_hook.py"], json.dumps(call))
    out = json.loads(first.stdout)["hookSpecificOutput"]
    assert "permissionDecision" not in out, out
    assert "JOURNAL BRIEF" in out["additionalContext"] and "SHOP_JOURNAL" in out["additionalContext"]
    assert "add the tax line to the receipt" in out["additionalContext"]
    after = _run(["quick_hook.py"], json.dumps(call)).stdout.strip()
    assert '"deny"' not in after and "JOURNAL BRIEF" not in after, after


def test_any_rules_journal_is_a_rules_source():
    code = ("import server, quickmap; server._index_refresh_internal(); "
            "print('\\n'.join(quickmap._owner_rule_lines('change the price shown to customers on the checkout page')))")
    r = _run(["-c", code])
    assert r.returncode == 0, r.stderr
    assert "price list file" in r.stdout and "[rules: SHOP_RULES_JOURNAL.md]" in r.stdout, r.stdout


def test_vault_index_is_off_until_you_point_at_one():
    vault = _TMP / "names.json"
    vault.write_text(json.dumps({"entries": [{"name": "stripe-live-key", "category": "payment", "fields": ["key"]}]}),
                     encoding="utf-8")
    code = "import server, quickmap; print(len(quickmap._vault_rows(['stripe'])))"
    assert _run(["-c", code]).stdout.strip() == "0"
    assert _run(["-c", code], JOURNAL_INCLUDE_VAULT_PATH=str(vault)).stdout.strip() == "1"


def test_own_brand_names_come_from_the_setting():
    code = "import server, quickmap; print(sorted(quickmap._BRAND_NAMES))"
    assert _run(["-c", code]).stdout.strip() == "[]"
    assert _run(["-c", code], JOURNAL_BRAND_NAMES="Acme, Acme Labs").stdout.strip() == "['acme', 'acme labs']"


def test_the_starter_vault_folder_is_indexed():
    code = "import server; server._index_refresh_internal(); c = server._conn(); print([r[0] for r in c.execute('SELECT name FROM journals')])"
    assert "BOOK_JOURNAL.md" in _run(["-c", code]).stdout


def test_obsidian_vault_dry_run_writes_nothing_and_apply_writes_the_map():
    dry = _run(["obsidian.py", "vault", "--root", str(ROOT)])
    assert dry.returncode == 0 and "DRY RUN" in dry.stdout, dry.stdout + dry.stderr
    assert not (ROOT / "_obsidian").exists()
    wet = _run(["obsidian.py", "vault", "--root", str(ROOT), "--apply"])
    assert wet.returncode == 0 and "WROTE" in wet.stdout, wet.stdout + wet.stderr
    for f in ("_obsidian/START HERE.md", "_obsidian/Journals.base", "_obsidian/Journals map.canvas",
              ".obsidian/app.json", ".obsidian/core-plugins.json"):
        assert (ROOT / f).exists(), f
    assert "SHOP_JOURNAL" in (ROOT / "_obsidian" / "START HERE.md").read_text(encoding="utf-8")


def test_new_journals_are_born_with_obsidian_properties():
    code = ("import server, json; r = server.journal_create('NEWAPP_JOURNAL.md', r'%s'); "
            "print(open(r['path'], encoding='utf-8').read()[:200])") % str(ROOT / "NEWAPP").replace("\\", "/")
    (ROOT / "NEWAPP").mkdir(exist_ok=True)
    out = _run(["-c", code]).stdout
    assert out.startswith("---") and "type: journal" in out, out


def test_a_journal_made_by_hand_after_the_first_index_is_found():
    """A buyer has no cron rescanning the roots: a journal file written by hand after the first index must still
    reach the quick map (the index rescans the roots when the last full scan is older than JOURNAL_RESCAN_MINUTES)."""
    assert "Checkout" in _run(["server.py", "--quick", "checkout"]).stdout   # the index exists now
    _write("MAIL/MAIL_JOURNAL.md", "# MAIL JOURNAL\n\n## 2026-10-21 09:00 [ship] zebrafinch newsletter sent\nSent.\n")
    late = _run(["server.py", "--quick", "zebrafinch"], JOURNAL_RESCAN_MINUTES="0").stdout
    assert "MAIL_JOURNAL.md" in late, late
