#!/usr/bin/env python3
"""SessionEnd hook: create the episode stub with frontmatter, status: raw,
the session's retrieved notes under *Knowledge retrieved*, and session_ref.
A session that retrieved nothing writes no episode (episode.md)."""

import sys

from _common import read_payload, run_cli

payload = read_payload()
session = str(payload.get("session_id") or "default")
transcript = str(payload.get("transcript_path") or session)
sys.exit(run_cli([
    "session-end",
    "--tool", "claude-code",
    "--session", session,
    "--session-ref", transcript,
    "--slug", "session",
]))
