#!/usr/bin/env python3
"""SessionEnd: write the episode stub with *Knowledge retrieved* pre-filled
from this session's telemetry, then delete the session scratch.

A session that retrieved nothing writes no episode (episode.md). SessionEnd
hooks share a tight time budget, so this does filesystem work only — no
summarisation, which is `/episode`'s job while the context is still warm.
"""

from _common import read_payload, run

payload = read_payload()
session = str(payload.get("session_id") or "default")
transcript = str(payload.get("transcript_path") or session)

run(
    "SessionEnd",
    [
        "session-end",
        "--tool", "claude-code",
        "--session", session,
        "--session-ref", transcript,
        "--slug", "session",
    ],
    inject=False,
)
