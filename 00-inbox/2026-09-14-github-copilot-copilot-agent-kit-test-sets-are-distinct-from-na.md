---
type: candidate
title: Copilot Agent Kit test sets are distinct from native Copilot Studio evaluations
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T23:20:02+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: e1ac88f07e885ec7
---

## Observations
- [evidence] Official Copilot Agent Kit guidance describes Agent Test Set and Agent Test records stored in Dataverse, while the official testing-capabilities document describes the Kit runner using Direct Line and optional AI Builder enrichment. Sources consulted 2026-09-14: https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-configure-tests and https://github.com/microsoft/Power-CAT-Copilot-Studio-Kit/blob/main/TESTING_CAPABILITIES.md
- [procedure] Treat a Kit Dataverse ingestion adapter and a native Copilot Studio Evaluation import adapter as separate backends; bind each test-set identifier to the backend that owns it and run it only with that backend's execution path.
- [limitation] Successful creation of Kit records does not demonstrate appearance in the native Evaluation page or successful execution. Verify Kit installation, permissions, flow connections, agent authentication, and test-type mappings separately.
- [procedure] Preserve dataset provenance and validate remote case counts after import; use idempotent creation and report partial uploads rather than equating an HTTP create response with a complete evaluation.
