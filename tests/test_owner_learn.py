"""The missing link of the learning loop (owner 2026-11-16): his message corrected the session or set a direction
and no journal was written that turn. Messages typed fast, in two languages, are the cases."""
import json
import os
import time
from datetime import datetime, timezone

import owner_calls


def _transcript(tmp_path, msg, tools=(), age=30):
    at = datetime.fromtimestamp(time.time() - age, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    rows = [{"type": "user", "timestamp": at, "message": {"role": "user", "content": [{"type": "text", "text": msg}]}}]
    for name, arg in tools:
        key = "command" if name in ("Bash", "PowerShell") else "file_path"
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": name, "input": {key: arg}}]}})
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


def _old_journal(tmp_path, monkeypatch):
    j = tmp_path / "SHOP_JOURNAL.md"
    j.write_text("# SHOP\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(j, (old, old))
    monkeypatch.setattr(owner_calls, "_journal_paths", lambda session="": [str(j)])
    return j


REAL = [
    "the hero I want it to be the sales one always",
    "no me gusta ese titulo, cambialo por el de ventas",
    "esto es para nosotros, no para el cliente",
    "it has to be for any level, I already told you",
    "pero que mierda, el producto esta en el servicio viejo y ya nos mudamos, no salto el chequeo",
    "I do not like that headline, it has to be the sales one always",
]
NOT_A_RULE = ["link please", "si dale", "dale la 1", "and how much does it cost in tokens to read the whole pack?",
              "and the mod thing?", "show me the other version now"]


def test_real_messages_are_seen_as_a_direction_and_plain_ones_are_not():
    for m in REAL:
        assert owner_calls.is_direction(m), m
    for m in NOT_A_RULE:
        assert not owner_calls.is_direction(m), m


def test_a_direction_with_no_journal_written_sends_the_reply_back(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    t = _transcript(tmp_path, REAL[0], tools=[("Bash", "python build.py --variant c")])
    out = owner_calls.check("Listo, ya esta en la landing.", t)
    assert "no journal was written this turn" in out and "the hero I want" in out, out


def test_a_journal_written_in_the_turn_lets_the_reply_pass(tmp_path, monkeypatch):
    j = _old_journal(tmp_path, monkeypatch)
    t = _transcript(tmp_path, REAL[0], tools=[("Bash", "python some_script.py")])
    stamp = time.strftime("%Y-%m-%d %H:%M")
    # another session added its own entry to the same journal: the file changed, the owner's direction was not saved
    j.write_text("# SHOP\n\n## " + stamp + " [ship] THE STORE PAGE IS LIVE\n\nGate passed, audit OK.\n", encoding="utf-8")
    assert "no journal was written this turn" in owner_calls.check("Listo, ya esta en la landing.", t)
    # this session wrote his direction down (a script appended the entry)
    j.write_text("# SHOP\n\n## " + stamp + " [correction] THE HERO IS ALWAYS THE SALES ONE\n\nOwner, PC chat: the hero always.\n", encoding="utf-8")
    assert owner_calls.check("Listo, ya esta en la landing.", t) == ""
    # a build entry that only carries his words does not count: his direction goes in an entry tagged as his
    j.write_text("# SHOP\n\n## " + stamp + " [build] LANDING C\n\nOwner, PC chat: the hero is the sales one, always.\n", encoding="utf-8")
    assert "no journal was written this turn" in owner_calls.check("Listo, ya esta en la landing.", t)
    # an entry about him from before his message does not count
    j.write_text("# SHOP\n\n## 2020-01-01 10:00 [correction] AN OLD ONE\n\nOwner said something long ago.\n", encoding="utf-8")
    assert "no journal was written this turn" in owner_calls.check("Listo, ya esta en la landing.", t)


def test_a_direct_edit_of_a_journal_or_a_rule_file_counts(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    for tool in (("Edit", "C:/x/SHOP_JOURNAL.md"), ("Write", "C:/x/OWNER_SAID_JOURNAL.md"),
                 ("Bash", "python - >> SHOPSITE_FULL_JOURNAL.md"), ("mcp__journal__journal_append", "")):
        t = _transcript(tmp_path, REAL[1], tools=[tool])
        assert owner_calls.check("Listo.", t) == "", tool


def test_a_plain_message_or_a_missing_time_never_stops(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    assert owner_calls.check("Aca van los links.", _transcript(tmp_path, "link aver")) == ""
    p = tmp_path / "nots.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": REAL[0]}}), encoding="utf-8")
    assert owner_calls.check("Listo.", str(p)) == ""


def test_other_rows_are_not_the_owner_and_the_switch_turns_it_off(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    note = "[SYSTEM NOTIFICATION - NOT USER INPUT] a task ended, it always has to be read"
    assert owner_calls.check("Listo.", _transcript(tmp_path, note)) == ""
    monkeypatch.setenv("JOURNAL_OWNER_LEARN", "off")
    assert owner_calls.check("Listo.", _transcript(tmp_path, REAL[0])) == ""


def test_the_end_of_a_long_record_is_enough(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    p = tmp_path / "long.jsonl"
    filler = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 4000}]}})
    at = datetime.fromtimestamp(time.time() - 30, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    owner = json.dumps({"type": "user", "timestamp": at, "message": {"role": "user", "content": REAL[0]}})
    p.write_text("\n".join([filler] * 1500 + [owner]), encoding="utf-8")   # about 6 MB before his message
    rows = owner_calls._tail_rows(str(p))
    assert rows and rows[-1]["type"] == "user" and len(rows) <= 600
    assert "no journal was written this turn" in owner_calls.check("Listo.", str(p))


def test_the_owner_voice_journal_and_backups_never_count_as_a_write(tmp_path, monkeypatch):
    assert owner_calls.NOT_A_WRITE.search("OWNER_VOICE_JOURNAL_2026-11.md")
    assert owner_calls.NOT_A_WRITE.search("ADS_JOURNAL.bak_20261115.md")
    assert not owner_calls.NOT_A_WRITE.search("SHOPSITE_FULL_JOURNAL.md")


def test_a_send_back_is_logged(tmp_path, monkeypatch):
    _old_journal(tmp_path, monkeypatch)
    monkeypatch.setenv("JOURNAL_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    assert owner_calls.check("Listo.", _transcript(tmp_path, REAL[0]), "sess1")
    rows = (tmp_path / "home" / "owner_learn_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["session"] == "sess1"
