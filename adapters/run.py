"""Entry point for the app adapters: reads the app's hook JSON on stdin, runs the core, prints the app's answer.

  python quick_hook.py --app codex|copilot|cursor [--event <event name>]
  python adapters/run.py --app codex|copilot|cursor [--event <event name>]

--event is needed only when the payload does not name its event (Copilot camelCase hooks). Always exits 0: a crash
here prints the app's "nothing to say" answer, never a block (Copilot denies on a non-zero exit, Cursor on bad JSON).
"""
import importlib
import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
APPS = ("codex", "copilot", "cursor")


def _arg(argv: list, name: str) -> str:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""


def read_stdin() -> str:
    data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def load(app: str):
    if str(CORE_DIR) not in sys.path:
        sys.path.insert(0, str(CORE_DIR))
    if app not in APPS:
        raise ValueError(f"unknown app {app!r}, expected one of {', '.join(APPS)}")
    return importlib.import_module(f"adapters.{app}").ADAPTER


def main(argv=None, stdin_text=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app, event = _arg(argv, "--app").lower(), _arg(argv, "--event")
    adapter, out = None, None
    try:
        adapter = load(app)
        raw = read_stdin() if stdin_text is None else stdin_text
        payload = json.loads(raw) if raw.strip() else {}
        out = adapter.handle(payload if isinstance(payload, dict) else {}, event)
    except Exception:
        try:
            from adapters.base import log_error
            log_error(app or "?")
        except Exception:
            pass
    text = adapter.render(out) if adapter else "{}"
    try:
        if text:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
