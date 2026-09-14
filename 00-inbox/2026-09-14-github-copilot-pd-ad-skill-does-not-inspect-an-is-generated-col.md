---
type: candidate
title: PD/AD skill does not inspect an Is Generated column
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T09:28:01+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: b7484f5b89b3d2cd
project: pd-ad-conversion
---

## Observations
- [behaviour] The current PD/AD conversion skill does not read or write a SharePoint Is Generated metadata column.
- [procedure] The Power Automate trigger must exclude generated outputs itself if an Is Generated flag is the intended loop-prevention mechanism.
- [limitation] The skill validates field matching, DOCX package integrity, and uploaded byte counts, but these checks do not classify a SharePoint item as generated.
- [evidence] SKILL.md contains no Is Generated check, and pd_tools.py explicitly documents source classification without a marker column.
