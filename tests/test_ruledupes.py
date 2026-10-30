"""Already-said check (ruledupes.py). Real case 2026-10-28: a new owner rule line duplicated the 2026-10-25 one."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ruledupes  # noqa: E402

RULES = [
    "- 2026-10-25: All employees of all companies use Shopsite tools as much as possible (they are the first dogfood "
    "users, the same kind of user whose agents will use our tools); Shopsite monitors that use system-wide (what failed, "
    "what was done outside a tool and why) and turns it into better tools and into sales proof and copy.",
    "- 2026-10-26: When a product is tested as a user before launch (dogfood runs), RECORD the whole process on screen "
    "as it happens, so parts can be cut into demos, ads and promo content (owner, on preparing Dreamfield demos)",
    "- 2026-10-24: Every automated action on any platform must emulate a real person so we are never detected: human "
    "pacing, reading and scrolling before acting, typing at human speed, few actions, varied days.",
]
DUP = ("- 2026-10-28: Every company splits its effort in two: one part on traffic and sales (content, demos, warming, "
       "cold outreach), the other ALWAYS on developing our tools: watch how the company's own employees use the Shopsite "
       "tools, where they fail or work around them, and improve the tools all the time. Directors own this split")
NEW = ("- 2026-10-28: Music for product demo reels and ads is High Tide beats (batch 1 and 2), never drum and bass; "
       "they read more pro for ads and content (Shopsite demo reels).")


def bash(lines):
    body = "\n".join(f'"{l}",' for l in lines)
    return {"tool_name": "Bash", "tool_input": {"command": "python - <<'EOF'\nimport pathlib\np=pathlib.Path(\"OWNER_SAID_JOURNAL.md\")\n"
                                                            f"lines=[\n{body}\n]\nEOF"}}


def test_the_real_duplicate_is_stopped_once_and_shows_the_old_rule():
    seen = {}
    r = ruledupes.check(bash([DUP]), seen, RULES)
    assert r and "ALREADY THERE: - 2026-10-25: All employees" in r["deny"]
    assert ruledupes.check(bash([DUP]), seen, RULES) is None


def test_a_really_new_rule_passes():
    assert ruledupes.check(bash([NEW]), {}, RULES) is None


def test_writes_elsewhere_are_not_checked():
    c = {"tool_name": "Bash", "tool_input": {"command": f"echo '{DUP}' >> NOTES.md"}}
    assert ruledupes.check(c, {}, RULES) is None


def test_edit_of_the_rules_file_checks_only_added_lines():
    c = {"tool_name": "Edit", "tool_input": {"file_path": "C:/x/OWNER_SAID_JOURNAL.md", "old_string": DUP,
                                             "new_string": DUP + " (repeated 2026-10-28)"}}
    assert ruledupes.check(c, {}, RULES) is None
