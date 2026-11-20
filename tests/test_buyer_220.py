"""What 2.2.0 adds, checked on the package itself: the five checks are in and wired, they read the owner's rule files
by their real names, and the version is the same everywhere."""
import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
import owner_calls  # noqa: E402
import quickmap  # noqa: E402


def test_the_version_is_the_same_everywhere():
    v = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    assert v == "2.2.0"
    assert f'VERSION = "{v}"' in (PKG / "server.py").read_text(encoding="utf-8")
    assert json.loads((PKG / "mod" / "journals" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"] == v
    assert f'"version": "{v}"' in (PKG / "mod" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    assert f"# Install Neural DNA {v}" in (PKG / "INSTALL.md").read_text(encoding="utf-8")
    assert f"## {v} " in (PKG / "CHANGELOG.md").read_text(encoding="utf-8")


def test_the_five_checks_are_in_the_package_and_wired():
    for f in ("owner_calls.py", "existsprobe.py", "verdictprobe.py", "alarmjudge.py", "donecheck.py"):
        assert (PKG / f).is_file(), f
    src = (PKG / "quickmap.py").read_text(encoding="utf-8")
    stop = src[src.index("def stop_check(call: dict)"):]
    # the order at the end of a turn: owner calls and learn, exists on the reply, then the done check
    assert stop.index("import owner_calls") < stop.index("existsprobe.reply_check") < stop.index("import donecheck")
    reply = src[src.index("def reply_check(call: dict)"):src.index("def stop_check(call: dict)")]
    assert "_moved_claims(text)" in reply and "verdictprobe.reply_check(text, folders)" in reply
    assert '"moved": moved' in reply and "CHECK THIS NAME IN YOUR LAST REPLY" in reply
    assert "existsprobe.block(q_msg)" in src
    assert hasattr(quickmap, "_moved_claims") and "another" in quickmap._NOT_A_PLACE


def test_a_rule_written_in_the_owners_own_files_counts_as_written():
    for name in ("C:/x/.claude/CLAUDE.md", "/home/me/project/AGENTS.md", "/x/memory/MEMORY.md", "/x/OWNER_SAID_JOURNAL.md",
                 "/x/SHOP_RULES_JOURNAL.md", "/x/.claude/projects/p/memory/note.md"):
        assert owner_calls.RULE_FILE.search(name), name
    assert not owner_calls.RULE_FILE.search("/x/SHOP_JOURNAL.md")


def test_a_message_from_another_session_is_not_the_owner_typing():
    assert owner_calls.NOT_OWNER.search("Another AI session sent you this: please rebase")
    assert owner_calls.NOT_OWNER.search("[SYSTEM NOTIFICATION - NOT USER INPUT] a task ended")
    assert not owner_calls.NOT_OWNER.search("always use the sales headline")


def test_a_direction_is_told_from_a_plain_message():
    assert owner_calls.is_direction("never put that word on the page again")
    assert owner_calls.is_direction("I do not like it, it has to be shorter")
    assert not owner_calls.is_direction("ok go")
    assert not owner_calls.is_direction("how much does it cost?")


def test_the_long_message_fix_is_in(monkeypatch):
    import existsprobe as E
    filler = " ".join(f"The paragraph number {i} talks about pricing servers hosting privacy speed budgets plans "
                      f"buyers products sessions journals guides copies rules owners agents. " for i in range(40))
    long_msg = filler + "Do we have a printable version of the guides? " + filler
    assert len(E._ideas(long_msg)) > E.MAX_IDEAS
    got = {i["label"] for i in E._question_ideas(long_msg)}
    assert len(got) <= E.MAX_IDEAS and {"printable", "guides"} <= got


def test_the_docs_name_every_switch():
    doc = (PKG / "INSTALL.md").read_text(encoding="utf-8")
    for k in ("JOURNAL_OWNER_LEARN", "JOURNAL_OWNER_CALLS", "JOURNAL_EXISTS_PROBE", "JOURNAL_ALARM_JUDGE", "JOURNAL_DONE_CHECK"):
        assert re.search(r"\| `" + k + r"` \|", doc), k
