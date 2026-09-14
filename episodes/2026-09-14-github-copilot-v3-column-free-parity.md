---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T11:10:08+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: v3-column-free-parity

## Goal

Restore version `(3)` feature parity while removing the unsupported SharePoint generated-column
dependency.

## What happened

Confirmed that the earlier column-free package came from a simpler branch and omitted configuration
validation, DOCX extraction, deterministic planning, path checks, collision handling, semantic
upload bindings, and `validate-run`.

Rebuilt from version `(3)`, bumped schema and contract versions to 2, removed generated-column and
marking fields, added cyan gap handling, retained source archiving and rollback, and synchronized
the verified implementation into the active workspace.

## Decisions

- Version `(3)` is the authoritative feature baseline.
- Keep its configured AD folder and independent archive histories.
- Preserve all eleven helper commands.
- Remove only custom-column behavior, while retaining flow-owned trigger filtering.

## Problems

The previous simplified package passed its own tests but was not a feature-parity replacement for
version `(3)`.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: schema v2 and run-report validation deterministically reject stale
  generated-column configuration before LLM processing.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-v3-feature-parity-pd-ad-package-without-generate.md`
