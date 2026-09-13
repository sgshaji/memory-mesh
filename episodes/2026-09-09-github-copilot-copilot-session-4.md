---
type: episode
tool: github-copilot
domains: [document-processing]
captured: "2026-09-09T17:54:51+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: call_cEuTIzBzSS2tHdMzrxhtNvQS
---

# Session: copilot-session

## Goal

Reject structurally incomplete document packages without requiring optional parts.

## What happened

Implemented shared package structure checks and synthetic in-memory regression tests.
The new suite passed 42 tests; 16 selected existing regression tests also passed.

## Decisions

Resolve internal package references using URI semantics rather than host filesystem rules.
Keep external targets opaque to package resolution. Parse declared XML with bounded depth
and reject DTDs through the parser callback, including non-UTF-8 encodings. Leave empty
opaque signature-origin parts to the construct policy rather than treating them as XML.

## Problems

Two existing tamper subcases fail at an earlier package-read check and need expectation
updates by the coordinating task. Optional-parser wording elsewhere needs alignment with
the standard-library bounded parser.

## Knowledge retrieved


## Knowledge used

None; recall returned no knowledge notes.

## Candidate learnings

Captured the encoding-independent XML guard observation in
00-inbox/2026-09-09-github-copilot-reject-xml-declarations-across-encodings-with-a.md.
