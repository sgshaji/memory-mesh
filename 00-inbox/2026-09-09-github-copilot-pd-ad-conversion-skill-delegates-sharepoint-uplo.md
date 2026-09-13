---
type: candidate
title: PD/AD conversion skill delegates SharePoint upload to create_file connector
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T19:42:46+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: bcafdafd9b3ecdc1
project: pd-ad-conversion
---

## Observations
- [behaviour] The pd-ad-conversion skill instructs the host to archive displaced documents, upload each generated DOCX with create_file, and verify the stored byte count before reporting success.
- [limitation] scripts/pd_tools.py creates, validates, and reports on documents but does not call SharePoint itself; successful upload requires a host-provided create_file connector that can read the configured writable directory.
- [procedure] Pass the absolute upload_path returned by fill as create_file body, then read the stored SharePoint size and run both verify and report.
- [evidence] SKILL.md sections 7a through 10 define copy-first, upload-second, verify, and delete-last behavior, while pd_tools.py returns upload_path and evaluates byte counts.
