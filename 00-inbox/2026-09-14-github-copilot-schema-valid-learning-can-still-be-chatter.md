---
type: candidate
title: Schema-valid learning can still be chatter
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T12:49:28+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: c284b76bb9f265c0
---

## Observations
- [scenario] Memory Mesh structured capture validates agent-authored learning records before the candidate-writing boundary.
- [limitation] An actionable kind plus an outcome/evidence kind is a structural requirement, not verification that the conversation contains a useful lesson or that the claimed outcome occurred.
- [evidence] A Python 3.13.15 no-write check mocked routing input, redaction, and the candidate writer. A record missing actionable labels raised ValueError; a thanks/continue record labeled procedure and outcome reached the mocked writer. The plain-text learn path also admitted nonempty chatter to that boundary.
- [procedure] Treat successful capture as admission of a candidate, not confirmation of truth or usefulness. Verify the underlying task result and applicability separately before treating the lesson as reliable.
- [outcome] The three admission assertions passed; no test chatter was persisted, no curator was run, and no canonical knowledge was changed. This check does not establish how later curation would classify the example.
