---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-14T10:27:22+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: optimized-skill

## Goal

Optimize the column-free PD/AD skill while resolving its missing-field, required-output, and
rollback ambiguities.

## What happened

Confirmed that missing placeholders remain cyan-highlighted, exactly one PD output is mandatory,
and any failure after SharePoint mutation requires full rollback.

Reduced the main skill from 500 lines and 3,592 words to 182 lines and 968 words. Moved detailed
template processing, SharePoint persistence, and output reporting into phase-specific references.
Hardened the Python report command to enforce one PD, local package validity, archived-source
evidence, failure precedence, and rollback-status consistency.

Rebuilt the ZIP with the main skill, helper, and three references.

## Decisions

- Keep hard invariants and ordered orchestration in the main skill.
- Load detailed references only when their phase begins.
- Preserve cyan gap highlights while stripping template highlighting.
- Require no custom SharePoint columns.

## Problems

The original monolith duplicated rules and allowed success-shaped reports despite explicit failure
reasons. The previous package also lacked phase references and deterministic rollback validation.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used

- [[validation-order]] — held: contract validation and report checks run before LLM-dependent
  processing or SharePoint mutation.
- [[projects/copilot-studio-skills]] — not-applicable: this is a separate PD/AD skill project.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-pd-ad-skill-modularized-with-deterministic-safet.md`
