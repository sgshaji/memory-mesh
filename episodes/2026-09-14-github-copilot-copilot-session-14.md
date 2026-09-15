---
type: episode
tool: github-copilot
domains: [unclassified, copilot-studio]
captured: "2026-09-14T22:24:28+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: d99007a5-2933-4cd6-9e73-dee1da060af2
---

# Session: copilot-session

## Goal
Review a transcript-to-agent workflow and distinguish evaluation capabilities from enforced quality guarantees.

## What happened
Inspected lifecycle instructions, local validators, schemas, synthetic fixtures, and installation wiring. Consulted official documentation about native agent test sets. Ran 38 targeted local tests without invoking cloud authoring or agent actions. After canonicalizing Windows temporary paths for the test process, 36 passed and two offline-reference integration tests failed.

## Decisions
Kept the project review read-only. Distinguished model-executed skill instructions from deterministic implementation. Recommended semantic gate enforcement before expanding evaluation generation, explicit requirements coverage, and a single orchestration entry point.

## Problems
Six synthetic evaluation probes accepted a declared pass with contradictory or incomplete evidence, including critical failure, nonexecution, missing scores, and empty browser-evidence references. Hash and schema checks did not recompute behavioral readiness. Initial local failures also exposed short-versus-long Windows path spelling assumptions.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]

## Knowledge used
- [[validation-order]] - held: local probes demonstrated the need for deterministic semantic checks before accepting model-authored evaluation decisions; structural validation alone was insufficient.

## Candidate learnings
- [[00-inbox/2026-09-14-github-copilot-artifact-integrity-checks-do-not-enforce-behavio]] - captured as an unvalidated candidate with synthetic evidence and actionable gate checks.
