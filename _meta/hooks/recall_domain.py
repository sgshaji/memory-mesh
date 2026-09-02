#!/usr/bin/env python3
"""UserPromptSubmit hook: on the FIRST prompt of a session, match the domain
router and print the matched index plus linked notes (bounded recall). Later
prompts are a silent no-op — automatic memory acts at most three times per
session (session-lifecycle.md)."""

import sys

from _common import read_payload, run_cli

payload = read_payload()
session = str(payload.get("session_id") or "default")
prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
if not prompt.strip():
    sys.exit(0)
sys.exit(run_cli(["session-prompt", prompt, "--tool", "claude-code", "--session", session]))
