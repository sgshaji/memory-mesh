---
type: candidate
title: PD/AD skill modularized with deterministic safety contracts
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T10:26:59+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: c5b69b7c4c87129b
project: pd-ad-conversion
---

## Observations
- [fix] Reduced the main PD/AD SKILL.md from 500 lines and 3,592 words to 182 lines and 968 words by moving phase-specific detail into template-processing, SharePoint-persistence, and output-contract references.
- [procedure] Keep critical invariants in the main skill, load phase references only when needed, and validate final report structure deterministically with pd_tools.py.
- [behaviour] The optimized contract requires exactly one PD, preserves cyan missing-field markers, forbids custom SharePoint columns, always archives the source, and mandates full rollback after mutation failures.
- [outcome] All 19 tests passed and direct validation of the rebuilt ZIP confirmed its five expected entries and executable helper behavior.
- [evidence] The final package SHA-256 is 888B47CEACF36D23BBC7C83609AECAF2C7D76A35C46E449D223C6EB097223F9E.
