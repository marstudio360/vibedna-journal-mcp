"""Tools map (toolmap.py): before an action, the tools that already do it, matched by concept; a call that builds
or runs its own way of doing a tool's job is stopped once.

Regression for 2026-10-26: a session posted an Instagram carousel on a new account with a loose Playwright script
(vd_post.py: connect_over_cdp, "New post", set_input_files, Share) run on a server, while the posting MCP (Social
Brain: Instagram posts, carousels, reels through the official API) sat unused. The journals map matched journal
words ("drip", "schedule") the action never used, and "Already exists" cards never stopped anything.
The real calls are in tests/fixtures/ig_carousel_incident.json (4 shell calls and the Write of vd_post.py).

Run: python -m pytest tests  (temp JOURNAL_HOME, temp tool docs; never the real journals)
"""
from __future__ import annotations

import json

import pytest
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import quick_hook  # noqa: E402
import toolmap  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="journal-toolmap-test-"))
_HOME = _TMP / "home"
_DOCS = _TMP / "docs"
_SCRATCH = _TMP / "scratch"
_REAL_SCRATCH = ("C:/Users/ANNLEE~1/AppData/Local/Temp/claude/c--Users-Ann-Lee-Desktop-DEV-PROJECTS/"
                 "e318fb3c-427f-4847-b2ee-52a783dd2701/scratchpad")


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


_w(_DOCS / "social-engine_JUICE.md", """# SOCIAL ENGINE MCP, the juice

Distilled from server.py.

## 1. One-liner

Your social media manager is now a chat message. Post, schedule, grow, and reply across Instagram, Facebook,
Threads, X, and YouTube by telling the AI what you want.

## 2. The wows

1. Post to 5 platforms from one sentence. `publish_multi` fires IG post/Reel/Story/carousel, Facebook, Threads, X.
2. Run a real posting calendar that fires on its own: `drip_schedule` slots, a runner posts them.
3. Reels never ship with a black cover: `publish_instagram_reel(video_url, cover_url)`.
""")
_w(_DOCS / "webweave_JUICE.md", """# WEBWEAVE MCP, the juice

## 1. One-liner

Webweave lets your AI drive a real logged-in browser: post, upload, fill forms on any website, no Playwright script
of your own, sessions saved per site.
""")
_w(_DOCS / "content-studio_JUICE.md", """# CONTENT STUDIO MCP, the juice

## 1. One-liner

Content Studio makes your posts: it can generate, render and design images, videos and reels, extract frames and
scrape references, ready for social media.
""")
_w(_DOCS / "MCP_REGISTRY.md", """# MCP Registry

### `social-engine-dna` \u2014 Multi-platform social posting brain
```json
"social-engine": {"type": "stdio"}
```

### `mailer-dna` \u2014 Mailer: send email and newsletters through the email API
```json
"mailer": {"type": "stdio"}
```

### `ledger-dna` \u2014 Ledger: payment, refund and checkout links
```json
"ledger": {"type": "stdio"}
```
""")
_w(_DOCS / "skills" / "brand-voice" / "SKILL.md", "---\nname: brand-voice\ndescription: Rewrite copy in the brand "
   "voice. Triggers on: rewrite this, tone.\n---\n\n# Brand voice\n")

_CARDS = {
    str(_TMP / "SOCIAL_SYSTEM_JOURNAL_USER.md"): {"m": 1.0, "n": "SOCIAL_SYSTEM_JOURNAL_USER.md", "c": [
        {"k": "exists", "what": "Publish to Instagram now through the official API: single image post, carousel (2 to 10 "
         "images), reel, story; any brand account, no browser script",
         "how": "Social Engine MCP (social-engine): publish_instagram_carousel(image_urls, caption, account), "
                "publish_instagram_reel(video_url, caption, account)",
         "status": "working; needs an Instagram Professional account linked to a Facebook Page and Meta credentials",
         "keys": "instagram, ig, carousel, reel, post, publish, publicar, postear, subir"},
        {"k": "exists", "what": "Scheduled posts across channels (drips)", "how": "Social Engine drip_schedule + drip_runner.py",
         "status": "working", "keys": "drip, programar, schedule, publicar, posts"},
        {"k": "decided", "what": "All brands run ONLY the Social Engine product", "how": "", "status": "", "keys": ""}]},
    str(_TMP / "FORECAST_MARKETS_JOURNAL.md"): {"m": 1.0, "n": "FORECAST_MARKETS_JOURNAL.md", "c": [
        {"k": "exists", "what": "Real bot fills and payouts report", "how": "fills_report.py on the box", "status": "working",
         "keys": "fills, payouts, pnl"}]},
}


_PREV_HOME = os.environ.get("JOURNAL_HOME")


def setup_module(_m=None):
    os.environ["JOURNAL_HOME"] = str(_HOME)
    os.environ["JOURNAL_TOOL_DOCS"] = ";".join([str(_DOCS / "*_JUICE.md"), str(_DOCS / "MCP_REGISTRY.md"),
                                                str(_DOCS / "skills" / "*" / "SKILL.md")])
    _w(_HOME / "quick_cards.json", json.dumps(_CARDS))
    # The incident's local files, where its commands expect them.
    calls = _calls()
    write = next(c for c in calls if c["tool_name"] == "Write")
    _w(_SCRATCH / "vd" / "post1" / "vd_post.py", write["tool_input"]["content"])
    _w(_SCRATCH / "vd" / "post1" / "caption.txt", "5 respuestas que te sacan de la entrevista.\n#entrevista #cv\n")
    _w(_SCRATCH / "vd" / "run_post.sh", "D=/data/appuser-out/launch-desk/ig-post1\nsudo -u deploy tmux new-session "
       "-d -s vdpost1 \"cd $D && $PY vd_post.py > post.log 2>&1\"\n")
    _w(_SCRATCH / "vd" / "build_carousel.py", "from PIL import Image\n# 7 carousel slides 1080x1350 for the Instagram post\n")


def teardown_module(_m=None):
    os.environ.pop("JOURNAL_TOOL_DOCS", None)
    if _PREV_HOME is not None:
        os.environ["JOURNAL_HOME"] = _PREV_HOME


def _calls() -> list[dict]:
    raw = (HERE / "fixtures" / "ig_carousel_incident.json").read_text(encoding="utf-8")
    raw = raw.replace(_REAL_SCRATCH, str(_SCRATCH).replace("\\", "/"))
    return json.loads(raw)


def _sid() -> str:
    return "tm-test-%d" % time.perf_counter_ns()


def _call(c: dict, sid: str) -> dict:
    ti = dict(c["tool_input"])
    if "content" in ti:
        ti["content"] = ti["content"][:4000]   # what the mod passes
    return {"tool_name": c["tool_name"], "tool_input": ti, "session_id": sid, "cwd": str(_TMP)}


def _desc(c: dict) -> str:
    return c["tool_input"].get("description") or Path(c["tool_input"].get("file_path", "")).name


def test_every_incident_call_alone_surfaces_social_engine():
    # Alone, "Send self-contained post job to box" names no object (no Instagram, carousel or browser signal): a
    # weak match on its own words is noise since 2026-10-26, so it surfaces only in the session sequence (next test).
    for c in _calls():
        r = quick_hook._tools_first(_call(c, _sid()))
        if _desc(c) in ("Send self-contained post job to box", "Find Playwright python on box and launch post"):
            continue
        assert r, _desc(c)
        text = r.get("deny") or r.get("note")
        assert text.startswith("TOOLS THAT ALREADY DO THIS"), _desc(c)
        first = text.split("\n")[1]
        assert first.startswith("1. Social Engine (MCP social-engine)"), (_desc(c), first)
        assert "publish_instagram_carousel" in text, _desc(c)
        assert "SOCIAL_SYSTEM_JOURNAL_USER.md" in text, _desc(c)


@pytest.mark.skipif(sys.platform != "win32", reason="the recorded incident carries Windows paths")
def test_incident_in_order_stops_once_each_call_that_posts():
    sid = _sid()
    got = {}
    for c in _calls():
        call = _call(c, sid)
        first, retry = quick_hook._tools_first(call), quick_hook._tools_first(call)
        got[_desc(c)] = ("deny" if first and first.get("deny") else "note" if first else "-", retry)
    # Building the slides is content work: shown, never stopped. Writing the poster and every run of it: stopped once.
    assert got["Build carousel slides and contact sheet"][0] == "note"
    for d in ("vd_post.py", "Upload carousel and launch post job on box", "Send self-contained post job to box",
              "Find Playwright python on box and launch post"):
        assert got[d][0] == "deny", (d, got[d])
        assert got[d][1] is None, d   # the same intent passes on retry


def test_deny_merges_with_the_journal_map_and_says_how_to_pass():
    out = quick_hook._merge(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                               "additionalContext": "JOURNAL QUICK MAP for x"}}),
                            {"deny": "TOOLS THAT ALREADY DO THIS: ..."})
    h = json.loads(out)["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny"
    assert h["permissionDecisionReason"].startswith("TOOLS THAT ALREADY DO THIS")
    assert "JOURNAL QUICK MAP" in h["permissionDecisionReason"] and "passes on retry" in h["permissionDecisionReason"]
    note = json.loads(quick_hook._merge("", {"note": "TOOLS THAT ALREADY DO THIS: n"}))["hookSpecificOutput"]
    assert note["additionalContext"].startswith("TOOLS THAT ALREADY DO THIS") and "permissionDecision" not in note


def test_reading_or_searching_never_stops():
    sid = _sid()
    for call in ({"tool_name": "Read", "tool_input": {"file_path": str(_SCRATCH / "vd" / "post1" / "vd_post.py")}},
                 {"tool_name": "Grep", "tool_input": {"pattern": "instagram carousel publish"}},
                 {"tool_name": "Bash", "tool_input": {"command": f'cat "{_SCRATCH}/vd/post1/vd_post.py" | grep -n instagram',
                                                      "description": "Read the Instagram post script"}}):
        assert quick_hook._tools_first(dict(call, session_id=sid, cwd=str(_TMP))) is None, call["tool_name"]


def test_oddsboard_command_never_stops():
    call = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": "ssh gpubox 'tail -50 /opt/oddsboard-bot/data/bulkbot_real.log'",
        "description": "Find real bot fills and payouts on 25/10"}}
    r = quick_hook._tools_first(call)
    assert not (r and r.get("deny"))


def test_chat_only_prompt_is_not_checked():
    assert quick_hook._tools_first({"prompt": "hola, como va todo? publicamos el carrusel de instagram?",
                                    "session_id": _sid()}) is None


def test_editing_or_naming_the_tool_itself_never_stops():
    sid = _sid()
    own = {"tool_name": "Edit", "session_id": sid, "cwd": str(_TMP), "tool_input": {
        "file_path": "C:/code/TOOL SHOP/servers/social-engine-mcp/server.py",
        "new_string": "def publish_instagram_carousel(image_urls, caption):\n    # instagram carousel publish\n"}}
    r = quick_hook._tools_first(own)
    assert not r or "Social Engine" not in (r.get("deny") or r.get("note"))
    agent = {"tool_name": "Agent", "session_id": sid, "cwd": str(_TMP), "tool_input": {
        "description": "Post the carousel with Social Engine",
        "prompt": "Use the social-engine MCP: publish_instagram_carousel with the 7 slides to the new Instagram account."}}
    r = quick_hook._tools_first(agent)
    assert not (r and r.get("deny"))


def test_a_test_harness_that_mentions_the_topic_is_not_stopped():
    _w(_SCRATCH / "replay.py", "# replays the instagram carousel publish calls (vd_post.py, Playwright, New post)\n")
    call = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": f'python "{_SCRATCH}/replay.py"', "description": "Replay the incident calls through the hook"}}
    r = quick_hook._tools_first(call)
    assert not (r and r.get("deny"))


def test_deploying_the_tool_itself_with_embedded_files_never_stops():
    # Real false positive 2026-10-26 (main session): "Deploy journals mod 0.6.0 to the box" was stopped with Social
    # Brain: the command named tests/fixtures/ig_carousel_incident.json and carried the files as base64, and the
    # tool folder was a quoted path with spaces ("DEV PROJECTS/TOOL SHOP/..."), so it was not seen as the tool.
    tool = _TMP / "TOOL SHOP" / "servers" / "journal-mcp"
    (tool / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    _w(tool / "server.py", "# journal tool\n")
    _w(tool / "INSTALL.md", "install\n")
    _w(tool / "tests" / "fixtures" / "ig_carousel_incident.json", '{"desc": "Upload carousel and launch post job"}\n')
    blob = "\n".join(["QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODk="] * 6)
    posix = "/" + str(tool).replace("\\", "/").replace(":", "", 1)
    cmd = (f'J="{posix}"; {{ echo \'base64 -d <<"B64" | tar xzf -\'; tar czf - -C "$J" toolmap.py '
           f'tests/fixtures/ig_carousel_incident.json | base64; echo B64; }} > /tmp/deploy.sh\n{blob}\n'
           'ssh gpubox bash -s < /tmp/deploy.sh')
    call = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": cmd, "description": "Deploy journals mod 0.6.0 to the box"}}
    r = quick_hook._tools_first(call)
    assert not (r and r.get("deny")), r
    assert "QUJDREVG" not in toolmap.strip_payloads(blob)


def test_read_only_server_probe_never_stops():
    # Real false positive 2026-10-26 (main session): "Read VD Chrome env and proxy unit on box", an ssh bash -s of a
    # local script that only runs cat/sed/systemctl cat/ss/ls, was stopped with Bidbot and Social Engine.
    probe = _SCRATCH / "probe4.sh"
    _w(probe, "D=/home/deploy/product-warmer/deploy\n"
              "sudo sed -E 's/(PASS|PASSWORD|TOKEN)[A-Z_]*=.*/\\1=<hidden>/I' $D/launch-desk.env\n"
              "echo \"== proxy unit\"; systemctl cat pw-proxy@launch-desk | sed -n '1,30p'\n"
              "echo \"== ports\"; ss -ltnp 2>/dev/null | grep -E ':(93[0-9][0-9])' | awk '{print $4}' | sort\n"
              "ls $D/*.env | head -20\n")
    call = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": f'S="{_SCRATCH}"; ssh gpubox bash -s < "$S/probe4.sh"',
        "description": "Read VD Chrome env and proxy unit on box"}}
    assert toolmap.action_parts(call)[4] is False
    assert not (quick_hook._tools_first(call) or {}).get("deny")
    inline = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": "ssh gpubox \"cat /data/x/status.json; tail -5 /data/x/post.log; ls /data/x/*.png\"",
        "description": "Check post job progress on box"}}
    assert toolmap.action_parts(inline)[4] is False
    _w(_SCRATCH / "act.sh", "sudo systemctl restart pw-chrome-screen@vd2\npython3 /tmp/post.py\n")
    act = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": f'ssh gpubox bash -s < "{_SCRATCH}/act.sh"', "description": "Restart and post"}}
    assert toolmap.action_parts(act)[4] is True
    # the same probe written and sent in one command (the real form of the false positive)
    written = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": 'S="C:/tmp/vd"; cat > "$S/probe9.sh" <<\'EOF\'\nD=/home/a/deploy\n'
                   "sudo sed -E 's/(PASS|TOKEN)=.*/\\1=x/I' $D/vd.env\nsystemctl cat pw-proxy@vd | sed -n '1,30p'\n"
                   "ss -ltn | awk '{print $4}' | grep -E ':93' | sort\nEOF\nssh gpubox bash -s < \"$S/probe9.sh\"",
        "description": "Read VD Chrome env and proxy unit on box"}}
    assert toolmap.action_parts(written)[4] is False
    acting = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": 'cat > /tmp/a.sh <<\'EOF\'\nsudo systemctl enable --now pw-chrome-screen@vd2\nEOF\n'
                   'ssh gpubox bash -s < /tmp/a.sh', "description": "Start the second Chrome"}}
    assert toolmap.action_parts(acting)[4] is True
    assert toolmap.readonly_script("cat a; sed -i s/x/y/ f") is False
    assert toolmap.readonly_script("echo hi > /etc/x") is False
    assert toolmap.readonly_script("curl -s -X POST https://x") is False


def test_writing_rule_prose_into_a_journal_never_stops():
    # Real false positive 2026-10-26 (main session): an inline python heredoc that only inserts two rule lines into
    # OWNER_SAID_JOURNAL.md, rule text about Instagram, Social Engine, posting, viral accounts, was stopped with Webweave.
    cmd = ('python - <<\'EOF\'\np = "C:/x/AI TEAM/OWNER_SAID_JOURNAL.md"\ns = open(p, encoding="utf-8").read()\n'
           's = s.replace("## Rules\\n", "## Rules\\n- Map rule: the mod shows the tools first.\\n- Viral farm rule: '
           'Launch Desk opens Instagram and TikTok accounts for viral posts, carousels and reels; posting goes through '
           'Social Engine, never a loose Playwright script; upload and share only through the tool.\\n")\n'
           'open(p, "w", encoding="utf-8").write(s)\nEOF')
    call = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": cmd, "description": "Re-add map rule and add viral farm rule"}}
    r = quick_hook._tools_first(call)
    assert not (r and r.get("deny")), r
    assert toolmap.action_parts(call)[4] is False   # prose into markdown: never a build, whatever words it holds
    commit = {"tool_name": "Bash", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "command": "git add toolmap.py && git commit -q -F - <<'EOF'\ntools map: stop a loose Playwright script that "
                   "posts an Instagram carousel (New post, set_input_files, Share)\nEOF",
        "description": "Commit the tools map"}}
    assert toolmap.action_parts(commit)[4] is False and not (quick_hook._tools_first(commit) or {}).get("deny")
    for fp in ("C:/x/manuals/POSTING_MANUAL.md", "C:/x/SOCIAL_SYSTEM_JOURNAL_USER.md", "C:/x/notes/plan.txt"):
        w = {"tool_name": "Write", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
            "file_path": fp, "content": "Publish the Instagram carousel with Playwright: New post, set_input_files, Share."}}
        assert quick_hook._tools_first(w) is None, fp




def _run(c: dict, sid: str) -> dict:
    return {"tool_name": c["tool_name"], "tool_input": dict(c["tool_input"]), "session_id": sid, "cwd": str(_TMP)}


def _after_instagram_work(sid: str):
    """The session had just worked on Instagram (the Mapleworks session had: its Instagram map), so the last
    actions carry Instagram and carousel as context, the worst case for a later website ship."""
    quick_hook._tools_first({"tool_name": "Bash", "session_id": sid, "cwd": str(_TMP), "tool_input": {
        "command": f'python "{_SCRATCH}/vd/build_carousel.py"', "description": "Build Instagram carousel slides"}})










def test_file_names_and_extensions_are_never_words_or_projects():
    assert "publish" not in toolmap.concepts_of("bash /opt/appuser-ship/site_publish.sh && bash -n pub.sh")
    assert "instagram" not in toolmap.concepts_of("tar czf - tests/fixtures/ig_carousel_incident.json")
    assert "instagram" in toolmap.concepts_of("", "page.goto('https://www.instagram.com/')")   # code signals still count
    # an .astro file is a file of an Astro website, not the ASTRO project
    assert not quick_hook._key_hit(["astro"], "/c/site/src/pages/index.astro")
    assert not quick_hook._key_hit(["astro"], "src/components/*.astro")
    assert quick_hook._key_hit(["astro"], "/c/dev projects/astro/build.py")
    assert quick_hook._key_hit(["quickmap.py"], "/x/journal-mcp/quickmap.py")
    import quickmap
    assert "astro" not in quickmap._quick_terms(".astro") and "astro" not in quickmap._quick_terms("src/x.astro")








@pytest.mark.skipif(sys.platform != "win32", reason="the recorded incident carries Windows paths")
def test_the_instagram_incident_still_stops_after_the_false_positive_fixes():
    sid = _sid()
    denied = [_desc(c) for c in _calls() if (quick_hook._tools_first(_call(c, sid)) or {}).get("deny")]
    assert denied == ["vd_post.py", "Upload carousel and launch post job on box", "Send self-contained post job to box",
                      "Find Playwright python on box and launch post"], denied


def test_general_not_social_only_email_script_surfaces_the_mail_tool():
    call = {"tool_name": "Write", "session_id": _sid(), "cwd": str(_TMP), "tool_input": {
        "file_path": str(_SCRATCH / "send_news.py"),
        "content": "import smtplib\nwith smtplib.SMTP('smtp.example.com') as s:\n    s.sendmail(FROM, TO, newsletter)\n"}}
    r = quick_hook._tools_first(call)
    assert r and "mailer" in (r.get("deny") or r.get("note"))


def test_concepts_are_data_and_extend_from_journal_home():
    _w(_HOME / "tool_concepts.json", json.dumps({"concepts": {"instagram": {"words": ["grammy"]}}}))
    try:
        assert "instagram" in toolmap.concepts_of("post the grammy carousel")
    finally:
        (_HOME / "tool_concepts.json").unlink()
    assert "instagram" not in toolmap.concepts_of("the grammy awards")


def test_tools_check_is_fast_with_a_warm_index():
    toolmap.tool_index()
    c = next(c for c in _calls() if c["tool_name"] == "Write")
    t0 = time.perf_counter()
    for _ in range(5):
        toolmap.check(_call(c, _sid()), {})
    assert (time.perf_counter() - t0) / 5 < 0.25








