---
type: candidate
title: Isolate Git staging from recoverable curator writes
source: "automatic capture via github-copilot, 2026-09-15"
captured: "2026-09-15T02:53:19+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 29581b0beb42f24b
project: memory-mesh
---

## Observations
- [scenario] A failed Git hook can leave proposed blobs staged even after a filesystem transaction restores its working files.
- [procedure] Stage curator changes in a private GIT_INDEX_FILE. Reconcile only a successful commit into the real index with Git's index-only two-tree merge, preserving unrelated stages and refusing overlapping user changes.
- [evidence] A real rejecting-hook regression preserved both original working files and real index bytes, then succeeded on retry without deleting user staging.
- [outcome] Tests preserved concurrent user stages, recovered a crash before publication without index leakage, and reconciled a crash after commit without reverting published files.
- [limitation] An uncertain native Git process must be confirmed stopped before rollback. A post-commit index conflict remains explicit and must not trigger destructive index reset or automatic unpublication.
