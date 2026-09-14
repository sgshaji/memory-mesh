---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-14T21:21:02+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: v2-personal-pilot-implementation

## Goal
Implement the experimental personal-pilot learning workflow without migrating or promoting the user's live vault.

## What happened
Implemented bounded task/evidence records, strict admission, explicit validation execution, human-review publication, conditional recall, session handoff, feedback, and observational evaluation commands. Preserved V1 defaults and documented the experimental interfaces and remaining release gates.

The full unittest suite passed: 363 tests, two existing skips. An isolated wheel build and installed-package workflow passed; the wheel contained required modules, no live vault data, and no third-party runtime dependencies. Read-only vault lint reported zero errors and warnings. Temporary package-validation copies were removed.

## Decisions
Require actual execution evidence plus human semantic review; keep host capability labeled assisted. Do not infer truth or savings from success-shaped text, repeated reports, or aggregate statistics. Off mode does not silently restore legacy recall.

Keep canonical publication curator-owned and retain immutable evidence identities. Use a fresh bytecode view for source-bound checks. Leave paid experiments, host qualification, capacity studies, licensing, and hosted/team rollout as explicit release gates.

## Problems
Implementation scope grew too large and took too long; the user raised the elapsed time. Stopped feature expansion and closed validation blockers.

Independent review exposed junction redirection, structured-secret checks, whitespace identity aliases, skipped-test accounting, invalid result ingestion, stale bytecode, and recursive discovery issues. Regression tests reproduced these before fixes. Also fixed string-identity/escaped-quote loss in the shared frontmatter codec.

The first wheel attempt lacked the declared build backend; isolated build dependencies resolved it. An editor snippet timed out; a terminal check verified the installed package instead.

## Knowledge retrieved
- [[validation-order]] (supplied in the conversation's recalled context)
- [[projects/copilot-studio-skills]] (supplied in the conversation's recalled context)

## Knowledge used
None. The recalled notes were not exercised in their documented tool scenarios.

## Candidate learnings
- [[00-inbox/2026-09-14-github-copilot-fresh-cache-views-are-required-for-python-source]]: verified stale-bytecode counterexample and mitigation; candidate only.
