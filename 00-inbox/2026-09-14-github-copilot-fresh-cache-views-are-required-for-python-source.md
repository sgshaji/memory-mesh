---
type: candidate
title: Fresh cache views are required for Python source-bound validation
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T21:21:02+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 95dd63990b390a66
---

## Observations
- [scenario] A validation worker checked Python source on Python 3.13.15, Windows ARM64.
- [limitation] Timestamp/size bytecode validation can reuse stale code after an equal-length source edit with the original modification time. Disabling bytecode writes alone does not prevent cached reads.
- [procedure] For source-bound checks, use a fresh private pycache_prefix with -B and compare selected artifact identities before and after execution; do not assume a fresh source hash proves which cached code executed.
- [evidence] The regression compiled a passing temporary test, rewrote it to an equal-length failing assertion, and restored its timestamp. The original worker passed stale code; the fresh-cache worker correctly reported failure.
- [outcome] The focused regression and full 363-test suite passed after the fix, with two existing platform/host skips in the full suite. This establishes the tested cache behavior, not a product savings or capacity claim.
