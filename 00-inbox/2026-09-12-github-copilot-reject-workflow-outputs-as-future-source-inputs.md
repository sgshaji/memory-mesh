---
type: candidate
title: Reject workflow outputs as future source inputs by location
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T12:20:30+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 6520068438328304
project: pd-ad-conversion
---

## Observations
- [scenario] A conversion trace supplied an archived advertisement document as the source while its generated flag was false.
- [behaviour] Metadata alone made the source look eligible and the planner derived a nested history destination.
- [fix] Validate source location against configured output and archive folder names before any browsing, staging, or model reasoning.
- [procedure] Resolve connector paths to exact identifiers and choose a byte-faithful content action on the first attempt; never probe text content or place a path in an id field.
- [evidence] The packaged planner now returns invalid-source-location for the traced folder shape and all 24 regressions pass.
