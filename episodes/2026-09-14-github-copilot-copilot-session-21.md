---
type: episode
tool: github-copilot
domains: [unclassified, copilot-studio]
captured: "2026-09-14T23:33:59+05:30"
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
Clarify local versus remote evaluation storage and whether a test suite is directly attached to an agent.

## What happened
Performed a read-only follow-up on the authorized reference. Traced local workspace organization, versioned approval, remote suite creation, run-to-target relationships, and the separate native evaluation client.

## Decisions
Explain storage location, logical grouping, and database association separately. Do not infer a remote agent binding from a local per-agent folder name. Distinguish suite creation from the later operation that selects an agent for execution.

## Problems
No cloud records were inspected or changed; conclusions are based on implementation inspection rather than a current tenant inventory.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]

## Knowledge used
No recalled note was independently exercised in this clarification.

## Skill outcomes
Confirmed the relevant create and lookup paths without executing reference code or modifying the working project.

## Candidate learnings
No additional candidate; this clarifies the previously captured distinction between Kit and native evaluation backends.
