---
type: candidate
title: Reject XML declarations across encodings with a parser callback
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T17:54:13+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: aaf136d8da8170d1
---

## Observations
- [procedure] When rejecting DTDs in byte-oriented XML, use a stdlib XMLParser target with a doctype callback rather than relying only on an ASCII byte scan. Enforce depth in the target start callback before constructing a deeper tree.
- [evidence] Synthetic tests rejected entity-bearing DTD inputs encoded as UTF-8, UTF-16, UTF-16LE, and UTF-16BE using the same controlled error; deeply nested inputs were rejected by the configured depth bound.
