---
type: episode
tool: copilot-studio
project: copilot-studio-skills
domains: [copilot-studio, agent-skills]
captured: 2026-09-01T17:40:00+05:30
duration_min: 45
trust: first-party
sensitivity: checked
status: mined
session_ref: cw-7f3a
mined: [knowledge/tools/cs-optional-properties, knowledge/workarounds/schema-validation-workaround]
---

# Session: document-validation skill, schema stage

## Goal
Make the validation skill reject malformed tool payloads before the LLM step.

## What happened
- inspected the generated tool schema
- tried tightening the prompt → payloads still malformed
- declared optional properties explicitly in the schema → validation passed

## Decisions
- deterministic validation runs before any LLM reasoning — cheaper and reproducible

## Problems
- schema generator silently omitted optional properties (copilot-studio, 2026-07 build)

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]
- [[schema-validation-workaround]]

## Knowledge used
- [[validation-order]] — held — sequence worked as documented
- [[cs-optional-properties]] — held — fix applied exactly as the note says

## Candidate learnings
- schema generator drops optional properties unless declared (copilot-studio, 2026-07)
