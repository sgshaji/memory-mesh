---
type: episode
tool: github-copilot
domains: [document-processing, agent-skills]
captured: "2026-09-09T21:05:53+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 36fdcb86-0c9f-421b-8f90-f382c0fceafb
---

# Session: copilot-session

## Goal
Determine how a workflow can consume an agent-generated DOCX and upload it to SharePoint.

## What happened
Compared the observed verbose agent response with current Microsoft documentation for GitHub Copilot harness created files and workflow Agent-node outputs. Created files appear as conversation file cards, while downstream Agent-node outputs are documented as text or structured values only.

## Decisions
Do not treat response prose or an internal `/app/created/` path as file content. Recommend moving final byte materialization into a deterministic flow action or using an in-run connector/tool that returns a durable file identifier.

## Problems
The desired direct handoff from a created-file card to a later workflow step is not exposed by the documented Agent-node output contract.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] — held — the recommended design validates and materializes bytes deterministically before SharePoint upload.

## Candidate learnings
- `00-inbox/2026-09-09-github-copilot-github-copilot-harness-workflow-agent-nodes-do-n.md`
