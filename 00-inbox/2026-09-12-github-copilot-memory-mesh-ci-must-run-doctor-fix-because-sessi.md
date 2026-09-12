---
type: candidate
title: Memory Mesh CI must run doctor --fix because session-state is gitignored
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T23:27:21+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 34715e3aeff885d0
---

## Observations
- [scenario] Adding a GitHub Actions workflow that validates a freshly cloned Memory Mesh vault.
- [behaviour] memory doctor exits 1 on a fresh clone, reporting missing directory _meta/session-state/, because that scaffold directory is gitignored and therefore absent from any checkout.
- [fix] Use memory doctor --fix in CI to scaffold the gitignored directories first, then memory lint for the read-only schema and index validation.
- [evidence] git clone of the repository into a temp dir reproduced doctor rc=1; doctor --fix created _meta/session-state/ and returned rc=0, and lint plus 137 tests then passed.
