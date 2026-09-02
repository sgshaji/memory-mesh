#!/usr/bin/env python3
"""PreCompact hook: append a checkpoint (time + last user prompt) so long
sessions lose nothing when context is compacted. Before the stub exists the
checkpoint parks in disposable session state; session-end folds it in."""

import sys

from _common import read_payload, run_cli

payload = read_payload()
session = str(payload.get("session_id") or "default")
last_prompt = str(payload.get("prompt") or payload.get("last_user_prompt") or "context compacted")
sys.exit(run_cli(["episode", "checkpoint", "--session", session, "--text", last_prompt[:300]]))
