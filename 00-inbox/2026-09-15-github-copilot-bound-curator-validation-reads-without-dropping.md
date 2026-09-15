---
type: candidate
title: Bound curator validation reads without dropping final conflict checks
source: "automatic capture via github-copilot, 2026-09-15"
captured: "2026-09-15T01:02:06+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: cbf05aefadbe92df
project: memory-mesh
---

## Observations
- [scenario] An immediate-write curator transaction reread its entire input snapshot before every file mutation.
- [procedure] Validate all registered inputs before the first mutation and at publication or successful exit, while retaining exact target checks for intermediate writes and complete guarded rollback.
- [evidence] On a 10000-file fixture with eight writes, input-content reads fell from 100016 to 30024; isolated elapsed time fell from 124.651 seconds to 36.424 and 36.802 seconds in two confirmation runs.
- [limitation] Writes remain provisional and visible before the final barrier. Non-target input drift may be found later; readers needing a consistent multi-file view must participate in the curator lock.
- [outcome] Focused tests rejected deferred source conflicts before Git staging and restored the complete run, while record and immutable-receipt crash recovery preserved later competing updates.
