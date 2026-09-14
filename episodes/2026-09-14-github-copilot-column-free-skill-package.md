---
type: episode
tool: github-copilot
domains: [agent-skills, cowork]
captured: "2026-09-14T09:34:13+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: column-free-skill-package

## Goal

Create a deployable PD/AD skill ZIP that does not require a SharePoint `IsGenerated` column.

## What happened

The user selected the current column-free workspace variant instead of modifying deployed V0.3.
Created `pd-ad-conversion-no-isgenerated.zip` containing root `SKILL.md` and
`scripts/pd_tools.py`.

Validated the exact archive layout, scanned all entries for generated-column contract terms,
compared archived bytes with source hashes, extracted the package, and ran the packaged helper's
`--help` command successfully.

## Decisions

- Preserve the selected workspace files as-is.
- Create a new archive rather than overwrite the older `scripts.zip`.

## Problems

None. The current workspace has no automated test suite, so verification used deterministic archive
checks and packaged-helper startup.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: deterministic ZIP structure, forbidden-term, hash, and executable
  checks were completed before reporting the artifact.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-column-free-pd-ad-skill-zip-built-from-workspace.md`
