---
type: candidate
title: Progressive disclosure and validated bindings improve skill reuse
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T11:59:37+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: ae0d3809c841480c
project: pd-ad-conversion
---

## Observations
- [procedure] Keep mandatory control flow in SKILL.md and move phase-specific template, deployment, and reporting detail into references loaded only when needed.
- [fix] Store environment bindings in one versioned JSON file and validate it deterministically before planning or model reasoning.
- [limitation] Connector parameter mapping can adapt names, but a connector that accepts bytes instead of a dereferenced local path needs a different transport implementation.
- [evidence] The core skill shrank from about 740 to 214 lines while 21 regression tests, compilation, diagnostics, configuration validation, and reference-link checks passed.
