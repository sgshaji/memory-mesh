---
type: candidate
title: OneDrive read-only worktree metadata can block Git cleanup
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T11:07:43+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 9d4f98b3ad4d244c
---

## Observations
- [behaviour] In a Windows OneDrive-backed repository, git worktree remove deleted an isolated checkout but reported permission denied deleting its remaining metadata. The abandoned metadata directories had read-only attributes; git worktree prune repeated the failure.
- [procedure] Confirm the checkout is gone, its gitdir registration is absent, and only that task's abandoned metadata is eligible for pruning. Clear the read-only attribute on those inspected metadata directories only, then retry native git worktree prune. Do not reset the repository or alter unrelated worktree metadata.
- [evidence] During branch reconciliation in September 2026, attribute inspection identified read-only directories under the abandoned worktree registration. Clearing those flags allowed native Git pruning to remove the remnant; the main checkout and its commit remained unchanged.
