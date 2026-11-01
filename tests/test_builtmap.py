"""Already built: a new script whose job a build entry already did is stopped once, by meaning, with no card by hand.

Real case 2026-11-01 (AA Breathwork Rhythms): bf_windows.py ("for every Breathwork Foundations song with a full drum
stem, measure each bar and pick 4- and 8-bar loops") was written while TONE_GARDEN_JOURNAL held the 2026-10-25
[feature] (34 loops cut by cut_loops.py) and the 2026-10-26 [ship] (64 section loops from cut_sections.py and
energy_map.py). Nothing stopped it; then bf_windows2/3/4 followed. The meaning layer is faked here (the hits and line
scores measured live on bge-m3); a live check runs only when the PC's meaning service answers.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# meaning.py reads JOURNAL_HOME at import: never the real index, and leave no imported copy behind for
# test_meaning.py, which imports it with its own temporary home (2026-11-01 its fixture ran on the real home).
_saved = os.environ.get("JOURNAL_HOME")
os.environ["JOURNAL_HOME"] = tempfile.mkdtemp(prefix="journal-builtmap-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import builtmap  # noqa: E402
sys.modules.pop("meaning", None)
if _saved is None:
    os.environ.pop("JOURNAL_HOME", None)
else:
    os.environ["JOURNAL_HOME"] = _saved

J = "C:/x/TONE_GARDEN_JOURNAL.md"
BODIES = {
    (J, 6494): "BREATHWORK RHYTHMS SONG JOURNEY LIVE (2026-10-26).\n"
               "- Per-bar map (energy_map.py) of 23 full drum stems (BF Vol 1 x10, Vol 2-4 x13): kick = 40-120 Hz band peak\n"
               "- Cut (cut_sections.py): 64 section loops = 22 groove, 14 sparse, 11 full, 2 nokick, 15 fills (1 bar)\n"
               "- Player (public/breathwork/rhythms.js, ?v=20261026x): song journey, phrase-aligned parts",
    (J, 6181): "BREATHWORK RHYTHMS: LOOPS LIBRARY + SCENES + PRESETS built on the PC (2026-10-25).\n"
               "- Loops: 34 bar-cut seamless loops from Breathwork Foundations stems. Cutter: cut_loops.py (beat grid fit)",
    (J, 7000): "A text entry with no script in it at all, about the same loops and the same bars, long enough.",
}
HITS = [
    {"path": J, "journal": "TONE_GARDEN_JOURNAL.md", "line": 6494, "score": 0.72,
     "heading": "2026-10-26 19:37 [ship] BREATHWORK RHYTHMS SONG JOURNEY LIVE (2026-10-26)"},
    {"path": J, "journal": "TONE_GARDEN_JOURNAL.md", "line": 6181, "score": 0.69,
     "heading": "2026-10-25 22:52 [feature] BREATHWORK RHYTHMS: LOOPS LIBRARY + SCENES + PRESETS built on the PC"},
    {"path": J, "journal": "TONE_GARDEN_JOURNAL.md", "line": 7000, "score": 0.70,
     "heading": "2026-10-27 10:00 [ship] SOMETHING WITHOUT SCRIPTS"},
    {"path": J, "journal": "TONE_GARDEN_JOURNAL.md", "line": 6600, "score": 0.75,
     "heading": "2026-10-28 10:00 [take] a take, not a build"},
]
BF_WINDOWS = ('"""bf_windows.py <sounds_lib.json> <cookies.json> <out.json>\nBreathwork Rhythms (owner 2026-10-31): for every '
              'Breathwork Foundations song with a full drum stem, measure each bar (loudness, kick, hits) and pick, for 4- '
              'and 8-bar loops, the normal part and the strongest part."""\nimport json\n')


@pytest.fixture
def fake(monkeypatch):
    calls = {"q": 0}

    def query(q, k=8, timeout=1.5, **kw):
        calls["q"] += 1
        return [dict(h) for h in HITS]

    def score(q, texts, timeout=3.0):
        # measured live 2026-11-01: the per-bar map line 0.69, the cut line 0.68, the player line 0.72 (the new
        # script does not use rhythms.js), the cut_loops line 0.67
        return [0.72 if "Player" in t else 0.69 if "energy_map" in t else 0.68 if "cut_sections" in t else 0.67
                for t in texts]

    monkeypatch.setattr(builtmap.meaning, "query", query)
    monkeypatch.setattr(builtmap.meaning, "score", score)
    monkeypatch.setattr(builtmap, "_body", lambda p, l: BODIES.get((p, l), ""))
    return calls


def write(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def test_real_case_new_cutter_is_stopped_with_the_existing_scripts(fake, tmp_path):
    r = builtmap.check(write(str(tmp_path / "bf_windows.py"), BF_WINDOWS), {})
    assert r and "deny" in r
    t = r["deny"]
    assert "ALREADY BUILT" in t and "cut_sections.py" in t and "energy_map.py" in t and "cut_loops.py" in t
    assert "TONE_GARDEN_JOURNAL.md:6494" in t and "TONE_GARDEN_JOURNAL.md:6181" in t
    assert "[take]" not in t and "SOMETHING WITHOUT SCRIPTS" not in t   # only build entries that name a script


def test_once_per_script_and_its_versions(fake, tmp_path):
    seen = {}
    assert builtmap.check(write(str(tmp_path / "bf_windows.py"), BF_WINDOWS), seen)
    assert builtmap.check(write(str(tmp_path / "bf_windows.py"), BF_WINDOWS), seen) is None   # the retry passes
    assert builtmap.check(write(str(tmp_path / "bf_windows2.py"), BF_WINDOWS.replace("bf_windows", "bf_windows2")), seen) is None


def test_existing_file_test_file_and_prose_never_stop(fake, tmp_path):
    old = tmp_path / "cutter.py"
    old.write_text("x = 1\n")
    assert builtmap.check(write(str(old), BF_WINDOWS), {}) is None            # rewriting a file = working on it
    assert builtmap.check(write(str(tmp_path / "test_bf.py"), BF_WINDOWS), {}) is None
    assert builtmap.check(write(str(tmp_path / "notes.md"), BF_WINDOWS), {}) is None
    assert builtmap.check(write(str(tmp_path / "tiny.py"), '"""x"""\n'), {}) is None   # nothing said: nothing to ask


def test_a_line_about_a_tool_the_new_code_uses_is_not_a_duplicate(fake, tmp_path):
    uses = BF_WINDOWS + "subprocess.run(['python', 'cut_sections.py']); open('energy_map.py'); x = 'rhythms.js'; 'cut_loops.py'\n"
    assert builtmap.check(write(str(tmp_path / "bf_windows.py"), uses), {}) is None


def test_a_module_named_without_extension_is_in_use(fake, tmp_path):
    """2026-11-01, live in the session that built this: a new tests/conftest.py that sets meaning.OFF was stopped
    with meaning.py as the existing tool; it was working ON meaning, and it is test infrastructure."""
    uses = BF_WINDOWS + "import cut_sections, energy_map\nx = cut_loops.run()\n"
    assert builtmap.check(write(str(tmp_path / "bf_windows.py"), uses), {}) is None
    assert builtmap.check(write(str(tmp_path / "conftest.py"), BF_WINDOWS), {}) is None


def test_meaning_service_down_means_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(builtmap.meaning, "query", lambda *a, **k: [])
    assert builtmap.check(write(str(tmp_path / "bf_windows.py"), BF_WINDOWS), {}) is None


def test_heredoc_script_and_agent_build_brief(fake, tmp_path):
    cmd = f"cat > \"{tmp_path}/cut_again.py\" <<'EOF'\n{BF_WINDOWS}EOF\npython \"{tmp_path}/cut_again.py\""
    assert builtmap.check({"tool_name": "Bash", "tool_input": {"command": cmd}}, {})
    ag = {"tool_name": "Agent", "tool_input": {"description": "Build Breathwork loop cutter",
                                                "prompt": "Write a script that cuts 4 and 8 bar loops from every drum stem"}}
    assert builtmap.check(ag, {})
    rd = {"tool_name": "Agent", "tool_input": {"description": "Research loop tools", "prompt": "Find what exists"}}
    assert builtmap.check(rd, {}) is None


def test_live_real_case_when_the_service_answers(monkeypatch):
    monkeypatch.setattr(builtmap.meaning, "OFF", False)   # conftest turns the real service off for every test
    real = Path(os.environ.get("JOURNAL_REAL_HOME") or Path.home() / ".journal") / "index.sqlite"
    if not real.is_file() or not builtmap.meaning.score("a", ["a"], timeout=3):
        pytest.skip("meaning service or real index not here")
    monkeypatch.setattr(builtmap.meaning, "DB", real)   # entry bodies are only read
    f = builtmap.find("bf_windows.py: " + builtmap.intro(BF_WINDOWS), BF_WINDOWS, "bf_windows.py", timeout=60)
    names = {s for e in f for s in e["scripts"]}
    assert {"cut_sections.py", "energy_map.py"} & names
