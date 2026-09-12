---
type: episode
tool: github-copilot
domains: [agent-skills, coding-agents]
captured: "2026-09-08T23:07:51+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 807c31e0-afe5-4deb-b149-9f1acd2555a7
---

# Session: copilot-session

## Goal
Assess whether addyosmani/agent-skills is worth using with GitHub Copilot.

## What happened
Inspected the repository, current first-party Copilot documentation, maintenance signals, installation paths, tests, and known issues. Compared Copilot CLI, VS Code agent mode, and cloud/coding agent compatibility.

## Decisions
Recommend a repository-scoped pilot of 3-5 reviewed skills pinned to a release. Do not install the complete pack globally or assume its Claude-specific commands and personas transfer unchanged.

## Problems
Copilot-specific behavioral testing is limited, documentation has host-specific inconsistencies, some skills use references outside their directories, and several workflow rules are overly broad.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] - held: the recommendation retains deterministic schema, test, lint, and security gates instead of treating skill prose as enforcement.

## Candidate learnings
- Captured a candidate recommending native, scoped, pinned skill installation over wholesale cross-host pack adoption.
