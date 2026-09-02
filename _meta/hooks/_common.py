"""Shared plumbing for hook entry points.

Hooks are deterministic mechanisms (P5), but they are guests in someone
else's session: they must never break it. Three rules hold everywhere here.

1. **Always exit 0.** On `UserPromptSubmit` a hook exiting 2 BLOCKS the
   prompt and erases what the user typed; any nonzero code raises a visible
   error notice. Memory failing is never worth costing someone their prompt,
   so every failure path is swallowed and reported as silence.
2. **Read the payload defensively.** Field names are version-dependent
   (`user_prompt` today, with `prompt` accepted as a fallback); a missing key
   means "no work to do", not a crash.
3. **Speak in the documented JSON form.** `hookSpecificOutput.additionalContext`
   is the supported way to add context; for `UserPromptSubmit` a top-level
   `additionalContext` is silently ignored.

Verified against Claude Code 2.1.240 docs (see integrations/claude-code/).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

# <vault>/_meta/hooks/_common.py  ->  <vault>
VAULT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VAULT_ROOT))


def read_payload() -> dict:
    """Hook input arrives as JSON on stdin. Anything unreadable is {}."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def emit_context(event_name: str, text: str) -> None:
    """Inject text into the session's context, or stay silent if empty."""
    if not text or not text.strip():
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text.strip(),
        }
    }
    sys.stdout.write(json.dumps(payload))


def capture_cli(argv: list[str]) -> str:
    """Run the memory CLI in-process, returning its stdout. Never raises."""
    buf = io.StringIO()
    try:
        from memory_mesh.cli import main

        with redirect_stdout(buf):
            main(["--root", str(VAULT_ROOT), *argv])
    except SystemExit:
        pass
    except Exception:
        return ""  # memory problems stay memory's problem
    return buf.getvalue()


def run(event_name: str, argv: list[str], inject: bool = True) -> None:
    """Standard hook body: run the CLI, optionally inject its output, exit 0."""
    try:
        out = capture_cli(argv)
        if inject:
            emit_context(event_name, out)
    except Exception:
        pass
    finally:
        sys.exit(0)
