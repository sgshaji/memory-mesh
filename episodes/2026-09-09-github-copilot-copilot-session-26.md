---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-09T21:38:24+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 36fdcb86-0c9f-421b-8f90-f382c0fceafb
---

# Session: copilot-session

## Goal
Record the broader platform issue affecting deterministic reuse of agent-created files.

## What happened
Captured a candidate describing the gap between downloadable conversation file cards and workflow-consumable file outputs, including current workarounds and the desired platform capability.

## Decisions
Treat in-agent path-aware connector upload as the temporary no-hosting workaround. Track first-class typed file output from Agent nodes as the broader fix.

## Problems
Deterministic downstream steps cannot currently consume an agent-created attachment directly.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] — held: the proposed platform fix preserves deterministic validation and transport outside additional model reasoning.

## Candidate learnings
- `00-inbox/2026-09-09-github-copilot-created-agent-files-need-a-first-class-workflow.md`
