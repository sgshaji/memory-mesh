---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T12:09:52+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: measured-context-optimization

## Goal

Optimize the current v3 column-free skill without losing its deployment and document-processing
features.

## What happened

Added failing regression tests for blank/nontext paragraphs, downloaded-package comparison,
compact inspection, text-only extraction, and avoiding unrelated ZIP decompression.

Fixed filling on blank paragraphs and added an evidence-based CHECK resolution path shared by
verify and report validation. Extracted pure deployment logic into a sibling module using an
AST-guided transformation; preserved CLI commands. Simplified pruning boundary/protection helpers.

Reduced main guidance from 10,681 to 5,432 characters and all Markdown from 31,975 to 19,950.
Synthetic inspection output shrank 7.9 percent and text-only extraction JSON 74.6 percent while
retaining decision evidence and identical source text.

## Decisions

- Keep schema/contract v2, all eleven commands, original full diagnostic modes, configured separate
  AD/archive layout, per-file timestamps, and rollback guidance.
- Use compact/text-only modes in normal skill runs; keep setup guidance out of routine context.
- Do not estimate customer model token usage as an exact measurement.

## Problems

One intermediate patch placed a guard in the wrong function; tests exposed the syntax error and
it was corrected before packaging. Customer SharePoint execution was not available.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] - held: deterministic package comparison rechecks downloaded contents and
  sizes rather than trusting success flags; all 55 tests pass.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-reduce-skill-context-through-single-source-guida.md`
