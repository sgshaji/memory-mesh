---
type: failure
title: Knowledge-source upload fails silently for files over 30 MB
domains: [copilot-studio]
status: validated
trust: first-party
confidence: low
applies_to:
  tools: [copilot-studio]
  from: 2026-08
first_observed: 2026-08-20
last_verified: null
feedback: {served: 1, held: 0, failed: 0, unclear: 0}
evidence: [episodes/2026-08-14-claude-code-api-change]
superseded_by: null
source: "episode: episodes/2026-08-14-claude-code-api-change"
---

## Observations
- [behaviour] uploading a knowledge-source file larger than roughly 30 MB completes the UI flow but the source never becomes queryable
- [error] no error surfaces; the source stays in `processing` indefinitely

## Relations
- observed_in [[episodes/2026-08-14-claude-code-api-change]]
