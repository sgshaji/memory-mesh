---
type: candidate
title: Column-free PD/AD skill ZIP built from workspace variant
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T09:34:04+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 7526969e905ffc0a
project: pd-ad-conversion
---

## Observations
- [procedure] Package the workspace SKILL.md at archive root and scripts/pd_tools.py under scripts/ when deploying the column-free variant.
- [behaviour] This package contains no IsGenerated, generatedColumnName, or generated-output-column contract; invocation selection remains the orchestrating flow responsibility.
- [outcome] Created pd-ad-conversion-no-isgenerated.zip with exactly SKILL.md and scripts/pd_tools.py.
- [evidence] Archive entry hashes match the source files, the packaged helper --help command passed, and ZIP SHA-256 is C9F4FC56D0C7E212A751A030A87D5FACB7CF870D62DB151737709AFF1E8736B3.
