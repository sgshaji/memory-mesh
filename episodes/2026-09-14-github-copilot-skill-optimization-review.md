---
type: episode
tool: github-copilot
domains: [agent-skills, cowork]
captured: "2026-09-14T10:10:52+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: skill-optimization-review

## Goal

Assess whether the PD/AD `SKILL.md` can be optimized without weakening its behavior.

## What happened

Read the full 500-line file and measured 3,592 words across 22 headings. Field mapping, pruning, and
persistence contain more than half of the text. Identified repeated routing and failure rules,
phase-order complexity, and deterministic helper commands omitted from the skill's command table.

## Decisions

- Resolve behavioral conflicts before shortening the document.
- Prefer a concise orchestration file plus phase-specific references.
- Preserve high-risk invariants in the main skill and move examples and command detail out.

## Problems

The current contract conflicts on missing-field highlighting, allows AD-only output while always
archiving the source PD, and defines no rollback after pre-upload archive moves. These are
correctness decisions, not wording cleanups.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: the review prioritizes deterministic plan/report helpers before
  LLM-driven orchestration and wording reduction.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-pd-ad-skill-md-optimization-should-resolve-three.md`
