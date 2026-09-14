---
type: pattern
title: Deterministic validation before any LLM reasoning
domains: [copilot-studio, agent-skills]
status: validated
trust: first-party
confidence: medium
applies_to:
  tools: [copilot-studio, claude-code]
  from: 2026-08
first_observed: 2026-08-14
last_verified: 2026-09-01
feedback: {served: 3, held: 2, failed: 0, unclear: 1}
evidence: [episodes/2026-08-14-claude-code-api-change, episodes/2026-09-01-copilot-studio-schema-stage]
superseded_by: null
source: "episode: episodes/2026-08-14-claude-code-api-change"
---

## Observations
- [behaviour] LLM steps accept malformed payloads that deterministic validation would reject
- [fix] run schema validation before any LLM reasoning step — cheaper and reproducible
- [procedure] validate schema → reject early → only then invoke the LLM stage

## Relations
- derived_from [[episodes/2026-08-14-claude-code-api-change]]
- supports [[schema-validation-workaround]]
