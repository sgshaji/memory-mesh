---
type: candidate
title: Artifact integrity checks do not enforce behavioral evaluation gates
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T22:24:28+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 7916654d4fa6eaa7
---

## Observations
- [scenario] Reviewing an agent evaluation pipeline that validates JSON schemas and artifact hashes before accepting a declared quality decision.
- [evidence] Isolated synthetic fixtures showed that structural validation can accept a declared pass despite a failed critical case, an unexecuted critical case, absent scores, or empty execution-evidence references when semantic consistency is not checked.
- [procedure] Validate applicable per-case scores and execution evidence, recompute critical-case and aggregate gates from the rubric, and reject a declared decision that disagrees with the computed result.
- [procedure] Use contradictory negative fixtures as well as hash-tampering fixtures to verify an evaluation gate; successful manifest validation alone is not proof of behavioral readiness.
