---
type: candidate
title: Column-free PD/AD package must always archive the source
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T10:03:00+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: e2d8045c3a922d6c
project: pd-ad-conversion
---

## Observations
- [behaviour] The prior column-free skill explicitly left PDF sources untouched, so runs correctly skipped source-PDF archiving despite the intended policy.
- [fix] Require every supplied source PD, PDF or DOCX, to move into the source parent Archive folder before any replacement upload; also archive separate existing PD and AD destinations.
- [procedure] Use one timestamp for the entire conversion, de-duplicate a DOCX source that is also the PD destination, verify every archive move, then upload replacements.
- [outcome] The rebuilt package passed six archive-contract tests covering PDF, DOCX de-duplication, AD placement, instructions, and packaged bytes.
- [evidence] Packaged destination plans now return source_archive_filename Role_20260914-045000.pdf for both PD and AD and keep AD beside the source.
