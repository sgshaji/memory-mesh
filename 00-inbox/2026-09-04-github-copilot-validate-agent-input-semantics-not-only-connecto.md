---
type: candidate
title: "Validate agent input semantics, not only connector wiring"
source: "automatic capture via github-copilot, 2026-09-04"
captured: "2026-09-04T15:08:42+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: d02ca7b38985c658
project: file-iterator
---

## Observations
- [scenario] A generated Power Automate harness invokes an existing agent whose skill contract requires one source file path per invocation.
- [behaviour] The harness validator passed because it checked that body/agentId and body/prompt existed, while the prompt supplied a position-folder path where the agent contract requires a source file path.
- [procedure] Parse or construct the agent prompt in validation and assert required inputs have the contractually correct granularity and shape.
- [fix] Add a contract test that selects one concrete source file per invocation and rejects folder-valued sourcePath inputs.
- [evidence] All local harness checks passed with zero warnings, yet the generated flow iterates position folders and sends positionFolderPath as sourcePath while the packaged skill states one source PD per invocation.
