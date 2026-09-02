---
type: episode
tool: claude-code
domains: [copilot-studio]
captured: "2026-09-02T16:33:08+05:30"
trust: first-party
sensitivity: checked
status: mined
session_ref: dod-demo
mined: [knowledge/tools/grounding-sources-must-be-revalidated-after-ever]
---

# Session: cs-validation-agent

## Goal
Build a Copilot Studio validation agent for document grounding sources.

## What happened
- applied validation-first sequencing from recall → deterministic stage passed
- declared optional properties explicitly per the recalled fix → schema validated
- published, then noticed grounding bindings reset → revalidated and re-bound

## Decisions
- validation topic runs before any generative step — reproducible and cheaper

## Problems
- grounding bindings silently reset after publish (copilot-studio, 2026-09)

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — held — deterministic-first sequence worked as documented
- [[cs-optional-properties]] — held — declaring optional properties fixed generation

## Candidate learnings
- grounding sources must be revalidated after every publish because bindings reset (copilot-studio, 2026-09)
