"""journal_quick: a word or a file path in, its owner, journals, decisions and latest entries out.

Regression for 2026-10-24: a session edited a shared queue worker without knowing a role owned it. The
before-build cards showed unrelated tools and the edit gate only knew folders. The quick map reads the
written "## Brain map" table (never a guess; there are no owners, it says which journal to read first and who
is working on the piece now) and the hook stops the first touch of a mapped piece once, so its context is read.

Run: python -m pytest tests  (everything in a temp JOURNAL_HOME and JOURNAL_ROOTS)
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="journal-quick-test-"))
os.environ["JOURNAL_HOME"] = str(_TMP / "home")
os.environ["JOURNAL_ROOTS"] = str(_TMP / "projects")
os.environ["JOURNAL_INCLUDE_VAULT_PATH"] = str(_TMP / "vault_names.json")  # never the real vault index
os.environ.pop("JOURNAL_EXTRA_DOCS", None)
_ROOT = _TMP / "projects"


def _write(rel: str, text: str):
    p = _ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


_write("OPS/OPS_JOURNAL.md", """# OPS JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Local model | localmodel, local model, localmodel_worker | Local AI of System | OPS/manuals/LOCAL_AI_JOURNAL.md | message local_ai |
| Billing code | invoice, billing.py | Billing desk | OPS/BILLING_JOURNAL.md | message billing |

## 2026-10-20 10:00 [ship] localmodel queue worker retries jobs
Worker for the localmodel queue.
""")
_write("LOCALMODEL/LOCALMODEL_JOURNAL.md", "# LOCALMODEL JOURNAL\n\n## 2026-10-22 09:00 [measure] localmodel speed\nlocalmodel runs 40 tokens per second.\n"
       "\n## Pending\n- [ ] localmodel: try a smaller context\n")
_write("SHOP/SHOP_JOURNAL.md", "# SHOP JOURNAL\n\n## 2026-10-21 08:00 [fix] checkout brake\nno double charge brake.\n")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as _server  # noqa: E402
import quickmap as srv  # noqa: E402
srv._BRAND_NAMES |= {"tone garden", "launch desk", "forecast desk", "high tide", "mapleworks", "shopsite", "adshare", "growvine", "boltlab", "team hq", "ai team"}
_server._index_refresh_internal()


def test_word_finds_written_owner_and_own_journal():
    m = srv.quick_map("localmodel")
    assert [o["now"] for o in m["pieces"]] == ["Local AI of System"]
    assert m["journals"][0]["journal"] == "LOCALMODEL_JOURNAL.md"
    assert any("smaller context" in p["item"] for p in m["pending"])
    assert m["latest"][0]["when"].startswith("2026-10-22")


def test_file_path_matches_owner_by_file_name():
    m = srv.quick_map("C:/code/servers/localmodel_worker.py")
    assert m["terms"] == ["localmodel"]
    assert m["pieces"] and m["pieces"][0]["now"] == "Local AI of System"


def test_unmapped_piece_is_never_guessed():
    m = srv.quick_map("brake")
    assert m["pieces"] == []


def _hook(call: dict, prompt: bool = False) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        srv.quick_hook(call, prompt=prompt)
    return json.loads(buf.getvalue()) if buf.getvalue().strip() else {}


def _env():
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)  # other test files move these


def _record(call: dict):
    import quick_hook
    quick_hook.record_read(call)


def test_first_touch_delivers_the_journal_brief_instead_of_a_stop():
    """2026-11-06 (owner: the stop cost a whole extra turn every time, "the memory stays the same but it cannot
    weigh"): the first touch of a mapped piece carries its journal's brief and goes through; it counts as the read."""
    _env()
    _write("OPS/BILLING_JOURNAL.md", "# BILLING JOURNAL\n\n## Handoff for next session\n- [ ] retry failed invoices\n")
    _server._index_refresh_internal()
    call = {"session_id": "s1", "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    first = _hook(call)["hookSpecificOutput"]
    assert "permissionDecision" not in first
    ctx = first["additionalContext"]
    assert "Billing desk" in ctx and "JOURNAL BRIEF" in ctx and "retry failed invoices" in ctx
    assert "JOURNAL BRIEF" not in json.dumps(_hook(call))  # delivered once: the next touch does not repeat it


def test_a_piece_map_is_shown_once_per_session_across_its_files():
    """2026-10-30: the journal-tool piece map came back in full on every call that named another of its files
    (quickmap.py, quick_hook.py, a git commit of both), three times in one turn."""
    _env()
    _write("OPS/BILLING_JOURNAL.md", "# BILLING JOURNAL\n\n## Handoff for next session\n- [ ] retry failed invoices\n")
    _server._index_refresh_internal()
    sid = "s1piece"
    first = {"session_id": sid, "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    assert "JOURNAL BRIEF" in _hook(first)["hookSpecificOutput"]["additionalContext"]
    other = {"session_id": sid, "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/invoice.py"}}
    out = _hook(other)
    assert "Billing desk" not in json.dumps(out), out
    # another session still gets the map
    fresh = dict(other, session_id="s1piece-other")
    assert "Billing desk" in json.dumps(_hook(fresh))


def test_gate_opens_with_a_search_or_a_read_of_the_file():
    """A search that found the journal, or a read of its file, opens the piece before any touch: no brief needed."""
    _env()
    _write("OPS/BILLING_JOURNAL.md", "# BILLING JOURNAL\n\n## Handoff for next session\n- [ ] retry failed invoices\n")
    _server._index_refresh_internal()
    call = {"session_id": "s1b", "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    _record({"session_id": "s1b", "reports_reads": True, "tool_input": {"journal_tool": "mcp__journal__journal_search",
             "args": {"query": "invoices"}, "ok": True, "text": json.dumps({"matches": [{"name": "BILLING_JOURNAL.md"}]})}})
    assert "JOURNAL BRIEF" not in json.dumps(_hook(call))
    c2 = {"session_id": "s1c", "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    _record({"session_id": "s1c", "reports_reads": True, "tool_name": "Read",
             "tool_input": {"journal_read": str(_ROOT / "OPS" / "BILLING_JOURNAL.md"), "ok": True}})
    assert "JOURNAL BRIEF" not in json.dumps(_hook(c2))


def test_gate_escape_never_deadlocks():
    """No journal file on disk (LOCAL_AI_JOURNAL.md is never written), a failed read, or an older mod that does not
    report reads: the 3rd attempt passes with a loud note."""
    _env()
    call = {"session_id": "s1d", "reports_reads": True, "tool_name": "Edit",
            "tool_input": {"file_path": "C:/code/servers/localmodel_worker.py"}}
    assert _hook(call)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _hook(call)["hookSpecificOutput"]["permissionDecision"] == "deny"
    third = _hook(call)["hookSpecificOutput"]
    assert "permissionDecision" not in third and "OPENED WITHOUT A JOURNAL READ" in third["additionalContext"]
    # Failed read: the journal exists, the read errored.
    _write("OPS/BILLING_JOURNAL.md", "# BILLING JOURNAL\n")
    _server._index_refresh_internal()
    c2 = {"session_id": "s1e", "reports_reads": True, "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    assert _hook(c2)["hookSpecificOutput"]["permissionDecision"] == "deny"
    _record({"session_id": "s1e", "reports_reads": True, "tool_input": {"journal_tool": "mcp__journal__journal_read",
             "args": {"name_or_path": "BILLING_JOURNAL.md"}, "text": "MCP error -32000: Connection closed", "ok": False}})
    assert _hook(c2)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "a journal read failed" in _hook(c2)["hookSpecificOutput"]["additionalContext"]
    # Older mod (no reports_reads): it would wait forever, so the 3rd attempt passes.
    c3 = {"session_id": "s1f", "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}}
    _hook(c3), _hook(c3)
    assert "older journals mod" in _hook(c3)["hookSpecificOutput"]["additionalContext"]
    assert (_TMP / "home" / "gate_escapes.log").read_text(encoding="utf-8").count("\n") >= 3


def test_hook_ignores_read_only_commands_and_unknown_files():
    assert _hook({"session_id": "s2", "tool_name": "Bash", "tool_input": {"command": "cat billing.py"}}) == {}
    assert _hook({"session_id": "s2", "tool_name": "Edit", "tool_input": {"file_path": "C:/x/random_thing.py"}}) == {}


def test_prompt_hook_only_for_named_things():
    out = _hook({"session_id": "s3", "prompt": "how is localmodel doing?"}, prompt=True)
    assert "Local AI of System" in out["hookSpecificOutput"]["additionalContext"]
    assert _hook({"session_id": "s3", "prompt": "ok go on, what do you think?"}, prompt=True) == {}


def test_quick_hook_script_runs_as_the_mod_calls_it():
    """The mod runs quick_hook.py as a separate process; a syntax error there fails silently in the mod."""
    import subprocess
    script = Path(__file__).resolve().parents[1] / "quick_hook.py"
    call = json.dumps({"session_id": "s9", "tool_name": "Edit", "tool_input": {"file_path": "C:/code/billing.py"}})
    r = subprocess.run([sys.executable, str(script)], input=call, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "JOURNAL_HOME": str(_TMP / "home"),
                            "JOURNAL_ROOTS": str(_ROOT)})
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_first_message_brings_pending_of_the_pieces_you_work_on():
    """Pending work reaches whoever does it at the start of their session, without anyone forwarding it."""
    _write("OPS/BILLING_JOURNAL.md", "# BILLING JOURNAL\n\n## Handoff for next session\n- [ ] retry failed invoices\n")
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)  # other test files move these
    _server._index_refresh_internal()
    out = _hook({"session_id": "s10", "prompt": "You are BILLING DESK of Ops. Start."}, prompt=True)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "YOUR PIECES" in ctx and "retry failed invoices" in ctx
    assert _hook({"session_id": "s10", "prompt": "You are BILLING DESK of Ops. Start."}, prompt=True) == {}


def test_prompt_map_comes_back_a_few_messages_later():
    """2026-10-24: "mails" was mapped on message 1 and a later message about mails got nothing."""
    sid = "s20"
    assert "LOCALMODEL_JOURNAL" in _hook({"session_id": sid, "prompt": "how is localmodel doing?"}, prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert _hook({"session_id": sid, "prompt": "and localmodel now?"}, prompt=True) == {}
    _hook({"session_id": sid, "prompt": "something else entirely"}, prompt=True)
    again = _hook({"session_id": sid, "prompt": "back to localmodel"}, prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert "LOCALMODEL_JOURNAL" in again and "shown earlier" in again


def test_two_common_words_together_map_to_their_journal():
    """2026-10-24: "the pack 1 funnel" gave no map because "pack" and "funnel" are in most journals."""
    for name in ("A", "B", "C", "D", "E", "F"):
        _write(f"MISC{name}/MISC{name}_JOURNAL.md", f"# MISC{name}\n\n## 2026-10-01 10:00 [note] pack\npack stuff\n"
               "\n## 2026-10-01 11:00 [note] funnel\nfunnel stuff\n")
    _write("SHOP/SHOP_JOURNAL.md", "# SHOP JOURNAL\n\n" + "".join(
        f"## 2026-10-2{i} 08:00 [ship] pack funnel step {i}\npack funnel email {i}.\n\n" for i in range(4)))
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _server._index_refresh_internal()
    assert not srv._specific("pack", 0.2) and not srv._specific("funnel", 0.2)
    ctx = _hook({"session_id": "s21", "prompt": "how does the pack 1 funnel work?"}, prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert "SHOP_JOURNAL.md" in ctx


def test_named_product_beats_role_and_chat_words():
    """2026-10-25: "manager" and "modelo" took both map slots of a message about Chatbot and Codex, and the
    decision entry titled "CODEX ... JUNTO A CLAUDE CODE" never showed because no journal is named after codex."""
    for name in ("A", "B", "C", "D", "E", "F", "G", "H"):
        _write(f"NOISE{name}/NOISE{name}_JOURNAL.md", f"# NOISE{name}\n\n## 2026-10-01 10:00 [note] filler {name}\nnothing here\n")
    _write("OPS/MANAGER_JOURNAL.md", "# MANAGER JOURNAL\n\n## 2026-10-02 10:00 [note] manager things\nthe manager tengo plan\n")
    _write("PORT/PORTFOLIO_JOURNAL.md", "# PORTFOLIO JOURNAL\n\n## 2026-10-15 12:35 [decision] CODEX NEXT TO THE EDITOR\n"
           "codex signs in with the chatbot plan; stella burns the quota fast\n")
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _server._index_refresh_internal()
    ctx = _hook({"session_id": "s30", "prompt": "tengo el plan, el manager dice que usemos Codex"},
                prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert 'MAP for "codex"' in ctx and "CODEX NEXT TO THE EDITOR" in ctx
    assert 'MAP for "manager"' not in ctx and 'MAP for "tengo"' not in ctx


def test_vault_names_show_without_values():
    """2026-10-25: a Cloudmodel key sat in the vault and a session asked for a new one; maps now name vault entries."""
    (_TMP / "vault_names.json").write_text(json.dumps({"entries": [{"name": "cloudmodel-free", "category": "api", "fields": ["CLOUDMODEL_API_KEY"]},
                                                                  {"name": "stripe", "category": "cloudmodel", "fields": ["KEY"]}]}))
    try:
        rows = srv._vault_rows(["cloudmodel"])
        assert [r["name"] for r in rows] == ["cloudmodel-free"]  # names only, never the category
        assert "VAULT: entry 'cloudmodel-free'" in srv.quick_map_text({"terms": ["cloudmodel"], "vault": rows})
    finally:
        (_TMP / "vault_names.json").unlink()


def _proc(call: dict, prompt: bool = False) -> dict:
    import subprocess
    script = Path(__file__).resolve().parents[1] / "quick_hook.py"
    r = subprocess.run([sys.executable, str(script)] + (["--prompt"] if prompt else []), input=json.dumps(call),
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "JOURNAL_HOME": str(_TMP / "home"),
                            "JOURNAL_ROOTS": str(_ROOT)})
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else {}


def test_reads_carry_a_journal_note_once_per_user_message():
    """2026-10-24: an answer came from reading code alone; Read, Grep and read-only commands never triggered."""
    _write("SHOP/site/worker.js", "// code\n")
    sid, cwd, rr = "s22", str(_ROOT), {"reports_reads": True}
    _proc({"session_id": sid, "prompt": "ok", **rr}, prompt=True)
    # First read of the project in the session: the gate, then a plain retry is stopped again.
    read = {"session_id": sid, "cwd": cwd, **rr, "tool_name": "Read", "tool_input": {"file_path": "SHOP/site/worker.js"}}
    first = _proc(read)["hookSpecificOutput"]
    assert "permissionDecision" not in first and "SHOP_JOURNAL.md" in first["additionalContext"]
    assert "JOURNAL BRIEF" in first["additionalContext"]  # other tests rewrite SHOP_JOURNAL.md: no content check
    # Reading the journal file itself is never gated (since 5fd26db it may carry the hand-read hint, never a deny);
    # once it ran (the mod reports it), the read passes.
    jr = _proc({**read, "tool_input": {"file_path": str(_ROOT / "SHOP" / "SHOP_JOURNAL.md")}})
    assert "permissionDecision" not in (jr.get("hookSpecificOutput") or {})
    _proc({**read, "tool_input": {"journal_read": str(_ROOT / "SHOP" / "SHOP_JOURNAL.md"), "ok": True}})
    assert _proc(read) == {}
    assert _proc({"session_id": sid, "cwd": cwd, **rr, "tool_name": "Bash", "tool_input": {"command": "cat SHOP/site/worker.js"}}) == {}
    # Later messages: the gate stays open, the first read of each message carries the note until a journal read.
    _proc({"session_id": sid, "prompt": "ok", **rr}, prompt=True)
    _proc({**read, "tool_input": {"journal_read": str(_ROOT / "SHOP" / "SHOP_JOURNAL.md"), "ok": True}})
    assert _proc({"session_id": sid, "cwd": cwd, **rr, "tool_name": "Grep", "tool_input": {"paths": ["SHOP/site"]}}) == {}
    _proc({"session_id": sid, "prompt": "ok", **rr}, prompt=True)
    again = _proc({"session_id": sid, "cwd": cwd, **rr, "tool_name": "Bash", "tool_input": {"command": "cat SHOP/site/worker.js"}})
    assert "permissionDecision" not in again["hookSpecificOutput"]
    assert "SHOP_JOURNAL.md" in again["hookSpecificOutput"]["additionalContext"]

def teardown_function(_):
    os.environ.pop("JOURNAL_AI_CHECKS", None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_command_line_maps_the_script_not_its_arguments():
    # 2026-10-25: "/data/dreamfield/generar.py --pid x" lost the dogfood decision because the argument words
    # (and "x.png") were taken as part of the file name.
    assert srv._file_token("python3 /data/dreamfield/clipgen_i2v.py --image x.png") == "/data/dreamfield/clipgen_i2v.py"
    assert srv._file_token("brake.py") == "brake.py"
    assert srv._quick_terms("python3 /data/dreamfield/clipgen_i2v.py --image x.png") == ["clipgen", "i2v"]
    assert srv._quick_terms("/data/dreamfield/generar.py --pid med1 --secs 12") == ["generar"]


def test_owner_slang_and_typos_never_map():
    # 2026-10-25: a fast message mapped "cloud", "capaz" and "mierda" and missed the owner's credit rule.
    msg = "man capaz hay que ahorrar credito, posta, la mierda esta, cloud code abriendo sesiones demasiado rapido aunque"
    assert _hook({"session_id": "s40", "prompt": msg}, prompt=True) == {}


def test_intent_text_is_the_ai_description():
    import quickmap as q
    assert q._intent_text("Bash", {"command": "ssh x", "description": "File owner order"}) == "File owner order"
    assert q._intent_text("Agent", {"description": "Audit", "prompt": "look at x"}).startswith("Audit. look")
    assert q._intent_text("Read", {"file_path": "a"}) == ""


# ─── Open plans and named things (2026-10-26) ─────────────────────────────────────────────────────────────
# Owner 2026-10-26: "the map must never depend on my exact words". The plan "stream one AI team live on
# mapleworks.dev/live" was one sentence inside a long [ship] entry ("NOT deployed: owner sees a screenshot and
# says publish first"), so "mapleworks" + "en vivo" brought nothing about it.
_LONG_SHIP = """# APPUSER JOURNAL

## Decided
- **Zentro streams its office to the public.** · date: 2026-10-24 · why: owner plan · aliases: live, pantalla abierta, streaming, public office

## 2026-10-23 23:02 [ship] Night build: queue worker, brakes, dashboards and more
- Queue worker retries failed jobs three times and logs each failure to the board.
- Brakes: daily cap per company at 2%, checked every 10 minutes.
- Live view of the Zentro office: captions every 10 min with a 30-min delay. Public office page for zentro.dev/live written, NOT deployed: owner sees a screenshot and says "publish" first.
- Dashboards: the board shows credit and the week.
"""


def _zentro_setup(extra_entries: str = ""):
    _env()
    _write("APPUSER/companies/zentro/company.json", json.dumps({"name": "Zentro", "roles": []}))
    _write("APPUSER/APPUSER_JOURNAL.md", _LONG_SHIP + "".join(
        f"\n## 2026-10-2{4 + i} 09:00 [work] zentro chore {i}\n- Zentro {w} export: NOT deployed yet.\n"
        for i, w in enumerate(("billing", "invoices", "payroll", "taxes"))) + extra_entries)
    _server._index_refresh_internal()


def test_plan_buried_mid_entry_shows_as_open_plan():
    _zentro_setup()
    m = srv.quick_map("zentro")
    assert "zentro" in m["entities"]
    texts = [p["plan"] for p in m["plans"]]
    assert texts and len(texts) <= 3
    # Synonym from the Spanish table and the Decided card's alias cluster: "en vivo" -> live ranks it first.
    m2 = srv.quick_map("zentro en vivo")
    assert "zentro.dev/live" in m2["plans"][0]["plan"] and "NOT deployed" in m2["plans"][0]["plan"]
    assert m2["plans"][0]["journal"] == "APPUSER_JOURNAL.md" and m2["plans"][0]["date"] == "2026-10-23 23:02"
    assert "OPEN PLAN (2026-10-23 23:02, APPUSER_JOURNAL.md:" in srv.quick_map_text(m2)
    # The named thing always brings its own decision, whatever the other words are.
    assert any("Zentro streams its office" in d["what"] for d in m2["decided"])


def test_alias_cluster_expands_a_query_word():
    _zentro_setup()
    ents = srv._entities_in("zentro pantalla abierta")
    groups = srv._query_groups("zentro pantalla abierta", ents)
    assert any("live" in g["phr"] for g in groups if not g["entity"])
    m = srv.quick_map("zentro pantalla abierta")
    assert "zentro.dev/live" in m["plans"][0]["plan"]


def test_owner_message_with_entity_and_spanish_synonym_brings_the_plan():
    _zentro_setup()
    ctx = _hook({"session_id": "s50", "prompt": "che y zentro en vivo?"}, prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert "OPEN PLAN" in ctx and "zentro.dev/live" in ctx
    # Chat words alone still map nothing.
    assert _hook({"session_id": "s51", "prompt": "bueno dale, en vivo lo vemos despues"}, prompt=True) == {}


def test_later_live_entry_closes_the_plan():
    _zentro_setup("\n## 2026-10-29 10:00 [ship] Zentro office page shipped\n"
                  "- Public office page for zentro.dev/live is LIVE: screenshot approved, captions running.\n")
    m = srv.quick_map("zentro en vivo")
    assert not any("zentro.dev/live" in p["plan"] for p in m["plans"])
    assert any("export" in p["plan"] for p in m["plans"])   # the other plans stay open


def test_quoted_marker_and_closed_items_are_not_plans():
    rows = srv._mine_plans('# X\n\n## 2026-10-01 10:00 [incident] lines like "requested from X / NOT deployed" got lost\n'
                           '- The tool should catch "planned" lines.\n- [x] old item, pending before\n'
                           '- One process held 22 GB of RAM.\n- Payroll export planned for next week.\n')
    assert [r[2] for r in rows] == ["Payroll export planned for next week."]


def test_path_with_spaces_is_one_file_not_a_command():
    # 2026-10-26: every edit under "C:/Users/Ann Lee/..." mapped "ann".
    assert srv._quick_terms(r"C:\Users\Ana Maria\Desktop\MY TOOLS\zentro_exporter.py") == ["zentro", "exporter"]
    assert srv._file_token("/data/dreamfield/generar.py --pid med1") == "/data/dreamfield/generar.py"


def test_cards_and_plans_belong_only_to_their_subject():
    """2026-10-26 regression after the named-things map: "tone garden" showed the Launch Desk name card and
    "launch desk" showed the Dreamfield MCP card, because each name appeared somewhere inside the other card;
    a roster line naming every company showed for all of them."""
    _env()
    for slug, name in (("tone-garden", "Tone Garden"), ("launch-desk", "Launch Desk"), ("forecast-desk", "Forecast Desk")):
        _write(f"APPUSER/companies/{slug}/company.json", json.dumps({"name": name, "roles": []}))
    _write("APPUSER/PORTFOLIO_CO_JOURNAL.md", """# PORTFOLIO CO JOURNAL

## Decided
- **The money-hunting product studio is named LAUNCH DESK (ex "Mapleworks Labs") with its own green brand; it never uses the crescent, unlike Tone Garden.** · date: 2026-10-23 · aliases: Launch Desk, Mapleworks Labs, logo, brand

## 2026-10-23 20:55 [ship] Companies roster
- Tone Garden (cap 2%/day), Launch Desk (5 on duty), Forecast Desk (created, NOT started).
""")
    _write("DREAM/DREAMFIELD_JOURNAL.md", """# DREAMFIELD JOURNAL

## Decided
- **The Dreamfield MCP is a CUSTOMER product: each user connects with their own Tone Garden account and credits, never like the Launch Desk experiments.** · date: 2026-10-25 · aliases: dreamfield mcp, customer mcp, credits
""")
    _write("AA/TONE_GARDEN_JOURNAL.md", """# TONE GARDEN JOURNAL

## Decided
- **Tone Garden video plates show the AA logo, then the product's full name.** · date: 2026-10-20 · aliases: plates, logo

## 2026-10-24 10:00 [work] Store
- Payroll of the store: export pending for next week.
""")
    _server._index_refresh_internal()
    aa = srv.quick_map("tone garden")
    aa_cards = " | ".join(d["what"] for d in aa["decided"])
    assert "video plates" in aa_cards
    assert "LAUNCH DESK" not in aa_cards and "Dreamfield MCP" not in aa_cards
    assert not any("roster" in p["plan"] or "Forecast Desk" in p["plan"] for p in aa["plans"])
    assert any("Payroll of the store" in p["plan"] for p in aa["plans"])   # its own journal's plan
    vd = srv.quick_map("launch desk")
    vd_cards = " | ".join(d["what"] for d in vd["decided"])
    assert "LAUNCH DESK" in vd_cards and "Dreamfield MCP" not in vd_cards
    assert not any("Forecast Desk" in p["plan"] for p in vd["plans"])
    # The live plan still comes for "zentro en vivo" (subject of its sentence).
    _zentro_setup()
    assert "zentro.dev/live" in srv.quick_map("zentro en vivo")["plans"][0]["plan"]


def test_chat_words_next_to_a_named_thing_map_nothing():
    """2026-10-26 regression: a report naming "shopsite" once made maps for "pertenencia", "arregle", "mensaje",
    "probado" and "tiempos", each carrying the same cards, because the named thing of the whole message was
    added to the map of every word in it."""
    _env()
    _write("APPUSER/companies/shopsite/company.json", json.dumps({"name": "Shopsite", "roles": []}))
    _write("APPUSER/companies/launch-desk/company.json", json.dumps({"name": "Launch Desk", "roles": []}))
    _write("VDNA/SHOPSITE_JOURNAL.md", """# SHOPSITE JOURNAL

## Decided
- **Shopsite brand names are written with one capital only.** · date: 2026-10-23 · aliases: spelling, brand

## 2026-10-24 10:00 [work] Store
- Shopsite store listing icon: pending.

## 2026-10-25 10:00 [work] Journals hook timing
- Hook timing measured on the journals.
""")
    # Entries TITLED with the chat words: before the fix, a capitalized label ("**Probado**") made them "names".
    _write("PROBE/PROBE_JOURNAL.md", "# PROBE JOURNAL\n\n## 2026-10-12 22:15 [decision] JOURNAL PROBADO CON UNA IA NUEVA\n"
           "probado with a new model.\n\n## 2026-08-11 10:00 [ux] TIEMPOS DE LECTURA\ntiempos de lectura.\n")
    _write("APPUSER/PORTFOLIO_CO_JOURNAL.md", """# PORTFOLIO CO JOURNAL

## Decided
- **The money-hunting product studio is named LAUNCH DESK with its own green brand, never the crescent of Mapleworks or the glyph of Shopsite.** · date: 2026-10-23 · aliases: Launch Desk, logo, brand
""")
    _server._index_refresh_internal()
    for w in ("pertenencia", "arregle", "mensaje", "probado", "tiempos"):
        assert _hook({"session_id": f"s60{w}", "prompt": f"bueno, {w} y listo"}, prompt=True) == {}, w
    msg = ("Arreglé la regresión, lo de Shopsite quedó.\n\n**Pertenencia:** es el tema.\n**Probado** en journals.\n"
           "**Tiempos:** el hook de tu mensaje tarda poco. **Arreglé** todo.\n\n| Mensaje | Tiempo |\n|---|---|\n| ok | 0.3 s |")
    ctx = _hook({"session_id": "s61", "prompt": msg}, prompt=True)["hookSpecificOutput"]["additionalContext"]
    assert ctx.count("JOURNAL QUICK MAP") == 1 and 'MAP for "shopsite"' in ctx
    assert "LAUNCH DESK" not in ctx
    assert ctx.count("Shopsite brand names are written with one capital") == 1


def test_everyday_action_words_never_stop_on_a_decision():
    """2026-10-26: "Run suite and confirm test fails on old code" stopped once on the Adshare AI card because
    "test" sat inside "tested" and "confirm" inside "confirms" (substring hits)."""
    _env()
    _write("ADS/ADS_JOURNAL.md", """# ADS JOURNAL

## Decided
- **Adshare AI is the brain on top of everything: an assistant that routes to existing tested actions and confirms before acting; deterministic code stays as the fallback when the AI fails.** · date: 2026-10-20 · aliases: adshare ai, assistant, brain

## 2026-10-20 10:00 [decision] Adshare AI
- assistant routes to tested actions, confirms before acting.
""")
    _server._index_refresh_internal()
    for intent in ("Run suite and confirm test fails on old code", "Confirm the test fails on old code",
                   "Rerun the full test suite and confirm"):
        im = srv._intent_map(intent)
        assert "DECIDED:" not in im and "OWNER RULE" not in im, (intent, im)
    # The card still stops an action that is really about it.
    assert "DECIDED:" in srv._intent_map("Change the Adshare AI assistant so it routes actions without confirming")


def test_path_tokens_never_map_as_words():
    """2026-10-26: a message carrying a Windows short path (ANNLEE~1 under Users) mapped "annlee"."""
    _env()
    _write("PIER/ANNLEE_JOURNAL.md", "# ANNLEE JOURNAL\n\n## 2026-10-20 10:00 [note] Annlee and Users\nannlee users appdata.\n")
    _server._index_refresh_internal()
    msg = (r"results saved in C:\Users\ANNLEE~1\AppData\Local\Temp\claude\scratchpad\timing.py and "
           "C:/Users/Ann Lee/Desktop/DEV PROJECTS/x/quickmap.py, nothing else")
    out = _hook({"session_id": "s70", "prompt": msg}, prompt=True)
    ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
    assert "annlee" not in ctx.lower() and "appdata" not in ctx.lower()


# ─── Action scope (2026-10-26) ─────────────────────────────────────────────────────────────────────────────
# A Oddsboard session was stopped three times in one evening on cards and rules of other projects: the intent
# map matched the words of the command's description across every journal. The project of an action now comes
# from its input (Brain map and Scope map keys, companies, journal names, paths, fed scripts).
_SSH = "ss" + "h"


def _scope_setup():
    _env()
    _write("PMK/FORECAST_MARKETS_JOURNAL.md", """# FORECAST MARKETS JOURNAL

## Decided
- **The real bot changes its order size only with the owner's GO.** · date: 2026-10-20 · aliases: real bot, order size

## 2026-10-24 10:00 [measure] Real bot fills
- bulkbot fills and payouts counted from the log.
""")
    _write("APPUSER/companies/forecast-desk/company.json", json.dumps({"name": "Forecast Desk", "roles": []}))
    _write("APPUSER/companies/forecast-desk/STARTUP_FCD.md", "Read FORECAST_MARKETS_JOURNAL.md first.\n")
    _write("APPUSER/companies/forecast-desk/manuals/SCOUT_FCD_JOURNAL.md",
           "# SCOUT FCD\n\n## K5. Real bot fills and payouts, light\n- fills and payouts of the real bot.\n")
    _write("MAPS/MAPS_JOURNAL.md", """# MAPS JOURNAL

## Brain map
| Piece | Keys | Working on it now | Read first | Notes |
|---|---|---|---|---|
| Real Oddsboard bot | oddsboard, oddsboard-bot, bulkbot-real, real bot | nobody | PMK/FORECAST_MARKETS_JOURNAL.md | real money |

## Scope map
| Keys | Journals | Project on its own | Notes |
|---|---|---|---|
| fcd-lab, pmdesk | PMK/FORECAST_MARKETS_JOURNAL.md | yes | paper lab |
| gpubox | GPU/STUDIO_DASHBOARD_AND_GPUBOX_JOURNAL.md | no | shared host |
""")
    _write("GPU/STUDIO_DASHBOARD_AND_GPUBOX_JOURNAL.md", "# GPU BOX\n\n## 2026-10-20 10:00 [ops] Disk layout\n- /data holds every lab.\n")
    _write("GROWTH/GROWTH_SAAS_JOURNAL.md", """# GROWTH SAAS JOURNAL

## Decided
- **Onboarding offers two options: 'Find them for me' (the list fills itself) or 'I pick them'; referral payouts are shown weekly.** · date: 2026-10-15 · aliases: onboarding, find them for me, payouts
""")
    _write("MEME/MEMESNIPER_FULL_JOURNAL.md", "# MEMESNIPER\n\n## SEC56 paper-strats tick row (2026-06-13)\n"
           "- paper lab layout of the strats, mapped on the box.\n\n## SEC49 real fills and payouts\n- real fills, payouts.\n")
    _write("OWNER_SAID_JOURNAL.md", """# OWNER SAID

## Rules
- 2026-10-25: Team HQ and every company app have a real desktop layout on every tab (Team, Map, Dashboard, Social, Library), not the phone column stretched; phone layout stays for phones. The Map must be visual (owner, PC chat)
- 2026-10-25: Learning is automatic: every owner conversation is mined in the same turn for corrections, preferences, rules and fixes, which go to this journal and the role manuals (owner, PC chat)
""")
    _server._index_refresh_internal()


def _tool(sid: str, desc: str, cmd: str, cwd: str = "") -> dict:
    return _hook({"session_id": sid, "tool_name": "Bash", "cwd": cwd,
                  "tool_input": {"command": cmd, "description": desc}}).get("hookSpecificOutput") or {}


def test_oddsboard_command_never_stops_on_another_products_card():
    """Case a, 2026-10-25: "Find real bot fills and payouts on 25/10" over the bulkbot log stopped on Growvine's
    onboarding card ("Find them for me ... fills itself") and listed MEMESNIPER and ebook entries."""
    os.environ["JOURNAL_AI_CHECKS"] = "risky"  # the strict stop exists only with per-call checks on
    _scope_setup()
    h = _tool("s80", "Find real bot fills and payouts on 25/10",
              f"{_SSH} vpsone 'grep fill /opt/oddsboard-bot/data/bulkbot_real.log | tail -50'")
    assert h.get("permissionDecision") != "deny", h
    ctx = h.get("additionalContext", "")
    assert "Onboarding" not in ctx and "MEMESNIPER" not in ctx and "GROWTH_SAAS" not in ctx, ctx
    # Its own project's card still stops an action that is really about it.
    h = _tool("s81", "Change the real bot order size",
              f"{_SSH} vpsone 'sed -i s/size=5/size=9/ /opt/oddsboard-bot/config.py'")
    assert h.get("permissionDecision") == "deny" and "order size" in h["permissionDecisionReason"], h


def test_box_script_belongs_to_the_project_it_reads():
    """Case b: "Map the paper lab layout on the box" (ssh gpubox bash -s < lab_layout.sh, the script reads
    /data/fcd-lab) stopped on the owner's Team HQ desktop-layout rule and listed MEMESNIPER SEC56."""
    _scope_setup()
    work = _TMP / "work_b"
    work.mkdir(exist_ok=True)
    (work / "lab_layout.sh").write_text("ls -la /data/fcd-lab\ndu -sh /data/fcd-lab/*\n", encoding="utf-8")
    h = _tool("s82", "Map the paper lab layout on the box", f"{_SSH} gpubox bash -s < lab_layout.sh", str(work))
    assert h.get("permissionDecision") != "deny", h
    ctx = h.get("additionalContext", "")
    assert "Team HQ" not in ctx and "MEMESNIPER" not in ctx, ctx
    s = srv._action_scope("Bash", {"command": f"{_SSH} gpubox bash -s < lab_layout.sh"}, "", str(work))
    assert {"FORECAST_MARKETS_JOURNAL.md", "SCOUT_FCD_JOURNAL.md", "STUDIO_DASHBOARD_AND_GPUBOX_JOURNAL.md"} <= s["jnames"]
    assert "GROWTH_SAAS_JOURNAL.md" not in s["jnames"]
    # A shared host alone names no project.
    assert srv._action_scope("Bash", {"command": f"{_SSH} gpubox uptime"}, "Check the box") == {}
    # A path under a journal root names its project folder, also written the Git Bash way ("/c/Users/...").
    if sys.platform != "win32":
        return   # the Git Bash form of a path exists only on Windows
    p = str(_ROOT).replace("\\", "/")
    gb = "/" + p[0].lower() + p[2:]
    s = srv._action_scope("Bash", {"command": f'cd "{gb}/PMK/tools" && python run.py > out.txt'}, "Run it")
    assert "FORECAST_MARKETS_JOURNAL.md" in s["jnames"] and "GROWTH_SAAS_JOURNAL.md" not in s["jnames"]


def test_global_owner_rule_needs_three_specific_words_to_stop():
    """Case c: "Log the owner's correction to the debug journal" stopped on the owner's learning rule on 2 words
    (correction, journal). Without a project it is a note; a rule sharing 3+ specific words still stops."""
    os.environ["JOURNAL_AI_CHECKS"] = "risky"  # the strict stop exists only with per-call checks on
    _scope_setup()
    h = _tool("s83", "Log the owner's correction to the debug journal",
              "echo '{\"m\": 1}' >> ~/.claude/debug-journal/journal.jsonl")
    assert h.get("permissionDecision") != "deny", h
    assert "OWNER RULE:" not in h.get("additionalContext", "")
    h = _tool("s84", "Mine every owner conversation for preferences, rules and fixes",
              "python miner.py > ~/out.txt")
    assert h.get("permissionDecision") == "deny" and "Learning is automatic" in h["permissionDecisionReason"], h


def _verdict_fixture():
    _write("STUDIO/STUDIO_JOURNAL.md", "# STUDIO JOURNAL\n\n"
           "## 2026-10-15 22:12 [test] Glowcam Ray loop=true on the clouds\n"
           "Native loop switch, 5 s 720p, file gen/glowcam_loop_rejected.mp4. Measured join 1.4x.\n\n"
           "## 2026-10-15 22:16 [decision] Owner verdict on Glowcam Ray native loop\n"
           "Veredicto de Owner sobre Glowcam Ray con loop nativo: \"esta bueno pero el loop no es seamless\". "
           "Pending: wire it into the studio.\n\n"
           "## 2026-10-15 22:30 [test] mandala blender geometry\n"
           "Veredicto de Owner sobre las geometrias de Blender: \"muy rigidas\".\n\n"
           "## 2026-10-16 10:00 [test] Blender volumetric clouds for loops\n"
           "Owner verdict on Blender clouds: \"se ven de plastico\".\n")
    _server._index_refresh_internal()


def test_map_shows_the_owner_verdict_written_in_a_plain_entry():
    # 2026-10-26: the map showed only "pending: wire Glowcam loop into the studio", never the verdict in the same
    # entry, and a session proposed the tested method as new.
    _verdict_fixture()
    m = srv.quick_map("glowcam")
    said = [v["said"] for v in m["verdicts"]]
    assert said and "no es seamless" in said[0]
    assert all("rejected.mp4" not in s for s in said)   # a file name is not a verdict
    assert "OWNER SAID ON IT" in srv.quick_map_text(m)


def _reply(text: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        srv.reply_check({"reply": text})
    return json.loads(buf.getvalue())["hookSpecificOutput"]["additionalContext"] if buf.getvalue().strip() else ""


def test_reply_that_proposes_a_tried_method_gets_the_owner_verdict():
    _verdict_fixture()
    note = _reply("Lo que hago ahora: conecto el loop de Glowcam al estudio y lo pruebo con la foto. Le doy?")
    assert "no es seamless" in note
    # the reply is about clouds: the Blender verdict on clouds ranks above the one on mandala geometry
    note = _reply("Propongo nubes volumetricas en Blender para los loops de clouds, con ruido en circulo. Le doy?")
    lines = [l for l in note.splitlines() if l.startswith("- blender")]
    assert lines and "plastico" in lines[0]


def test_reply_that_proposes_nothing_is_not_checked():
    _verdict_fixture()
    assert _reply("Listo: borre las copias de Glowcam en D: y libere 1.3 GB.") == ""


def test_reply_skips_verdicts_of_other_projects_and_shared_names_only():
    """2026-10-27: an Instagram map for Mapleworks got High Tide reel verdicts and an BOLTLAB widget verdict
    (it shared only the names "tone garden" with the reply). Another project's journal is noise once the reply
    names its own project; a verdict needs a topic word in common beyond the names."""
    _verdict_fixture()
    _write("HIGH TIDE MUSIC/HIGH_TIDE_MUSIC_JOURNAL.md", "# HVM\n\n"
           "## 2026-06-26 02:40 [todo] IG reels\n"
           "Owner: \"use social engine for instagram reels of hvm\".\n")
    _write("BOLTLAB/BOLTLAB_ECOSYSTEM_JOURNAL.md", "# BOLTLAB\n\n"
           "## 2026-07-08 13:27 [decision] chatbot pattern\n"
           "Owner: \"check tone garden instagram how we are doing it there, dont reinvent the widget\".\n")
    _write("MAPLEWORKS/MAPLEWORKS_JOURNAL.md", "# MAPLEWORKS\n\n"
           "## 2026-10-22 16:35 [decision] posts\n"
           "Owner: \"instagram posts of mapleworks show one company per carousel\".\n")
    _server._index_refresh_internal()
    note = _reply("Propongo el mapa de Instagram de Mapleworks: 5 posts por semana, como el Comment STUDIO "
                  "de Tone Garden. Le doy?")
    assert "HIGH_TIDE" not in note and "BOLTLAB" not in note, note
    assert "MAPLEWORKS_JOURNAL" in note, note




def _replaced_fixture():
    # The journals as they were BEFORE the 2026-10-27 [fix] entry: an older entry ties the Library to
    # media-library.js; newer App Studio entries (another journal) say the tabs were redesigned and the library in
    # the company apps is the "old library"; another product's journal has its own "Library tab" redesign.
    _write("APPUSER/APPUSER_JOURNAL.md", "# APPUSER JOURNAL\n\n"
           "## 2026-10-22 23:51 [ship] Library tab in the AA box app\nIndexer library_index.py every 10 min.\n\n"
           "## 2026-10-23 01:25 [fix] Library deep links left the owner at the top\n"
           "Fix in media-library.js reveal(): open the file anyway when the link is not indexed yet.\n")
    _write("APPUSER/manuals/APPSTUDIO_JOURNAL.md", "# APPSTUDIO JOURNAL\n\n## Work log\n"
           "- 2026-10-25 16:45 UTC | work | Tab redesign step 1: Team, Map, Dashboard, Social, Library; new basic "
           "Dashboard and Library for every company.\n\n"
           "## 2026-10-25 19:41 [ship] Step 1 (5 tabs) LIVE\n"
           "Checked live files. One fault: AA phone Library has sideways scroll from the old library's project "
           "<select> (.lib-filters, 21 px).\n\n"
           "## 2026-10-25 19:50 [work] Global Library built\n"
           "Reuses media-library.js (old Studio library) instead of new code: mount(el,{global:true}) in hub.html.\n")
    _write("AASITE/AASITE_JOURNAL.md", "# AASITE JOURNAL\n\n## 2026-10-25 21:58 [ship] Site suite\n"
           "Site integrates tool-redesign-1 + ONE Library tab.\n")
    _server._index_refresh_internal()




def test_a_file_name_word_is_not_a_multi_word_piece_key():
    # 2026-10-27: real_test.py (a Playwright check of the HQ app) was stopped as the "Real Oddsboard bot" piece:
    # one word of the key "real bot" was enough.
    _env()
    _write("PM/PM_JOURNAL.md", "# PM JOURNAL\n\n## Brain map\n| Piece | Keys | Working on it now | Read first | Notes |\n"
           "|---|---|---|---|---|\n| Real Oddsboard bot | oddsboard, bulkbot-real, real bot | owner only | "
           "PM/PM_JOURNAL.md | never touch without go |\n")
    _server._index_refresh_internal()
    assert srv.quick_map("C:/tmp/panel/real_test.py", cards=False)["pieces"] == []
    assert srv.quick_map("C:/bots/real_bot.py", cards=False)["pieces"]   # the whole key still maps
    r = _hook({"session_id": "rt1", "reports_reads": True, "tool_name": "Write",
               "tool_input": {"file_path": "C:/tmp/panel/real_test.py", "content": "print(1)\n"}})
    assert r.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


# Real intent-map lines of 2026-10-27 (main PC session driving box Chromes): ~12 stops in a row, one per step,
# each with another line of OWNER_SAID or WEBWEAVE_JOURNAL, even right after reading both journals.
_IM_OWNER = ('JOURNALS FOR WHAT YOU ARE ABOUT TO DO ("Click Continue in Meta Developers registration"):\n'
             "- OWNER RULE: 2026-10-27: Launch Desk gets its OWN Meta identity with nothing tied to the owner: a "
             "non-owner email (trydesk domain or another), its own Facebook account, Meta Developers app\n"
             "If one of these already covers it, extend or follow it; never file or build a duplicate.")
_IM_OWNER2 = _IM_OWNER.replace("2026-10-27: Launch Desk gets its OWN Meta identity", "2026-10-26: Companies create "
                               "and connect their own accounts end to end")
_IM_WEBWEAVE = ('JOURNALS FOR WHAT YOU ARE ABOUT TO DO ("Open Facebook Page creation with box Webweave"):\n'
               "- DECIDED: Never launch Chrome by hand; when a session shows offline use Webweave's own launcher "
               "(WEBWEAVE_JOURNAL.md)\n")
_IM_WEBWEAVE2 = _IM_WEBWEAVE.replace("Never launch Chrome by hand; when a session shows offline use Webweave's own "
                                   "launcher", "No personal data in anything public")


def test_intent_stop_once_per_card_and_never_after_its_journal_was_read():
    seen = {}
    assert srv._intent_stops_fresh(_IM_OWNER, seen) is True        # first time: stop
    assert srv._intent_stops_fresh(_IM_OWNER, seen) is False       # the same rule under another step: never again
    assert srv._intent_stops_fresh(_IM_WEBWEAVE, seen) is True      # a NEW journal's card: stop once
    # once the journal was read in the session, another line of it never stops
    seen.setdefault("jt", {})["webweave"] = 1.0
    seen["jt"]["ownersaid"] = 1.0
    assert srv._intent_stops_fresh(_IM_WEBWEAVE2, seen) is False
    assert srv._intent_stops_fresh(_IM_OWNER2, seen) is False


def test_journal_reads_count_with_every_argument_name_and_with_sed():
    # 2026-10-27: journal_handoff_brief(name="AI_TEAM_JOURNAL.md") and (project="WEBWEAVE") were not recorded
    # (only name_or_path was read); `sed -n 3550,3566p WEBWEAVE_JOURNAL.md` never counted at all.
    _env()
    import quick_hook
    sid = "args-%d" % os.getpid()
    for args, key in (({"name": "AI_TEAM_JOURNAL.md"}, "aiteam"), ({"project": "WEBWEAVE"}, "webweave"),
                      ({"path": "C:/x/OWNER_SAID_JOURNAL.md", "section": "Rules"}, "ownersaid"),
                      ({"journal": "SHOP"}, "shop")):
        tool = "mcp__journal__journal_read_section" if "section" in args else "mcp__journal__journal_handoff_brief"
        _record({"session_id": sid, "reports_reads": True, "tool_input": {
            "journal_tool": tool, "args": args, "text": "# brief ...", "ok": True}})
        f, seen = quick_hook._state({"session_id": sid})
        assert key in seen.get("jt", {}), (args, seen.get("jt"))
    sid2 = sid + "-sed"
    quick_hook.read_turn({"session_id": sid2, "reports_reads": True, "tool_name": "Bash", "cwd": str(_ROOT),
                          "tool_input": {"command": 'cd "C:/x/NANO"; sed -n 3550,3566p LOCALMODEL/LOCALMODEL_JOURNAL.md | cut -c1-900'}})
    f, seen = quick_hook._state({"session_id": sid2})
    assert "localmodel" in seen.get("jt", {})


def test_a_container_folder_journal_does_not_gate_another_tool_inside_it():
    # 2026-10-27: running the gmail tool in TOOL SHOP/servers/gmail-mcp was stopped 6 times for the journal of the
    # journal tool (JOURNAL_MCP_JOURNAL.md sits at the top of TOOL SHOP, a folder of dozens of tools).
    _env()
    _write("TOOLBOX/JOURNAL_MCP_JOURNAL.md", "# JOURNAL MCP JOURNAL\n\n## 2026-10-20 10:00 [ship] quick map\nx\n")
    _write("TOOLBOX/servers/gmail-mcp/server.py", "# gmail\n")
    _write("TOOLBOX/servers/journal-mcp/quickmap.py", "# map\n")
    import quick_hook
    hit = quick_hook._journal_folder(str(_ROOT / "TOOLBOX/servers/gmail-mcp/server.py"), "")
    assert hit and not quick_hook._folder_owns(hit, str(_ROOT / "TOOLBOX/servers/gmail-mcp/server.py"), "")
    assert quick_hook._folder_owns(hit, str(_ROOT / "TOOLBOX/servers/journal-mcp/quickmap.py"), "")
    out = _proc({"session_id": "box-gm", "tool_name": "Grep",
                 "tool_input": {"paths": [str(_ROOT / "TOOLBOX/servers/gmail-mcp/server.py")]}})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"














def test_reply_pending_check_skips_ships_older_than_an_open_claim_and_context_names():
    """Live replay 2026-10-28: "Webweave: arreglar launch_session" was flagged by a 10-24 "[ship] Box employees get
    Webweave" although a 10-26 entry says "Webweave fix pending: launch_session"; "Buyers copy: ... the journals mod"
    was flagged by a journals mod ship (the label says what is pending, the rest is context)."""
    _write("LOOMX/LOOMX_JOURNAL.md", "# LOOMX\n\n"
           "## 2026-10-24 00:00 [ship] Box employees get LoomKit sessions LIVE\nLoomKit local session slots for employees.\n\n"
           "## 2026-10-26 00:26 [plan] LoomKit next\nLoomKit fix pending: launch_session must not open a local Chrome.\n\n"
           "## 2026-10-26 17:08 [ship] Journals mod 0.5.0 LIVE\nThe journals mod now ports the quick map to every copy.\n")
    _server._index_refresh_internal()
    assert _reply("**Pendiente**\n- [ ] LoomKit: arreglar launch_session para que no abra Chrome local.") == ""
    assert "WRONG" not in _reply("**Pendiente**\n- [ ] Buyers copy: port quickmap.py and the journals mod; owner GO.")


def test_reply_pending_in_a_table_with_a_multiword_name_in_spanish():
    """Real case 2026-10-28 ~01:25 UTC: a reply told the owner, in a TABLE under "## Qué falta para abrirla", that the
    "Melodía de MIDI Tools con sonido real" was still to do (a synthetic voice), while the journal shipped "MIDI TOOLS
    MELODY ON HAVEN'S ENGINE: LIVE" the day before. The header did not START with "Falta", table rows were not
    items, "MIDI" alone matched the catalog card, and melodía/sonido never met melody/sound."""
    _write("TONE GARDEN/AA_TEST_JOURNAL.md", "# AA TEST JOURNAL\n\n"
           "## 2026-10-26 18:56 [feature] MIDI TOOLS SUITE CHANNEL (not committed)\nMIDI Tools channel built on the PC, "
           "not committed, not deployed.\n\n"
           "## 2026-10-26 19:49 [fix] MIDI Tools melody too loud\nThe melody plays on a preview voice; open: a real sound.\n\n"
           "## 2026-10-26 20:39 [ship] MIDI TOOLS MELODY ON HAVEN'S ENGINE: LIVE 2026-10-26\nThe MIDI Tools melody "
           "now plays on Haven's engine with a soft preset (Glass Keys), live in the suite.\n")
    _server._index_refresh_internal()
    reply = ("**Dónde está:** la Suite está en vivo pero privada.\n\n## Qué falta para abrirla\n\n"
             "| # | Qué | Quién |\n|---|---|---|\n"
             "| 3 | **Melodía de MIDI Tools con sonido real**: hoy usa una voz sintética. Opciones: Haven con un "
             "preset suave, o un instrumento de nuestros packs | Vos elegís |\n\n¿Arranco?")
    note = _reply(reply)
    assert note.startswith("WRONG IN YOUR LAST REPLY"), note
    assert "- midi tools:" in note and "2026-10-26 20:39" in note, note
    # the same table under a done header is not a warning
    assert "WRONG" not in _reply("## Hecho\n\n| Qué | Estado |\n|---|---|\n| **Melodía de MIDI Tools**: "
                                 "toca con Haven suave | en vivo |")


def test_reply_precedent_and_company_names_are_not_pending_things():
    """Live false positives 2026-10-28: "Te recomiendo 2% por día, que es lo mismo que hicimos con Launch Desk"
    (a precedent) and a pending table row naming "Tone Garden" (a company name) were flagged as shipped things."""
    _write("AI TEAM/APPUSER_TEST_JOURNAL.md", "# APPUSER TEST\n\n## 2026-10-27 18:22 [ship] LAUNCH DESK BACK WITH CREDIT\n"
           "Launch Desk got 2% a day and its Director was woken.\n")
    _server._index_refresh_internal()
    assert "WRONG" not in _reply("Para que lo arregle ya, hay que darle crédito. Te recomiendo 2% por día, "
                                 "que es lo mismo que hicimos con Launch Desk. ¿Le doy?")
    assert "WRONG" not in _reply("## Qué falta\n\n| # | Qué |\n|---|---|\n| 1 | **Prueba como comprador de Tone Garden**: "
                                 "entrar con una cuenta, que todo suene | Yo |")




def _reply_in(text: str, session: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        srv.reply_check({"reply": text, "session_id": session})
    return json.loads(buf.getvalue())["hookSpecificOutput"]["additionalContext"] if buf.getvalue().strip() else ""


def _dreamfield_fixture(handoff: str):
    _write("TONE GARDEN/DREAMFIELD_TEST_JOURNAL.md", "# DREAMFIELD TEST\n\n## Handoff for next session\n" + handoff +
           "\n\n## 2026-10-16 17:56 [ship] DEFAULT = Clipgen 1.5 pro\nClipgen 1.5 pro is the studio default model now, "
           "live for every new clip.\n\n"
           "## 2026-10-27 13:13 [estado] RELEASES measured live\nSeven releases are out on Spotify.\n\n"
           "## 2026-10-27 14:28 [decision] OWNER 2026-10-27: REDO THE RELEASES, little by little\nOne release at a time.\n\n"
           "## 2026-10-27 18:34 [incident] fal account locked after Inner Sight try 7\nNo more generation until top-up.\n")
    _write("CONTENT AGENCY/CONTENT_AGENCY_TEST_JOURNAL.md", "# AGENCIA\n\n"
           "## 2026-10-12 22:22 [ship] Stock de Pexels listo en las 9 cafeterias\nPexels stock clips downloaded and live "
           "for the coffee shops: 12 photos and 5 clips each.\n\n"
           "## 2026-10-15 21:26 [test] Clipgen template E\nPendiente el veredicto de Owner y el resultado de E con Clipgen.\n")
    _server._index_refresh_internal()


def test_brief_says_the_handoff_is_behind_and_lists_what_came_after_owner_first():
    """Real case 2026-10-28: a session stopped when fal ran dry and never replaced the Dreamfield Handoff (01:50 UTC,
    an ad run); the next session read it as current. 20 entries written after it held the day's real thread."""
    _dreamfield_fixture("HANDOFF 2026-10-27 ~01:50 UTC (PC session). Waiting for the owner's verdict on the ad.")
    out = _server.journal_handoff_brief("DREAMFIELD_TEST_JOURNAL.md")
    assert "HANDOFF IS BEHIND" in out and "3 entries came after it" in out, out
    behind = out.split("HANDOFF IS BEHIND", 1)[1].split("## Handoff", 1)[0]
    assert behind.index("REDO THE RELEASES") < behind.index("RELEASES measured live") < behind.index("fal account locked")
    assert "DEFAULT = Clipgen" not in behind   # written before the Handoff
    # the quick map of the project word says it too
    assert "HANDOFF IS BEHIND" in srv.quick_map_text(srv.quick_map("dreamfield"))
    # a Handoff written through the tool is stamped with the heading clock; a fresh one carries no warning
    _server.journal_update_section("DREAMFIELD_TEST_JOURNAL.md", "Handoff for next session", "Redo releases: Inner Sight next.")
    out = _server.journal_handoff_brief("DREAMFIELD_TEST_JOURNAL.md")
    assert "<!-- written 20" in out and "HANDOFF IS BEHIND" not in out, out
    _server.journal_update_section("DREAMFIELD_TEST_JOURNAL.md", "Handoff for next session", "Second write.")
    assert out.count("<!-- written") == 1 and _server.journal_handoff_brief("DREAMFIELD_TEST_JOURNAL.md").count("<!-- written") == 1


def test_reply_check_false_alarms_of_20261028():
    """Live false alarms 2026-10-28 on a Dreamfield reply: (1) "la biblioteca de stock (483 clips de Pexels) ya esta
    restaurada ... el unico que falta" was flagged against a Pexels ship of the content agency; (2) "probar Clipgen
    1.5 pro" against the ship that made it the default; (3) "Pendiente el veredicto de Owner" shown as what the owner
    said; (4) "Content Agency", named as a journal, pulled that journal's quotes."""
    _dreamfield_fixture("HANDOFF 2026-10-28 ~01:10 UTC. Redo releases.")
    stock = ("**Lo que arreglé:**\n- Aparte, otra sesión borró la biblioteca de stock (483 clips de Pexels) y ya está "
             "restaurada: volvieron 482. El único que falta lo bajaron de Pexels.")
    assert "WRONG" not in _reply(stock)
    assert "WRONG" not in _reply("**El plan:**\n- [ ] ⏳ **Si no te convence, probar Clipgen 1.5 pro**: es el único "
                                 "modelo que no probamos en esta foto.")
    note = _reply("Propongo seguir con Clipgen en Inner Sight, con el armador de prompts. ¿Le doy?")
    assert "Pendiente el veredicto" not in note, note
    note = _reply("Te propongo filtrar por proyecto: me marcó Pexels de otro proyecto (Content Agency). ¿Lo arreglo?")
    assert "CONTENT_AGENCY" not in note, note


def test_reply_ship_of_another_project_does_not_count_when_the_session_works_elsewhere():
    """A pending thing whose only ship lives in a project the session never read nor named is another thing with the
    same name (2026-10-28: Pexels stock of the coffee shops vs Dreamfield's stock library)."""
    _dreamfield_fixture("HANDOFF 2026-10-28 ~01:10 UTC. Redo releases.")
    pending = "**Pendiente**\n- [ ] ⏳ **Pexels stock**: bajar de nuevo los clips para las piezas"
    assert _reply(pending).startswith("WRONG")           # no session scope: every journal counts
    f, _ = srv._quick_seen("sess-dreamfield")
    f.write_text(json.dumps({"rr": 1, "jr": {"dreamfieldtest": 2}}), encoding="utf-8")
    assert "WRONG" not in _reply_in(pending, "sess-dreamfield")
    f.write_text(json.dumps({"rr": 1, "jr": {"contentagencytest": 2}}), encoding="utf-8")
    assert _reply_in(pending, "sess-dreamfield").startswith("WRONG")


def test_owner_verdict_without_the_word_verdict_is_found():
    """Real miss 2026-10-28: the Inner Sight verdict lived only as "owner still sees the camera move in the crossing"
    inside a summary line; the map never showed it and a session re-showed the rejected H3 grid as pending."""
    _write("TONE GARDEN/INNERSIGHT_TEST_JOURNAL.md", "# T\n\n## 2026-10-27 18:18 [test] INNERSIGHT fast try with the fixed armador\n"
           "Eye rejected: rings. Summary of today on this photo: hthree = style kept, zoom 1.2% (dezoom fixes the measure, "
           "owner still sees the camera move in the crossing); lockcam = jitter.\n")
    _server._index_refresh_internal()
    said = [v["said"] for v in srv.quick_map("innersight")["verdicts"] if v.get("owner")]
    assert any("owner still sees the camera move" in s for s in said), said


def test_a_two_word_file_stem_needs_its_words_together_for_a_replacement():
    """Live false stop 2026-10-28: with_keys.py was stopped as REPLACED by "Keys (owner rule): ANTHROPIC_API_KEY ...
    replaced with vault" (the words "keys" and "with" loose in a sentence about another thing)."""
    _write("TOOLS/TOOLS_TEST_JOURNAL.md", "# T\n\n## 2026-10-20 10:00 [ship] with_keys runner\nwith_keys.py runs a command "
           "with vault fields.\n\n## 2026-10-27 20:36 [fix] owner keys\nKeys (owner rule): the API key in production "
           "replaced with vault apikey. with_keys.py untouched.\n")
    _server._index_refresh_internal()
    assert srv.newer_about("C:/x/with_keys.py") == {}


def test_command_output_names_a_thing_the_owner_already_corrected():
    """2026-10-28: `systemctl --failed` on the box listed starpair-drip, clip-farm and xvfb-game; the owner had said
    on 2026-10-23 ("Owner correction") that they are NOT outages to report, and the session reported them anyway: the
    mod never read what a command returned, and "Owner correction" was not an owner verdict."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("BOX/BOX_JOURNAL.md", "# BOX\n\n"
           "## 2026-10-23 13:18 [correction] SUPERSEDES the line about units seen down\n"
           "Seen down: starpair-drip, clip-farm. Owner correction 2026-10-23: these are NOT outages to report. "
           "starpair-drip.service is a leftover.\n\n"
           "## 2026-10-23 14:00 [work] queue\nowner said the owner orders board is fine.\n")
    _server._index_refresh_internal()
    buf = io.StringIO()
    with redirect_stdout(buf):
        hit = srv.output_check({"output": "starpair-drip.service loaded failed failed\nclip-farm.service failed\n"
                                          "owner_orders.json company_status.json"}, set())
    out = buf.getvalue()
    assert "NOT outages to report" in out and "starpair-drip" in out and "clip-farm" in out
    assert "owner_orders" not in hit   # a common name split by FTS never borrows an unrelated owner sentence
    buf = io.StringIO()
    with redirect_stdout(buf):
        srv.output_check({"output": "starpair-drip.service loaded failed failed"}, hit)
    assert buf.getvalue() == ""        # once per session per name


def test_git_status_lists_files_that_only_changed_line_endings(tmp_path, capsys):
    """Real case 2026-10-28: 82 shopsite-site files showed as modified and were reported to the owner as other
    sessions' unpublished work; they differed from the commit only by CRLF. The mod now says so."""
    import subprocess as sp
    import quickmap
    repo = tmp_path / "site"
    repo.mkdir()
    sp.run(["git", "init", "-q", str(repo)], check=True)
    for i in range(5):
        (repo / f"f{i}.ts").write_bytes(b"line one\nline two\n")
    sp.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "add", "."], check=True)
    sp.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], check=True)
    for i in range(4):
        (repo / f"f{i}.ts").write_bytes(b"line one\r\nline two\r\n")       # line endings only
    (repo / "f4.ts").write_bytes(b"line one\nline two CHANGED\n")          # a real change
    out = "\n".join(f" M f{i}.ts" for i in range(5))
    call = {"tool_input": {"command": f'cd "{repo}" && git status --short'}, "output": out, "cwd": str(tmp_path)}
    shown = set()
    hit = quickmap.git_eol_check(call, shown)
    text = capsys.readouterr().out
    assert hit and "4 of 5 modified files differ ONLY by line endings" in text and "f4.ts" in text
    assert quickmap.git_eol_check(call, hit) == set()                      # once per repo per session
    call2 = {"tool_input": {"command": "git log --oneline -3"}, "output": out}
    assert quickmap.git_eol_check(call2, set()) == set()                   # only git status / diff


def test_vault_key_shows_the_newest_entry_that_names_it():
    """2026-10-29: the map showed the key ai-subscription-token-vpsone; the session read the 17:30 accounts map
    ("runs on vpsone") and told the owner the account was shared with vpsone, while a 19:02 entry in ANOTHER
    journal, naming the same key, said vpsone was shut down. The newest entry naming a key now shows beside it."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("COMP/COMP_JOURNAL.md", "# COMP\n\n## 2026-10-28 17:30 [fact] ACCOUNTS MAPPED\n"
           "| mainacct | vault deploytoken-hetz-max | runs on vpsone, freelance brain |\n")
    _write("FREE/FREE_JOURNAL.md", "# FREE\n\n## 2026-10-28 19:02 [incident] VPSONE KEPT RUNNING, now stopped\n"
           "Its brain used the vault deploytoken-hetz-max. Off now: cron lines commented, services disabled.\n\n"
           "## 2026-10-28 20:00 [work] unrelated\nthe deploytoken-hetz-max-old file was removed.\n")
    _server._index_refresh_internal()
    (_TMP / "vault_names.json").write_text(json.dumps({"entries": [
        {"name": "deploytoken-hetz-max", "category": "api", "fields": ["CLAUDE_CODE_OAUTH_TOKEN"]}]}))
    try:
        m = srv.quick_map("deploytoken")
        v = m["vault"][0]
        assert v["latest"][0]["journal"] == "FREE_JOURNAL.md" and "stopped" in v["latest"][0]["entry"]
        assert all("removed" not in x["said"] for x in v["latest"])   # a longer name is another key
        txt = srv.quick_map_text(m)
        assert "NEWEST WORD ON 'deploytoken-hetz-max' (2026-10-28 19:02" in txt
    finally:
        (_TMP / "vault_names.json").unlink()


def _today(hours_back: int = 0) -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")


def test_reply_says_a_host_uses_a_thing_after_that_host_was_shut_down():
    """2026-10-29: the reply told the owner 'vpsone uses mainacct and shares its week'; an entry 4 h older, in
    another journal, said vpsone was shut down. The reply check now shows the newer shutdown."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("FREE2/FREE2_JOURNAL.md", "# FREE2\n\n"
           f"## {_today(4)} [incident] THE SHUTDOWN ONLY STOPPED THE PC: HETZBOX KEPT RUNNING\n"
           "Found and stopped. Off now: hetzbox cron lines commented, services disabled.\n\n"
           "## 2026-01-02 10:00 [infra] old\nhetzbox was shut down for a day in January.\n")
    _server._index_refresh_internal()
    note = _reply("Lo que no hay que tocar: Hetzbox ya usa mainacct, va a compartir la semana con las compañías.")
    assert "CHECK THIS CLAIM" in note and "hetzbox" in note and "KEPT RUNNING" in note
    assert "January" not in note                     # only the last 10 days count
    assert "CHECK THIS CLAIM" not in _reply("El plan: hetzbox queda igual, le paso los numeros de hoy.")
    # 2026-10-29 noise on the reply that described this check: a quoted example is not a claim, and a common word
    # next to "corre" ("el chequeo ... corre") is not a name
    _write("FREE2/WARM_JOURNAL.md", "# WARM\n\n"
           f"## {_today(2)} [rule] public check\nEl chequeo deslogueado queda apagado salvo public_check.\n")
    _server._index_refresh_internal()
    assert "CHECK THIS CLAIM" not in _reply("Lo probé con la frase real de hoy (\"Hetzbox ya usa mainacct\") y la marca.")
    assert "CHECK THIS CLAIM" not in _reply("Ahora el chequeo corre en la caja y avisa.")
    # a newer entry that only CITES the shutdown ("now shows FREE2_JOURNAL.md:3 ...") never replaces the real one
    _write("FREE2/TOOL_JOURNAL.md", "# TOOL\n\n"
           f"## {_today(1)} [fix] reply check\nReal replay now shows FREE2_JOURNAL.md:3 (HETZBOX KEPT RUNNING, stopped).\n")
    _server._index_refresh_internal()
    note = _reply("Lo que no hay que tocar: Hetzbox ya usa mainacct, va a compartir la semana con las compañías.")
    assert "FREE2_JOURNAL.md" in note and "TOOL_JOURNAL" not in note, note


def test_long_pending_label_keeps_names_in_its_detail_out():
    """2026-10-29: a 52-char bold label failed the label match, the whole line became the subject and "Owner Proxy"
    in its detail was flagged against an unrelated [ship] "Owner Proxy guard"."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("PROXY/PROXY_JOURNAL.md", "# PROXY\n\n"
           "## 2026-10-28 02:28 [ship] OWNER DIRECTION FROM ALL HIS CHATS + Owner Proxy guard\n"
           "The Owner Proxy guard is live: it reads every owner chat and restarts nothing.\n")
    _server._index_refresh_internal()
    line = ("**El plan:**\n- [ ] ⏳ **Pasar a la cuenta nueva a los que ya están corriendo**: siguen con la llave vieja "
            "hasta que reinician. Los que nunca se apagan (Supervisor, Owner Proxy, chat en vivo) los reinicio enseguida.")
    assert "WRONG" not in _reply(line)


def test_credit_table_of_companies_pulls_no_owner_quotes():
    """2026-10-29: a reply proposing credit caps per company pulled a June Boltlab dashboard verdict and Adshare
    quotes into the reply check: a company name is context, never the thing proposed (same rule as the pending check)."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    # the verdict sits in the company's own journal, so the "reply names a project" filter keeps it in play
    _write("IVYX/GROWVINE_JOURNAL.md", "# GROWVINE\n\n## 2026-06-24 22:44 [fix] Dashboard card\n"
           "Owner: \"why does the Growvine dashboard card show minus 14 percent of the cap?\"\n")
    _server._index_refresh_internal()
    note = _reply("Te propongo que Growvine quede con su percent cap de hoy. ¿Le doy?")
    assert "minus 14" not in note, note








def test_reply_pending_needs_its_own_words_not_a_brand_or_a_first():
    """Live false positives 2026-10-29 ~06:00 UTC (Launch Desk session, real pending lines): "Primer post automático de
    @remotejobs.hoy" was called shipped by an Growvine X ship whose title ends in "Primer" (another brand, another
    network), and "Carpeta de posts y calendario para Launch Desk" by a Launch Desk ship of a hand post. Each match
    rode on one generic word ("primer", "post") or on the company name."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("SOCIALX/SOCIALX_TEST_JOURNAL.md", "# SOCIALX TEST\n\n"
           "## 2026-10-22 03:59 [ship] X DE GROWVINE EN MARCHA EN SOCIAL ENGINE (2026-10-22, \"dale\" de Owner). Primer\n\n"
           "X DE GROWVINE EN MARCHA EN SOCIAL ENGINE (2026-10-22, \"dale\" de Owner). Primer post hoy 20:48 UTC "
           "(17:48 Local).\n")
    _write("AI TEAM/APPUSER_VD_TEST_JOURNAL.md", "# APPUSER VD TEST\n\n"
           "## 2026-10-28 01:58 [ship] LAUNCH DESK: owner lifted the quiet day for posting; @remotejobs.hoy first p\n\n"
           "LAUNCH DESK: owner lifted the quiet day for posting; @remotejobs.hoy first post LIVE; @cvinterviews "
           "stuck at a selfie checkpoint.\n- @remotejobs.hoy: carousel posted with Webweave autopilot on Chrome 9327; "
           "verified on profile: 1 post. Launch Desk posts by hand until its calendar exists.\n")
    _server._index_refresh_internal()
    reply = ("- [x] ✅ **Publicar por navegador en vivo**: @remotejobs.hoy lista\n"
             "- [ ] 🔄 **Primer post automático de @remotejobs.hoy**: lo hace Launch Desk hoy; te paso el link\n"
             "- [ ] ⏳ **Carpeta de posts y calendario para Launch Desk**: para que sus posts queden programados y "
             "salgan solos")
    note = _reply(reply)
    assert "WRONG" not in note, note


def test_reply_platform_or_first_word_with_one_shared_word_is_not_a_ship():
    """Same class as the two real cases above, each rule on its own: a platform written CamelCase ("YouTube" counted as
    a sure name, one shared word was enough) and a capitalised first word ("Primer") are never the pending thing; a ship
    of another brand that shares the item's kind ("carrusel de frases") is not this item."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("CHANNELX/CHANNELX_TEST_JOURNAL.md", "# CHANNELX TEST\n\n"
           "## 2026-10-28 10:00 [ship] YouTube channel art LIVE\nNew channel art uploaded to YouTube: the covers of the "
           "3 packs.\n\n"
           "## 2026-10-27 10:00 [ship] Primer carrusel de frases de Growvine LIVE\nPrimer carrusel de frases (5 slides) "
           "posted on the Growvine account.\n")
    _server._index_refresh_internal()
    note = _reply("**Pending**\n- [ ] ⏳ Upload the 3 new covers to YouTube once the owner says yes.")
    assert "WRONG" not in note, note
    note = _reply("**Pendiente**\n- [ ] ⏳ **Primer carrusel de frases para Lunaria**: armarlo y programarlo")
    assert "WRONG" not in note, note


def test_test_fixture_journals_are_never_indexed():
    """2026-10-29: the real index held tests/fixtures/shapesmith_20261028 (a 10-28 snapshot of two real journals):
    52 stale entries fed every quick map and reply check."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("TOOLX/tests/fixtures/case_1/OLDCOPY_JOURNAL.md", "# OLD COPY\n\n## 2026-10-01 10:00 [ship] oldcopy LIVE\nx\n")
    _write("TOOLX/TOOLX_JOURNAL.md", "# TOOLX\n\n## 2026-10-01 10:00 [ship] toolx LIVE\nx\n")
    _server._index_refresh_internal()
    c = _server._conn()
    try:
        paths = [p for (p,) in c.execute("SELECT path FROM journals").fetchall()]
    finally:
        c.close()
    assert any(p.endswith("TOOLX_JOURNAL.md") for p in paths)
    assert not any("fixtures" in p for p in paths), [p for p in paths if "fixtures" in p]


def test_worktree_copies_and_vault_output_are_never_indexed():
    """2026-10-30: every search showed SHOPSITE_FULL_JOURNAL three times, from the site's throwaway git worktrees
    (shopsite-site-wt-audio, -wt-perf); the store vault build output copies the sold journals too."""
    os.environ["JOURNAL_HOME"], os.environ["JOURNAL_ROOTS"] = str(_TMP / "home"), str(_ROOT)
    _write("site/SITEX_JOURNAL.md", "# SITEX\n\n## 2026-10-01 10:00 [ship] sitex LIVE\nx\n")
    _write("site-wt-audio/SITEX_JOURNAL.md", "# SITEX copy\n\n## 2026-10-01 10:00 [ship] sitex LIVE\nx\n")
    _write("site/journals-vault/Library/SOLD_JOURNAL.md", "# SOLD copy\n")
    _server._index_refresh_internal()
    c = _server._conn()
    try:
        paths = [p.replace("\\", "/") for (p,) in c.execute("SELECT path FROM journals").fetchall()]
    finally:
        c.close()
    assert any(p.endswith("site/SITEX_JOURNAL.md") for p in paths)
    assert not any("-wt-" in p for p in paths)
    assert any("journals-vault" in p for p in paths)   # the starter vault buyers unzip is indexed


def test_a_file_a_website_serves_is_never_a_journal():
    """public/installs/journal.md (the journal tool's install guide) was indexed as the journal of a project
    "installs"; reading public/installs/connector.md then stopped 3 times (2026-10-29 03:12 [bug], 2026-10-30)."""
    from pathlib import Path as _P
    assert not _server._is_journal_path(_P("C:/x/site/public/installs/journal.md"))
    assert not _server._is_journal_path(_P("/home/a/site/public/docs/OPS_JOURNAL.md"))
    assert _server._is_journal_path(_P("C:/x/site/SITE_JOURNAL.md"))
