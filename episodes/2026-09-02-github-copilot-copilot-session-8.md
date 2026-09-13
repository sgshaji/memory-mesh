---
type: episode
tool: github-copilot
domains: [unclassified, coding-agents, document-processing]
captured: "2026-09-02T21:43:10+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 0e8d1f30-c255-4d8f-a296-0e86b1d9521b
---

# Session: copilot-session

## Goal
Implement automatic, agent-authored capture of verified reusable findings for
GitHub Copilot without requiring a special user prompt.

## What happened
Added a structured learning input with deterministic schema validation,
redaction, domain assignment, deduplication, and inbox-only persistence. Updated
Copilot instructions and the memory-learn skill to trigger capture
autonomously while context is warm. Reinstalled the user-level integration.
The full suite passed 143 tests with two environment-dependent skips; vault
lint passed with no findings.

## Decisions
- Keep reasoning and structure selection in the active coding agent.
- Keep validation, redaction, classification fallback, and writing deterministic.
- Require an actionable observation plus an outcome or evidence.
- Never promote automatically captured candidates into canonical knowledge.

## Problems
- Copilot's sessionEnd hook has no transcript, so it cannot reliably extract
  learnings after the conversation ends. Capture now occurs during active work.
- Initial review found multiline-field corruption, unredacted project metadata,
  ignored CLI overrides, and an incomplete skill example; all were corrected.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — held: deterministic validation runs before candidate
  persistence and rejected malformed structured inputs in tests.

## Candidate learnings
- [[00-inbox/2026-09-02-github-copilot-copilot-sessionend-hooks-do-not-expose-the-sessi]]
