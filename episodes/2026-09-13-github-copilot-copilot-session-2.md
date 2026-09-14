---
type: episode
tool: github-copilot
domains: [unclassified, agent-skills]
captured: "2026-09-13T00:15:15+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: copilot-session

## Goal
Determine whether the locally installed agent-skills collection can be used
in GitHub Copilot cloud sessions, including sessions started from mobile.

## What happened
Checked GitHub's current agent-skills documentation and customization support
matrix, the upstream collection's Copilot guide, and this repository's cloud
setup workflow. GitHub explicitly supports skills in cloud agent, describes
project skills in repository directories, and describes personal skills in
the local home directory. The setup workflow prepares Python and Memory Mesh
but does not install the external skill collection.

## Decisions
Treat this as a feasibility question, not permission to change cloud
configuration. Recommend repository-scoped skills with their shared resources
for reliable cloud availability. Distinguish local user installation from
cloud provisioning; do not claim an account-wide skill synchronization feature.
Pin and reuse a shared source if configuring multiple repositories.

## Problems
No technical failures. Cloud skill discovery and execution were not tested.
Some skills depend on tools that must be configured separately in the cloud.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
None. The recalled notes did not address cloud skill installation scope.

## Candidate learnings
- Provision Copilot cloud skills separately from local user skills, based on
  official documentation and the inspected workflow.
