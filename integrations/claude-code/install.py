#!/usr/bin/env python3
"""Install (or remove) the Memory Mesh hooks in Claude Code user settings.

Merges into `~/.claude/settings.json`, never overwrites it: existing keys are
preserved, a timestamped backup is written, and `--uninstall` removes only the
Memory Mesh entries.

Verified against Claude Code 2.1.240:
  - exec form (`command` + `args`) avoids shell quoting on Windows paths that
    contain spaces — this vault lives under "OneDrive - Microsoft";
  - SessionStart/PreCompact take a matcher; SessionEnd needs an explicit
    timeout because its default budget is ~1.5s shared across hooks;
  - UserPromptSubmit has a 30s timeout and MUST NOT exit nonzero (exit 2
    blocks the prompt and erases the user's input) — the scripts always exit 0.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
HOOKS = VAULT / "_meta" / "hooks"
SETTINGS = Path.home() / ".claude" / "settings.json"
MARKER = "memory-mesh"  # identifies our entries for clean uninstall


def _entry(script: str, event: str, matcher: str | None, timeout: int | None) -> dict:
    hook: dict = {
        "type": "command",
        "command": sys.executable,
        "args": [str(HOOKS / script)],
        # not read by Claude Code; used by --uninstall to find our entries
        "_source": MARKER,
    }
    if timeout is not None:
        hook["timeout"] = timeout
    block: dict = {"hooks": [hook]}
    if matcher:
        block["matcher"] = matcher
    return block


def desired_hooks() -> dict:
    return {
        # startup|resume|clear: inject the router. Deliberately not `compact`,
        # which is a mid-session context rebuild, not a new session.
        "SessionStart": [_entry("recall_start.py", "SessionStart", "startup|resume|clear", 20)],
        # first prompt only; the script self-limits and stays silent after
        "UserPromptSubmit": [_entry("recall_domain.py", "UserPromptSubmit", None, 20)],
        "PreCompact": [_entry("episode_checkpoint.py", "PreCompact", "manual|auto", 15)],
        # raise past the ~1.5s SessionEnd budget; the script takes ~0.2s
        "SessionEnd": [_entry("episode_stub.py", "SessionEnd", None, 15)],
    }


def _is_ours(block: dict) -> bool:
    return any(h.get("_source") == MARKER for h in block.get("hooks", []))


def load_settings() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"refusing to touch malformed settings: {SETTINGS}: {e}")


def backup() -> Path | None:
    if not SETTINGS.exists():
        return None
    dest = SETTINGS.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(SETTINGS, dest)
    return dest


def write(settings: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def install() -> None:
    settings = load_settings()
    hooks = settings.setdefault("hooks", {})
    for event, blocks in desired_hooks().items():
        existing = [b for b in hooks.get(event, []) if not _is_ours(b)]
        hooks[event] = existing + blocks  # other people's hooks survive
    b = backup()
    write(settings)
    print(f"installed Memory Mesh hooks into {SETTINGS}")
    if b:
        print(f"backup: {b}")
    print("restart Claude Code (or start a new session) to load them")


def uninstall() -> None:
    settings = load_settings()
    hooks = settings.get("hooks", {})
    removed = 0
    for event in list(hooks):
        kept = [b for b in hooks[event] if not _is_ours(b)]
        removed += len(hooks[event]) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    b = backup()
    write(settings)
    print(f"removed {removed} Memory Mesh hook entr{'y' if removed == 1 else 'ies'} from {SETTINGS}")
    if b:
        print(f"backup: {b}")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
