---
type: candidate
title: External approval does not replace deterministic execution input checks
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T18:02:49+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: e38b2d26339ad671
---

## Observations
- [scenario] A reusable file-transformation skill delegates business approval entirely to its calling agent or workflow.
- [procedure] Remove approval artifacts and identity gates from the transformer, but retain schema validation, snapshot-to-manifest consistency, plan/value binding, independent output verification and single-execution controls.
- [evidence] Synthetic regression tests executed valid supplied values without an approval record, accepted updated valid values before execution, rejected a rewritten manifest even with a rebound plan, and blocked stale plans.
- [limitation] Mechanical validation is not evidence of business authorization; any required identity and approval controls must be enforced by the caller.
