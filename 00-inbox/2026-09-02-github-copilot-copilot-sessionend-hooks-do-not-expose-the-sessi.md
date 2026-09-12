---
type: candidate
title: Copilot sessionEnd hooks do not expose the session transcript
source: "automatic capture via github-copilot, 2026-09-02"
captured: "2026-09-02T21:42:03+05:30"
domains: [coding-agents]
trust: mixed
sensitivity: checked
content_hash: 4cb851fb24dc0c1a
project: memory-mesh
---

## Observations
- [behaviour] The GitHub Copilot CLI sessionEnd payload contains session identity, time, working directory, and reason, but no conversation transcript.
- [procedure] Capture reusable findings through the active coding agent while session context is still available instead of attempting transcript extraction in the sessionEnd command hook.
- [evidence] Verified against the GitHub Copilot hooks reference while implementing automatic candidate capture.
