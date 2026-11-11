"""Logs never keep secrets (2026-11-11: action_check_log.jsonl held 55 commands with keys in plain text, one an
unquoted NAME_API_KEY=value the secret rules did not cover)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from default_rules import redact  # noqa: E402

A = "sk-" + "ant-" + "abcdefghijklmnopqrstuvwxyz0123"
L = "sk_" + "live_" + "abcdefghijklmnopqrstuvwx"
G = "gh" + "p_" + "a" * 36


def test_secrets_are_hidden():
    cases = {
        "printf 'VOYAGE_API_KEY=pa-FAKEFAKEFAKEFAKE1234567890' > x.env": "pa-FAKE",
        "curl -H 'Authorization: Bearer abcdefghijklmnop123' https://api.x.com": "abcdefghijklmnop123",
        f"git push https://user:{G}@github.com/x/y": G[:8],
        f"export STRIPE_SECRET_KEY={L}": L[:10],
        f"python -c \"api_key='{A}'\"": A[:10],
    }
    for cmd, secret in cases.items():
        assert secret not in redact(cmd), cmd


def test_normal_commands_are_untouched():
    for cmd in ["npm run build", "git status --short", "export TOKEN=$GITHUB_TOKEN", "ls ~/.ssh",
                "grep -c '^CRON_SECRET=' .env.local", "MAX_TOKENS=4096 node x.js", "rm -rf node_modules"]:
        assert redact(cmd) == cmd


def test_command_log_line_is_redacted(tmp_path, monkeypatch):
    import actioncheck
    monkeypatch.setattr(actioncheck, "LOG", tmp_path / "log.jsonl")
    line = {"cmd": actioncheck._redact(f"export OPENAI_API_KEY={A}")[:300]}
    (tmp_path / "log.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert A not in (tmp_path / "log.jsonl").read_text(encoding="utf-8")


def test_mod_event_is_redacted(tmp_path, monkeypatch):
    import quick_hook
    monkeypatch.setattr(quick_hook, "_home", lambda: str(tmp_path))
    quick_hook.event("stop", cmd=f"export STRIPE_SECRET_KEY={L}")
    text = (tmp_path / "mod_events.jsonl").read_text(encoding="utf-8")
    assert L not in text and "<redacted>" in text
