---
type: episode
tool: github-copilot
domains: [unclassified]
captured: "2026-09-12T12:07:11+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Produce a Copilot Studio upload package and token-efficient agent instructions for the PD/AD skill.

## What happened

Verified current Microsoft requirements for Copilot Studio skills using the GitHub Copilot harness. Built a ZIP with `SKILL.md` at root plus runtime config, references, and Python; excluded tests and caches. Extracted it to a temporary directory, validated configuration, compiled the script, and checked package limits. Added concise recommended agent instructions outside the ZIP.

## Decisions

Keep workflow detail in the skill and only routing, scope, and credential boundaries in agent instructions. Do not package tests or agent instructions as runtime skill context. Live SharePoint behavior remains a Preview/staging validation because connectors and credentials are orchestrator capabilities, not script capabilities.

## Problems

The user's current agent-instruction text was not present in the message or workspace, so a clean replacement was created rather than claiming a line-by-line optimization.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used

- `held` — `validation-order`: the extracted package configuration was validated before declaring the ZIP ready.
- `not-applicable` — `projects/copilot-studio-skills`: the recalled project concerns another validation-skill build.

## Candidate learnings

Captured `00-inbox/2026-09-12-github-copilot-package-copilot-studio-skills-with-runtime-artif.md`.
