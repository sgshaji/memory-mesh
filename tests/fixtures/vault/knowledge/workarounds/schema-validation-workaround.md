---
type: workaround
title: Pre-validate tool payloads with an explicit JSON schema stage
domains: [copilot-studio]
status: validated
trust: first-party
confidence: low
applies_to:
  tools: [copilot-studio]
  from: 2026-08
first_observed: 2026-09-01
last_verified: null
feedback: {served: 1, held: 0, failed: 0, unclear: 0}
evidence: [episodes/2026-09-01-copilot-studio-schema-stage]
superseded_by: null
source: "episode: episodes/2026-09-01-copilot-studio-schema-stage"
---

## Observations
- [fix] add an explicit JSON-schema validation topic before the tool-invocation step until the generator declares optional properties itself
- [procedure] copy the generated schema, declare optional properties, validate payloads against it in a deterministic step

## Relations
- derived_from [[episodes/2026-09-01-copilot-studio-schema-stage]]
- mitigated_by [[cs-optional-properties]]
