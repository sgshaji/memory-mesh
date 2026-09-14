---
type: candidate
title: PD/AD skill variants have different IsGenerated contracts
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T09:31:25+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: fb1586050860a7aa
project: pd-ad-conversion
---

## Observations
- [scenario] The deployed PD Conversion Assistant V0.3 matches the Ali-version skill rather than the pd-ad-conversion workspace copy.
- [behaviour] Ali-version requires a configured SharePoint Yes/No generated-output column, while the workspace copy does not use that column.
- [procedure] Identify which packaged skill is deployed before diagnosing preflight behavior; keep SKILL.md, deployment.json, references, flow, and helper from one coherent variant.
- [reason] Ali-version uses the marker to prevent generated PDs from becoming new sources and treats inability to read or set it as a preflight failure.
- [evidence] Ali-version config sets generatedColumnName to IsGenerated and its deployment reference requires reading the source flag and marking verified replacements.
