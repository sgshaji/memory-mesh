---
type: candidate
title: Centralize connector skill contracts in pure helper functions
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T11:49:14+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 544e6c648e14c521
project: pd-ad-conversion
---

## Observations
- [procedure] Expose pure helpers for destination planning, archive naming, upload verdicts, and final report validation, then compose them behind one plan command.
- [reason] A single versioned planning contract removes repeated subprocess calls and prevents workflow prose from drifting from executable naming rules.
- [evidence] A 16-test standard-library suite passed after adding the combined plan command and strict report validator.
- [outcome] The connector-facing workflow now derives PD and AD deployment paths once and validates final evidence before reporting success.
