---
type: candidate
title: Unknown configuration keys can leak private input through validation diagnostics
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T19:13:20+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 6c8b1dd6e3868a75
---

## Observations
- [scenario] A validator accepts a free-form configuration object structurally and later rejects unknown option names semantically.
- [behaviour] Interpolating the unknown option key into a human-readable error can copy arbitrary input text into logs and reports, even when configured numeric bounds and review reasons are hidden.
- [procedure] Export structured rule codes and allowlisted option names; represent unrecognized keys with a controlled label. Include private markers in malformed object keys when testing diagnostic privacy.
- [evidence] A local synthetic comparison found that a generic diagnostic omitted a marker, while a later raw semantic-error diagnostic included the same marker in both preflight output and a blocked-job report. No document was staged in the failing case.
