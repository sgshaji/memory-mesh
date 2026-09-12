---
type: episode
tool: github-copilot
domains: [agent-skills, document-processing]
captured: "2026-09-12T12:08:47+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Optimize the supplied unattended PD agent instructions while keeping them separate from the skill.

## What happened

Replaced the generic recommendation with a 1,269-character instruction block tailored to unattended workflow execution. It preserves mandatory skill delegation, visible failures, delegated judgments, one permitted correction, credential boundaries, and evidence-based reporting. Verified that the seven-entry skill ZIP does not contain agent instructions.

## Decisions

Agent-level instructions own identity, routing, unattended behavior, and security. The skill remains the sole authority for task procedure, SharePoint lifecycle, validation, rollback, and report schema.

## Problems

None.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- `held` — `validation-order`: the instruction keeps validated skill output as the only acceptable final result.

## Candidate learnings

No additional candidate; separation of agent and skill responsibilities was captured in the preceding packaging candidate.
