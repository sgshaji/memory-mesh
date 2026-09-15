---
type: candidate
title: Normalize equivalent Windows namespaces before containment checks
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T23:58:41+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 4637f48e9fcfc4ca
project: memory-mesh
---

## Observations
- [scenario] Concurrent local file creation on Windows with Python 3.13 exercised resolved path containment.
- [behaviour] Path.resolve returned an extended Win32 path spelling while the vault root used an ordinary drive spelling, causing a false traversal error for an inside-vault file.
- [procedure] Normalize only equivalent DOS-drive and UNC namespace spellings for comparison, preserve the vault root namespace for returned paths, and continue rejecting resolved paths outside that root.
- [evidence] The concurrent recall retry test and deterministic Windows inside/outside namespace regressions passed after the containment repair.
