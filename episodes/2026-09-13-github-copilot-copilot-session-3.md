---
type: episode
tool: github-copilot
domains: [coding-agents]
captured: "2026-09-13T00:18:54+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: copilot-session

## Goal
Clarify support for installing a skill bundle once for a personal GitHub
account and using it in cloud sessions across arbitrary repositories.

## What happened
The user corrected the scope: repository-only installation was not the goal.
Checked GitHub's current custom-agent scope documentation and instruction
support table. Cloud custom agents are documented at repository, organization,
and enterprise scopes. Personal instructions are listed for Copilot Chat but
not for cloud agent.

## Decisions
Answer the exact account-wide requirement directly: no supported
personal-account-wide cloud skill installation was identified in the
documentation reviewed. Do not substitute a local global install or a
per-repository setup. Organization-level custom agents and instructions are
related cross-repository options, not equivalent personal account skill stores.
No repository provisioning or GitHub settings changes were made.

## Problems
The previous recommendation was technically applicable to cloud use but did
not satisfy the user's requested scope. No cloud execution test was performed.

## Knowledge retrieved


## Knowledge used
None.

## Candidate learnings
- Distinguish personal Chat customization from organization-scoped shared
  cloud-agent customization; a custom agent is not a complete skill bundle.
