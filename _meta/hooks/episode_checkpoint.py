#!/usr/bin/env python3
"""PreCompact: park a checkpoint so a long session loses nothing when its
context is compacted. Injects nothing back into the session — it only
records. The parked text is redacted before it touches disk."""

from _common import read_payload, run

payload = read_payload()
session = str(payload.get("session_id") or "default")
last = str(payload.get("user_prompt") or payload.get("prompt") or "context compacted")

run(
    "PreCompact",
    ["episode", "checkpoint", "--session", session, "--text", last[:300]],
    inject=False,
)
