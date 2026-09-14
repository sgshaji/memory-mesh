---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T09:42:51+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: choose-skill-zip

## Goal

Determine which of two PD/AD skill ZIPs should be deployed for a customer unable to add SharePoint
columns.

## What happened

Inspected both archives directly, compared manifests and helper hashes, scanned generated-column
contracts, compiled both packaged Python helpers, and ran their startup interfaces.

The column-free archive contains only `SKILL.md` and `scripts/pd_tools.py` and has no generated-column
contract. Version `(3)` contains seven files and explicitly configures, documents, and validates
`generatedColumnName: IsGenerated`.

## Decisions

- Recommend the column-free archive for this customer.
- Do not install both packages because both expose the same skill name.
- Require the orchestrating flow to exclude generated outputs from later invocations.

## Problems

Version `(3)` is internally valid but incompatible with the customer's fixed SharePoint schema.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: both archives were validated deterministically before selecting one.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-use-column-free-pd-ad-package-when-sharepoint-sc.md`
