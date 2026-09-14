---
type: tool-behaviour
title: Copilot Studio schema generator omits optional properties unless declared
domains: [copilot-studio]
status: validated
trust: first-party
confidence: medium
applies_to:
  tools: [copilot-studio]
  from: 2026-07
first_observed: 2026-09-01
last_verified: 2026-09-01
feedback: {served: 2, held: 1, failed: 0, unclear: 1}
evidence: [episodes/2026-09-01-copilot-studio-schema-stage]
superseded_by: null
source: "episode: episodes/2026-09-01-copilot-studio-schema-stage"
---

## Observations
- [behaviour] the tool-schema generator silently drops optional properties from generated payload schemas
- [fix] declare every optional property explicitly in the schema; generation then validates
- [command] verified with `validate --schema tool.json` on the 2026-07 build

## Relations
- derived_from [[episodes/2026-09-01-copilot-studio-schema-stage]]
- mitigated_by [[schema-validation-workaround]]
