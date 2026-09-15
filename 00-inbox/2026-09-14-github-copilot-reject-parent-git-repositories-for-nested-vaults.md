---
type: candidate
title: Reject parent Git repositories for nested vaults
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T23:03:41+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 5b189d33c9ed40d6
project: memory-mesh
---

## Observations
- [scenario] A local vault directory can be nested inside an unrelated Git working tree without owning any Git metadata.
- [behaviour] Git invoked with -C still discovers an ancestor repository, so is-inside-work-tree alone does not prove vault ownership.
- [procedure] Compare the resolved git rev-parse --show-toplevel path with the vault root before inspecting or committing; otherwise report manual commit required.
- [evidence] The isolated nested-vault regression test returned Git unavailable and preserved the parent repository HEAD after an attempted commit.
