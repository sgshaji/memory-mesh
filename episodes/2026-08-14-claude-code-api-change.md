---
type: episode
tool: claude-code
project: copilot-studio-skills
domains: [coding-agents, agent-skills]
captured: 2026-08-14T16:20:00+05:30
duration_min: 50
trust: first-party
sensitivity: checked
status: mined
session_ref: cc-3b1e
mined: [knowledge/patterns/validation-order, knowledge/failures/large-file-upload-failure]
---

# Session: API change in the validation skill

## Goal
Change the payload validation interface without breaking dependent skills.

## What happened
- edited the interface first → two dependent files broke silently
- listed every dependent file before retrying → clean refactor
- tried uploading a 40 MB knowledge file to test grounding → stuck in processing forever

## Decisions
- run deterministic validation before any LLM step — reproducible and cheaper

## Problems
- knowledge-source upload over 30 MB never becomes queryable (copilot-studio, 2026-08)

## Knowledge retrieved
- [[validation-order]]

## Knowledge used
- [[validation-order]] — held — validation-first sequence worked as documented

## Candidate learnings
- list every dependent file before changing an interface (claude-code, 2026-08)
