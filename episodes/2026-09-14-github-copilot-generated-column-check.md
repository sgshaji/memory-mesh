---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T09:28:09+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: generated-column-check

## Goal

Determine whether the PD/AD conversion skill checks a SharePoint `Is Generated` column.

## What happened

Searched the skill and helper implementation. The skill validates field matching, DOCX package
integrity, and local-versus-stored byte counts. It does not read or write an `Is Generated`
metadata column. The helper explicitly describes source classification without a marker column.

## Decisions

- Distinguish document validation from SharePoint item classification.
- Treat generated-item filtering and trigger-loop prevention as responsibilities of the upstream
  Power Automate flow unless the skill contract is extended.

## Problems

The phrase "generated columns" was ambiguous; the answer covers both the SharePoint marker and
generated-document validation.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: inspected deterministic field, package, and byte validations before
  characterizing what the skill does not validate.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-pd-ad-skill-does-not-inspect-an-is-generated-col.md`
