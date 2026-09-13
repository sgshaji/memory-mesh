---
type: candidate
title: Package Copilot Studio skills with runtime artifacts only
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T12:06:55+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: 7c40c24c5f59b512
project: pd-ad-conversion
---

## Observations
- [procedure] Place SKILL.md at the ZIP root and include only runtime config, references, and supported scripts; exclude tests, caches, and agent-level instructions.
- [reason] Agent instructions should contain routing and security boundaries while task-specific workflow remains in the progressively disclosed skill.
- [limitation] Uploaded skills require a Copilot Studio agent using the GitHub Copilot harness, and live connector behavior still needs Preview testing in a configured environment.
- [evidence] A seven-file 34,873-byte package extracted successfully, kept SKILL.md under 20,000 characters, validated its configuration, and compiled its Python script.
