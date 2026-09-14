---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T10:03:14+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: source-archive-fix

## Goal

Fix the column-free PD/AD skill so every supplied source PD is archived during conversion.

## What happened

Reproduced the issue from the instructions: they explicitly protected PDF sources from archiving.
Added failing contract and helper-plan tests, then changed the skill, agent instructions, and
destination planner to archive PDF and DOCX sources. Existing PD and AD destinations are also
planned for the same Archive folder under one timestamp.

Rebuilt `pd-ad-conversion-no-isgenerated.zip` and validated the packaged PDF, DOCX, and AD plans.

## Decisions

- Always archive the source, regardless of extension.
- De-duplicate a DOCX source that is also the PD destination.
- Keep PD and AD outputs beside the source, with one shared Archive folder.
- Retain the column-free design.

## Problems

The previously delivered package implemented a narrower replacement-only archive policy and
therefore did not satisfy the source-archive requirement.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: a failing deterministic contract test reproduced the bug before the
  fix, followed by six passing tests and direct packaged-output validation.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-column-free-pd-ad-package-must-always-archive-th.md`
