---
type: candidate
title: V3 feature-parity PD/AD package without generated columns
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T11:09:56+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 1fb0203e1c637973
project: pd-ad-conversion
---

## Observations
- [fix] Rebuilt the column-free PD/AD package from version 3 rather than the simpler legacy branch, preserving its deployment configuration, extraction, deterministic planning, collision checks, semantic upload bindings, rollback, and validate-run contracts.
- [behaviour] Schema and contract version 2 remove generatedColumnName and markedGenerated while retaining the configured AD folder and independent PD/AD archive histories.
- [behaviour] Null source values preserve cyan-highlighted template placeholders; exactly one PD remains required; the source PD is archived; full rollback remains mandatory.
- [outcome] All 39 tests passed, package entries and all 11 helper commands match version 3, and the packaged config and plan commands execute successfully.
- [evidence] The feature-parity ZIP SHA-256 is 306FC77B5BD61B41A12010D0102435FF75991D458D4EE0E14B4DDCBC4B3CD9E0.
