---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-08T23:10:55+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 807c31e0-afe5-4deb-b149-9f1acd2555a7
---

# Session: full-agent-skills-install

## Goal
Install the complete addyosmani/agent-skills pack for GitHub Copilot in the current repository.

## What happened
Used GitHub CLI's native skill manager to install all 25 skills at project scope, pinned to release 0.6.9. Added seven shared reference files omitted by the manager and preserved the upstream MIT license.

## Decisions
Used repository scope rather than user scope to avoid changing Copilot behavior in unrelated projects. Retained installer provenance metadata so `gh skill list` and future updates work.

## Problems
The publisher validator rejects installer provenance metadata by design, so validation was run against the pinned pristine source. The installer omitted shared references used by relative links; pinned copies repaired them.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] - held: deterministic schema validation ran against pristine source before completion, followed by link and SHA-256 checks.

## Candidate learnings
- None; the scoped and pinned installation approach was already captured in this session.
