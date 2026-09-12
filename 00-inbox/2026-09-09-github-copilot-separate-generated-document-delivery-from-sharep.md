---
type: candidate
title: Separate generated-document delivery from SharePoint persistence
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T19:53:48+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: adc8254ea7a3d5a9
project: pd-ad-conversion
---

## Observations
- [scenario] A document-generation agent is invoked by a deterministic workflow that owns downstream SharePoint storage.
- [procedure] Keep template inspection, source mapping, fill, prune, and package verification in the skill, then return the verified DOCX artifact without invoking SharePoint operations.
- [fix] Remove destination derivation, archive handling, create_file upload, stored-byte checks, and upload-oriented reporting from the agent instructions while preserving byte-faithful staging and final package validation.
- [outcome] The pd-ad-conversion skill now treats inputs as immutable, writes final DOCX artifacts to the configured output directory, validates them after pruning, and explicitly delegates transport to the invoking workflow.
