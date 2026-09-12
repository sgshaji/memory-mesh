---
type: candidate
title: Protect reviewer guidance when retaining document variants
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T12:32:41+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: eaabb320baa228ed
project: pd-ad-conversion
---

## Observations
- [scenario] A conversion retained two template variants but removed the instruction telling the reviewer how to choose between them.
- [behaviour] The final schema validated because pruning evidence was syntactically valid even though required operational guidance was removed.
- [fix] Require exact protected paragraphs in the prune specification and reject any removal that matches or spans them.
- [fix] Include not-found removals in the prune failure condition; reporting a missing target while returning success is contradictory.
- [evidence] Protection and missing-target regression tests pass within a 30-test suite, and the rebuilt skill package exposes deterministic DOCX extraction.
