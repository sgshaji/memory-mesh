---
type: episode
tool: github-copilot
domains: [agent-skills, cowork]
captured: "2026-09-14T12:44:10+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: archive-and-context-confirmation

## Goal

Explain the current archive layout, filename convention, Python optimization and context costs.

## What happened

Re-read current configuration, main skill and persistence guidance. Executed deterministic plan
and archive-name examples. Confirmed separate PD/AD histories, parenthesized timestamps drawn from
each item's modification time, and case-insensitive collision rejection.

Reconfirmed 5,432 main-skill characters, 19,950 Markdown characters overall, and the 1,684-line Word
helper plus 633-line deployment module.

## Decisions

- Describe the current v3-based policy, not the superseded shared-folder/shared-timestamp policy.
- Distinguish connector mutations from Python's planning and validation.
- Qualify optimization as measured local improvements, not a live model-token or SharePoint claim.

## Problems

The deterministic PDF-source plan does not explicitly archive a separate pre-existing same-stem
DOCX. Mention this limitation rather than guarantee history preservation for that case.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] - held: deterministic planning and collision probes established the
  explanation before answering.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-explicitly-plan-both-pdf-source-and-a-separate-e.md`
