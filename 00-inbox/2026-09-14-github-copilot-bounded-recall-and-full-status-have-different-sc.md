---
type: candidate
title: Bounded recall and full status have different scaling costs
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T23:38:05+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 4e1b1a88c3115c48
project: memory-mesh-feedback
---

## Observations
- [scenario] A pre-integration Memory Mesh 0.1.0 checkout after 2b47c21 was measured on Windows with Python 3.13.15 using synthetic vaults and three-run medians.
- [evidence] At 100, 1000 and 10000 knowledge notes, recall returned five notes and 1118 estimated note tokens. The 10000-note recall median was 0.1905 seconds; full status was 12.6051 seconds with 1000 synthetic episodes.
- [procedure] Measure bounded recall separately from full-vault status, and reuse inventories instead of adding repeated metadata scans when integrating analytics.
- [limitation] These are local synthetic pre-integration measurements, not general performance guarantees or final feedback-loop benchmarks.
