---
type: episode
tool: github-copilot
domains: [agent-skills, coding-agents]
captured: "2026-09-12T18:29:42+00:00"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 5ae68d78-a46a-41f3-894d-c58941474719
---

# Session: copilot-session

## Goal
Install three selected Agent Skills for repository-local Copilot cloud use.

## What happened
Reviewed a pinned upstream revision and its MIT license. Installed
idea-refine, interview-me, and spec-driven-development with supporting
references and attribution. Added packaging checks to existing Copilot
integration tests and documented activation and usage.

## Decisions
Use repository skill discovery rather than a CLI plugin or new dependencies.
Omit the optional setup script. Adapt questions to cloud follow-up turns,
keep drafts in conversation unless files are explicitly requested, and
preserve bounded recall and frozen-contract boundaries. Replace mandatory
references to uninstalled companion skills with inline guidance.

## Problems
Live skill discovery requires a fresh cloud session and is not verified here.
The focused tests passed. The default whitespace check flagged existing CRLF
line endings in the test file; the CRLF-aware check passed without changing
the file's established line-ending convention.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
None. The recalled validation-order note concerns a different workflow and
was not exercised during installation.

## Candidate learnings
None. Installation scope and activation are documented in the README.
