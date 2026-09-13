---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-09T19:55:59+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 36fdcb86-0c9f-421b-8f90-f382c0fceafb
---

# Session: copilot-session

## Goal
Create a root-level agent instruction file for artifact-only PD conversion.

## What happened
Created `instruction.md` with unattended behavior, mandatory use of the conversion skill, immutable inputs, preserved generation rules, final package validation, and explicit file-artifact output without SharePoint upload.

## Decisions
Keep transport ownership with the invoking deterministic workflow.

## Problems
None.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — held — the instruction requires final deterministic package validation before returning an artifact.
- [[projects/copilot-studio-skills]] — not-applicable — this was an agent instruction file, not a Studio validation change.

## Candidate learnings
None.
