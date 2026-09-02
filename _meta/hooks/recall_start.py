#!/usr/bin/env python3
"""SessionStart: inject the domain router and the project note matching the
working directory. This is operation 1 of the 3 automatic memory operations
a session is allowed."""

from _common import VAULT_ROOT, read_payload, run

payload = read_payload()
session = str(payload.get("session_id") or "default")
cwd = str(payload.get("cwd") or "")

argv = ["session-start", "--tool", "claude-code", "--session", session]
if cwd:
    argv += ["--cwd", cwd]

run("SessionStart", argv)
