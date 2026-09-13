---
type: episode
tool: github-copilot
domains: [document-processing, agent-skills]
captured: "2026-09-12T12:20:43+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Validate an execution trace, eliminate avoidable connector calls, and prevent unsafe source selection.

## What happened

The trace used an archived AD as the source, accepted it because its generated flag was false, and trusted a plan yielding nested archive folders. It also tried decoded-text staging before base64 and passed a path to an identifier parameter. Added config-aware source-location rejection, exact identifier guidance, first-choice byte-faithful staging, one deterministic path-to-ID correction, and explicit `includeAd` selection. Rebuilt the upload ZIP.

## Decisions

Source location and invocation mode are independent evidence from generated metadata. The planner now rejects direct AD/archive parents before SharePoint browsing. Workflow `includeAd` controls output selection; template presence is only the backward-compatible default.

## Problems

The first ZIP rebuild included a Python cache created by tests. Cleaning caches before compression and strengthening the archive-entry check fixed it.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held — invalid source location is rejected deterministically before staging or model mapping.

## Candidate learnings

Captured `00-inbox/2026-09-12-github-copilot-reject-workflow-outputs-as-future-source-inputs.md`.
