---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-12T11:51:05+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Align, harden, and optimize the PD/AD SharePoint conversion skill, then clarify its upload-size verification.

## What happened

Implemented separate PD and AD destinations and archive lifecycles, deterministic planning and archive helpers, collision rejection, rollback evidence, strict report validation, and a single-pass DOCX fill. Added 16 regression tests; tests, compilation, diagnostics, terminology checks, and cleanup passed. Clarified that the 2,048-byte value is an allowed stored-versus-sent overhead threshold, not a maximum document size.

## Decisions

Keep SharePoint operations connector-driven while treating the Python helper as the versioned contract. Compare the local uploaded byte count with SharePoint's stored size; fail truncation/path mistakes and require download comparison for unexplained overhead.

## Problems

The initial destination interpretation placed AD output beside PD; screenshots established the separate `AD Documents` lifecycle. No unresolved implementation problems remain.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used

- `held` — `validation-order`: deterministic report and deployment validation is executed before success is claimed.
- `not-applicable` — `projects/copilot-studio-skills`: the project note concerns a different validation-skill build.

## Candidate learnings

Captured a candidate about centralizing connector workflow contracts in pure, tested helper functions.
