---
type: candidate
title: PD/AD SKILL.md optimization should resolve three contract gaps first
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T10:10:41+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 3bdb3a6783a8d34d
project: pd-ad-conversion
---

## Observations
- [behaviour] The 500-line skill contains 3,592 words; field mapping, pruning, and persistence account for more than half of the document.
- [limitation] Null fields are described as highlighted for reviewers, but pruning later requires stripping all highlighting.
- [limitation] AD-only conversion is allowed while the source is always archived, which can remove the live PD without creating a PD replacement.
- [limitation] The source and destinations are archived before upload, but no rollback is defined if upload or stored-byte verification fails.
- [procedure] Resolve these behavior contracts first, then reduce the main skill to orchestration and hard invariants while moving phase-specific mapping, pruning, and persistence detail into references.
- [evidence] The helper exposes destination, sources, and report commands that the SKILL.md command table omits, leaving deterministic behavior duplicated in prose.
