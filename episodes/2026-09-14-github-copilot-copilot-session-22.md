---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-14T23:45:35+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: d99007a5-2933-4cd6-9e73-dee1da060af2
completeness: complete
prefilled:
  knowledge_retrieved: {source: provided-retrievals, evidence: reported}
---

# Session: copilot-session

## Goal
Explain feasibility of explicitly linking environment-resident evaluation sets to an agent before executing them.

## What happened
Consulted official Dataverse relationship and managed-property documentation. Distinguished a proposed persistent association from a test-run record and from native Evaluation membership.

## Decisions
Recommend a separately packaged binding record identifying the target environment and bot, the Kit test set and environment, and dataset version/hash. Prefer valid lookups where supported and verify installed metadata before adding relationships. Verify the persisted association before reporting ingestion complete and check it before execution. Do not create a run merely to establish an association.

## Problems
This is a design recommendation, not an implemented or live-validated feature. Installed Kit customization eligibility and cross-environment target setup remain to be checked. A custom association does not populate the native Evaluation page or automatically constrain runs made outside the integrating application.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
No recalled note was exercised in a new runtime test.

## Skill outcomes
Used interface-design principles to distinguish durable identity from names and execution side effects. No project code or cloud resources changed.

## Candidate learnings
No new candidate: proposed integration design is not yet verified in a target environment.
