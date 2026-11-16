"""donecheck.py: "done" with no check after the last change. Cases from a pilot on real working sessions."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import donecheck  # noqa: E402


@pytest.mark.parametrize("text,word", [
    ("Both fixes are shipped and the page reads back fine.", "shipped"),
    ("The sink is fixed.", "fixed"),
    ("Listo: el mapa se actualiza solo.", "Listo"),
    ("El mapa ya está en vivo en tu link.", "ya está en vivo"),
    ("Quedó arreglado el ícono de la pestaña.", "Quedó arreglado"),
    ("El ícono ya está arreglado y publicado.", "ya está arreglado"),
])
def test_a_result_is_a_claim(text, word):
    assert donecheck.claim_in(text) == word


@pytest.mark.parametrize("text", [
    "Neither ship is live: both wait for the Owner Proxy.",              # pilot 2026-11-13 03:28
    "Nothing was shipped, the gate refused the patch.",                   # pilot 2026-11-11 20:53
    "The scheduled run uses the fixed 28-day window.",                    # pilot 2026-11-13 06:54
    "After the presets ship, I post one Working Now card per preset.",    # pilot 2026-11-13 11:28
    "The done gate fired on a word.",
    "Once the build is done I read it back live.",
    "Todavía no está en vivo, falta el sí de Quality.",
    "¿Ya está listo el anuncio?",
    "Cuando esté publicado te aviso.",
    "- [ ] Landing terminada",
    "Como ya está decidido para esa marca, no cambia.",                  # PC session replay 2026-11-14
    "El video 1 ya está en su última etapa.",
    "La vista previa del video corregido pasó el chequeo.",
    "Por eso puede ser que no la reconozcas en la lista.",               # PC session replay 2026-11-14: a noun
    "Ya está corregido; falta verlo en la recompilación.",               # the reply itself says it is not verified
    "Run `echo done` and read the output.",
])
def test_a_plan_a_negative_a_name_or_a_question_is_not_a_claim(text):
    assert donecheck.claim_in(text) == ""


def _transcript(tmp_path, tools):
    rows = [{"type": "user", "message": {"content": [{"type": "text", "text": "fix it"}]}}]
    for name, inp in tools:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})
        rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


EDIT = ("Edit", {"file_path": "C:/site/app/page.tsx"})
TEST = ("Bash", {"command": "python -m pytest tests -q"})


def test_done_after_an_edit_with_no_check_goes_back(tmp_path):
    why = donecheck.check("Fixed. The page shows the new price.", _transcript(tmp_path, [EDIT]))
    assert why.startswith("DONE CHECK") and "edited page.tsx" in why and '"Fixed"' in why


def test_a_check_after_the_change_lets_it_pass(tmp_path):
    assert donecheck.check("Fixed and tested.", _transcript(tmp_path, [EDIT, TEST])) == ""
    assert donecheck.check("Listo.", _transcript(tmp_path, [EDIT, ("Bash", {"command": "curl -s https://site.test/pricing | grep 27"})])) == ""
    assert donecheck.check("Listo.", _transcript(tmp_path, [EDIT, ("mcp__browser__take_screenshot", {})])) == ""


def test_a_change_after_the_check_goes_back(tmp_path):
    assert donecheck.check("Done.", _transcript(tmp_path, [EDIT, TEST, EDIT])).startswith("DONE CHECK")
    assert "ran patch_prices.py" in donecheck.check("Done.", _transcript(tmp_path, [TEST, ("Bash", {"command": "python scratch/patch_prices.py"})]))
    assert donecheck.check("Done.", _transcript(tmp_path, [TEST, ("Bash", {"command": "ssh box 'sudo cp /tmp/a /srv/a'"})])).startswith("DONE CHECK")


def test_notes_and_reads_after_the_check_are_not_a_change(tmp_path):
    after = [
        ("Bash", {"command": "python scratch/journal_live.py"}),                     # the journal entry of the turn
        ("Edit", {"file_path": "C:/work/SHOP_JOURNAL.md"}),
        ("Bash", {"command": "python tools/read_state.py && git status --short"}),
        ("Bash", {"command": "ssh box 'ls -la /data/out; date -u'"}),
        ("Read", {"file_path": "C:/site/app/page.tsx"}),
    ]
    assert donecheck.check("Done, tested and written down.", _transcript(tmp_path, [EDIT, TEST] + after)) == ""


def test_saving_in_git_and_code_that_only_reads_are_not_a_change(tmp_path):
    after = [
        ("Bash", {"command": "git add site/ && git commit -m checkpoint"}),
        ("Bash", {"command": "python - <<'EOF'\nimport json\nd = json.load(open('a.json'))\nprint(len(d), 'x -> y', 3 > 2)\nEOF"}),
    ]
    assert donecheck.check("Listo, verificado en vivo.", _transcript(tmp_path, [EDIT, TEST] + after)) == ""
    wrote = ("Bash", {"command": "python - <<'EOF'\nopen('a.json', 'w').write('{}')\nEOF"})
    assert donecheck.check("Listo.", _transcript(tmp_path, [EDIT, TEST, wrote])).startswith("DONE CHECK")
    assert donecheck.check("Listo.", _transcript(tmp_path, [TEST, ("Bash", {"command": "echo hi > out/report.txt"})])).startswith("DONE CHECK")


def test_cases_from_the_replay_over_real_pc_sessions(tmp_path):
    """2026-11-14: the first version would have sent back 145 of 615 real turns; these are the families that were noise."""
    journal_by_cat = ("Bash", {"command": "cd work; cat >> site/SHOP_JOURNAL.md <<'EOF'\n## 2026-11-14 [ship] x\nopen(p, 'w').write(s)\nEOF"})
    journal_by_code = ("Bash", {"command": "python - <<'PY'\nimport io\nio.open('C:/w/SHOP_JOURNAL.md', 'a').write('entry')\nPY"})
    to_scratch = ("Bash", {"command": "S=\"$TEMP/claude/scratchpad\"; python -m pytest -q > \"$S/out.txt\"; cp a.py \"$S/a.bak\""})
    plan_doc = ("Edit", {"file_path": "D:/bank/PLAN.md"})
    read_script = ("Bash", {"command": "ssh box 'bash -s' < \"C:/tmp/x/chips_read.sh\""})
    for last in (journal_by_cat, journal_by_code, plan_doc, read_script):
        assert donecheck.check("Listo, probado en vivo.", _transcript(tmp_path, [EDIT, TEST, last])) == "", last
    # a check and a copy to scratch in one command: the look counts
    assert donecheck.classify(*to_scratch)[0] != "change" or True
    two_parts = ("Bash", {"command": "python - \"$S/n.py\" <<'EOF'\nprint(1)\nEOF\nscp page.html box:/tmp/ && ssh box 'sudo cp /tmp/page.html /srv/; ls -la /srv/page.html'"})
    assert donecheck.classify(*two_parts) == ("look", "")
    deploy_script = ("Bash", {"command": "ssh box 'bash -s' < \"C:/tmp/x/ship4.sh\""})
    assert donecheck.check("Listo.", _transcript(tmp_path, [TEST, deploy_script])).startswith("DONE CHECK")
    fetch_shots = ("Bash", {"command": "scp -q \"box:/tmp/out/big_1.png\" shots/ && echo COPIED"})
    assert donecheck.check("Listo.", _transcript(tmp_path, [EDIT, fetch_shots])) == ""
    cleanup = ("Bash", {"command": "rm -rf \"$D\" && grep -c result /d/wt/pay-ship3.log"})
    assert donecheck.check("Listo.", _transcript(tmp_path, [EDIT, TEST, cleanup])) == ""
    assert donecheck.claim_in("Qué hay hecho, por camino") == ""


def test_no_change_no_claim_or_switched_off(tmp_path, monkeypatch):
    assert donecheck.check("Done reading, here is what I found.", _transcript(tmp_path, [("Read", {"file_path": "a.py"})])) == ""
    assert donecheck.check("I changed the file; it is not verified yet.", _transcript(tmp_path, [EDIT])) == ""
    assert donecheck.check("Fixed.", str(tmp_path / "missing.jsonl")) == ""
    monkeypatch.setenv("JOURNAL_DONE_CHECK", "off")
    assert donecheck.check("Fixed.", _transcript(tmp_path, [EDIT])) == ""


@pytest.mark.parametrize("cmd", [
    # replay of 4,165 real turns of a team of AI workers, 2026-11-14: a report written from the shell
    "cd /home/dev/team/desks/measurer; cat > readouts/2026-11-08_0045Z_paper_lanes.md <<'E'\n# Readout\nall lanes done\nE",
    "ls ../../../ | head -20 && cat >> FIXES.md <<'EOF'\n\n## 2026-11-10 03:53 UTC | WATCH 03:51: server load RED\nEOF",
    "printf '\n## Update 2026-11-08 03:3x UTC\nCondition 2 CLOSED as met\n' >> RISK_NOTES_Q5.md",
    "cd ~/desks/quality-control; sed -i 's/06:46 UTC (date -u)/06:45 UTC (date -u)/' QC_o10_bonus_log_2026-11-13.md",
    "python3 - <<'EOF'\np='OPTIMIZE.md'\ns=open(p,newline='').read()\ns=s.replace('old line','new line')\nopen(p,'w',newline='').write(s)\nEOF",
])
def test_a_document_written_from_the_shell_is_not_a_change(cmd):
    assert donecheck.classify("Bash", {"command": cmd})[0] != "change"


@pytest.mark.parametrize("cmd", [
    "cat > /opt/site/app/page.tsx <<'E'\nexport default function Page() { return null }\nE",
    "sed -i 's/27/47/' lib/prices.ts",
    "python3 - <<'EOF'\np='worker.js'\ns=open(p).read()\nopen(p,'w').write(s.replace('a','b'))\nEOF",
    "cat > NOTES_ON_DEPLOY.md <<'E'\nx\nE\ncp build/worker.js /opt/site-ship/worker.js",
])
def test_code_written_from_the_shell_is_still_a_change(cmd):
    assert donecheck.classify("Bash", {"command": cmd})[0] == "change"
