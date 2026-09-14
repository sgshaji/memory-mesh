---
type: candidate
title: PD/AD skill now owns SharePoint persistence
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T08:59:44+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: d6c644d8c4c00d5e
project: pd-ad-conversion
---

## Observations
- [behaviour] The current PD/AD conversion skill persists verified DOCX outputs beside the source in SharePoint instead of returning files to an external workflow for storage.
- [procedure] Resolve the source parent, verify SharePoint capabilities, archive an existing destination, upload with create_file, then compare stored and local byte counts before reporting success.
- [outcome] The current SKILL.md is 490 lines versus 414 in the archived baseline, with 97 additions and 21 deletions concentrated in persistence orchestration.
- [evidence] The archived and current pd_tools.py SHA-256 hashes are identical, so this version changes skill instructions and orchestration boundaries rather than helper implementation.
