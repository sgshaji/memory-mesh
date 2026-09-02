#!/usr/bin/env python3
"""UserPromptSubmit: on the FIRST prompt of a session, match the domain router
and inject the matched index plus its linked notes. Every later prompt is a
silent no-op — memory acts at most three times per session, never per message.

This hook must never fail loudly: a nonzero exit here would block the user's
prompt and erase what they typed.
"""

from _common import read_payload, run

payload = read_payload()
session = str(payload.get("session_id") or "default")
# `user_prompt` is the documented field; `prompt` kept as a fallback
prompt = str(payload.get("user_prompt") or payload.get("prompt") or payload.get("raw_user_input") or "")

if not prompt.strip():
    raise SystemExit(0)

run("UserPromptSubmit", ["session-prompt", prompt, "--tool", "claude-code", "--session", session])
