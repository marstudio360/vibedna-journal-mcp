"""What 2.2.1 changes, checked on the package itself: the installer run with no flag and no keyboard (how an AI
runs it) says in one line that nothing was changed, instead of ending in a Python error."""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="neural-dna-221-"))


def _env(name: str) -> dict:
    """A fresh machine: an empty home folder, no JOURNAL_* setting, no claude command on the PATH."""
    home = _TMP / "homes" / name
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOURNAL_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8", PATH=str(Path(sys.executable).parent))
    return env


def _run(args: list, env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PKG), env=env, timeout=300)


def _files(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_no_keyboard_and_no_flag_changes_nothing_and_says_so():
    env = _env("nokeyboard")
    home = Path(env["HOME"])
    before = _files(home)
    r = _run(["install_mod.py"], env)          # empty stdin: the question cannot be answered
    assert r.returncode == 1
    assert "Traceback" not in r.stderr and "EOFError" not in r.stderr
    assert "No keyboard here, so nothing was changed." in r.stdout
    assert "run it again with --yes" in r.stdout
    assert _files(home) == before


def test_a_no_at_the_keyboard_still_changes_nothing():
    env = _env("saidno")
    home = Path(env["HOME"])
    r = _run(["install_mod.py"], env, stdin="n\n")
    assert r.returncode == 0
    assert "Nothing changed." in r.stdout
    assert not (home / ".claude" / "settings.json").exists()


def test_the_docs_say_what_happens_with_no_keyboard():
    text = (PKG / "INSTALL.md").read_text(encoding="utf-8")
    assert "## New in 2.2.1" in text
    assert "Run with no keyboard and no `--yes`, it changes nothing and says so in one line." in text
    assert "## 2.2.1 " in (PKG / "CHANGELOG.md").read_text(encoding="utf-8")
