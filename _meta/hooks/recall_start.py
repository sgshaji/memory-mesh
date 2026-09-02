#!/usr/bin/env python3
"""SessionStart hook: print the domain router and the project note matching
the working directory. Stdout becomes session context."""

import sys

from _common import read_payload, run_cli

payload = read_payload()
session = str(payload.get("session_id") or "default")
cwd = str(payload.get("cwd") or "")
argv = ["session-start", "--tool", "claude-code", "--session", session]
if cwd:
    argv += ["--cwd", cwd]
sys.exit(run_cli(argv))
