---
type: candidate
title: Use column-free PD/AD package when SharePoint schema cannot change
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T09:42:43+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: e785034667ee7619
project: pd-ad-conversion
---

## Observations
- [procedure] Deploy pd-ad-conversion-no-isgenerated.zip, not pd-ad-conversion (3).zip, for customers who cannot add custom SharePoint columns.
- [behaviour] Version (3) includes deployment configuration, references, and helper validation for generatedColumnName IsGenerated, so its preflight intentionally fails when that column is absent.
- [limitation] The column-free package delegates prevention of generated-output reprocessing to the orchestrating Power Automate flow.
- [outcome] Both packaged Python helpers passed syntax compilation and startup; version (3) also validated its configuration and returned IsGenerated as a required binding.
- [evidence] The column-free ZIP has zero generated-column contract matches; version (3) has matches in config, SKILL instructions, references, and pd_tools.py.
