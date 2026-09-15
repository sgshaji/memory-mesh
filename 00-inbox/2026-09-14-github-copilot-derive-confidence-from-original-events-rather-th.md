---
type: candidate
title: Derive confidence from original events rather than repeatedly demoting a projection
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T22:45:49+05:30"
domains: [unclassified]
trust: first-party
sensitivity: checked
content_hash: 5ce71ff3d22731b1
---

## Observations
- [procedure] Recompute confidence from deduplicated immutable outcomes; use the prior confidence only for comparison rather than as a new vote or another decrement.
- [reason] A stored confidence value is a projection of the same reports, not an independent observation.
- [evidence] A focused regression passed when four reported successes and one behaviour-change failure yielded medium confidence both with an earlier high projection and on replay with the resulting medium projection.
