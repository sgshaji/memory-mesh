---
type: candidate
title: Explicitly plan both PDF source and a separate existing PD DOCX archive
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T12:43:58+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 3fe82183015c2554
---

## Observations
- [scenario] A conversion accepts a PDF source but writes a same-stem DOCX destination that could already exist.
- [limitation] The current v3-derived deterministic PD plan names only the supplied PDF as its existing file to archive; it does not emit an additional archive entry for a separate existing same-stem DOCX.
- [procedure] When explaining guarantees or extending archive handling, inspect and de-duplicate every displaced destination explicitly rather than treating archive-source as archive-all-destinations.
- [evidence] Calling derive_plan for a synthetic Role.pdf with AD enabled emitted archive candidates Role.pdf and AD Documents/Role - AD.docx, but no Role.docx candidate.
