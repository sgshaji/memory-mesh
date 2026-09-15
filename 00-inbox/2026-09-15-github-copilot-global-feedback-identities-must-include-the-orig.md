---
type: candidate
title: Global feedback identities must include the originating admission namespace
source: "automatic capture via github-copilot, 2026-09-15"
captured: "2026-09-15T09:05:00+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: aa077d1ffb8ca08a
project: memory-mesh-feedback
signal: high
source_episode: episodes/2026-09-15-github-copilot-feedback-loops
---

## Observations
- [scenario] Two approved Memory Mesh lessons from different origin tasks reused the task-local proposal label lesson-1 and feedback label shared-use.
- [behaviour] An event identity based only on the target task, proposal label and feedback label collided across the two knowledge subjects.
- [procedure] Derive new shared-journal identities from the complete source admission namespace as well as the target receipt identity, while preserving already-persisted legacy IDs on replay.
- [evidence] The cross-origin integration test records both reviewed lessons from one target, verifies distinct journal IDs, and independently replays both without duplicating either outcome (Memory Mesh 0.1.0 feedback extension, Python 3.13.15).
