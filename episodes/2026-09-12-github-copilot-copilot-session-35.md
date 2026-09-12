---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-12T17:16:37+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 2c3bb810-d344-4cc0-9526-d193c6ca213a
---

# Session: copilot-session

## Goal
Install the complete addyosmani/agent-skills collection for Copilot at user
level across projects, preserving existing skills.

## What happened
Confirmed personal skill discovery locations in official VS Code documentation.
Installed all 25 skills with published skills CLI 1.5.23, using the global,
GitHub Copilot, and all-skills selectors. The installer used ~/.agents/skills.
Retained a full user-level checkout at commit
be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39 and linked its shared references
through ~/.agents/references.

Verified all 30 installed files matched the checkout by SHA-256, all three
existing Memory Mesh skills were unchanged, and the global registry listed
the 25 additions. The upstream validator reported zero errors and warnings;
all 20 shared-reference links resolved to the seven expected files.

## Decisions
Use the supported shared personal skills directory without modifying any
project. Preserve omitted shared resources with a non-overwriting directory
junction to the retained checkout. Install skills, not Claude-specific plugin
commands or hooks. A fresh chat or reload may be needed for runtime discovery;
current-session activation was not verified.

## Problems
The repository's development package version 1.5.26 was not published on npm.
Resolved the published version with npm and succeeded with 1.5.23.
The default installer omitted repository-level references even when installing
all skills; the user-level junction restored their relative paths.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] - not-applicable: no LLM processing pipeline was changed.
  Installation was independently verified with hashes and the upstream linter.

## Candidate learnings
- [[00-inbox/2026-09-12-github-copilot-global-agent-skills-installation-needs-shared-re]]
