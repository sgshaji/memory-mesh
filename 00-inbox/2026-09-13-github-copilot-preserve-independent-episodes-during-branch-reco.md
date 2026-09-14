---
type: candidate
title: Preserve independent episodes during branch reconciliation
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T11:02:18+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 89bb44a3a0df4b83
---

## Observations
- [behaviour] Two branches can contain unrelated episodes with the same date-and-counter filename. A text merge or choosing the latest file can silently erase a distinct session.
- [procedure] Compare session identity, capture time, and Git blob content. Keep independent records at collision-safe filenames, check references, and verify the disposition of every source blob before recording branch ancestry as integrated.
- [evidence] A Memory Mesh 0.1.0 branch reconciliation preserved eight incoming colliding records across seven filenames. Accounting verified all 139 reviewed record versions, including explicitly reviewed formatting-only corrections, and all original master files remained unchanged.
