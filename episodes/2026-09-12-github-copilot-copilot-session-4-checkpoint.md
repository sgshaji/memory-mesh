---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-12T11:19:35+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal
Align the PD/AD conversion skill with the actual SharePoint layout and separate PD and AD histories.

## What happened
Updated the skill instructions and deterministic destination helper. PD output now uses the source
parent and a `.docx` filename. AD output now uses the existing `AD Documents` child and an
` - AD.docx` filename. Each destination has its own `Archive`. Added first-generation versus
regeneration rules, metadata handling, pre-mutation generation safety, and reporting examples.
Contract tests covered PDF and DOCX sources, archive naming, invalid folder/link inputs, and path
length rejection.

## Decisions
- A source PDF keeps its base name but generated PD output uses `.docx`.
- AD output is `<source base> - AD.docx` under `AD Documents`.
- Archive names remain `<stem> (YYYYMMDD-HHMMSS)<extension>`.
- Generate and validate all requested documents before any SharePoint mutation.
- Require one PD template and at most one AD template.

## Problems
The prior implementation sent both outputs to the source parent under one filename, causing them to
replace each other. It also risked putting Word package bytes under a `.pdf` extension.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] — held — deterministic destination and archive contracts were tested before
  considering the skill update complete.

## Candidate learnings
None; these are project-specific SharePoint conventions.
