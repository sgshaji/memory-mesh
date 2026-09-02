"""Shared plumbing for hook entry points.

Hooks are deterministic mechanisms (P5): they read a JSON payload from stdin
DEFENSIVELY (missing keys tolerated — issues.md I-014), locate the vault
relative to this file, and call the `memory` CLI in-process. They never
summarise, never touch knowledge/, and never make network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VAULT_ROOT))


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def run_cli(argv: list[str]) -> int:
    from memory_mesh.cli import main

    return main(["--root", str(VAULT_ROOT), *argv])
