---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-14T09:31:33+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: isgenerated-preflight-error

## Goal

Explain why a customer's PD Conversion Assistant stopped because `IsGenerated` was missing.

## What happened

Traced screenshot phrases across local projects and found that the deployed V0.3 behavior matches
`Ali-version/pd-ad-conversion`, not the current `pd-ad-conversion` workspace copy. The deployed
variant configures `generatedColumnName: IsGenerated`; its preflight requires reading that field,
and deployment must mark verified outputs Yes.

## Decisions

- Treat the failure as an expected deployment-prerequisite failure in the Ali variant.
- Recommend either provisioning the configured Yes/No column or redeploying the complete
  column-free variant; do not mix files or remove only the check.

## Problems

The workspace contains two incompatible skill variants. Inspecting only the current working
directory initially produced an answer that did not apply to the deployed assistant.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used

- [[validation-order]] — held: the deployed variant validates configuration and SharePoint schema
  before LLM mapping or mutation, producing the observed early failure.
- [[projects/copilot-studio-skills]] — not-applicable: it concerns a separate validation project.

## Candidate learnings

- `00-inbox/2026-09-14-github-copilot-pd-ad-skill-variants-have-different-isgenerated.md`
