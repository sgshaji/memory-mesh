---
type: candidate
title: Copilot Memory is user-enabled but separates repository facts from personal preferences
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T00:32:50+05:30"
domains: [coding-agents]
trust: third-party
sensitivity: checked
content_hash: bd16ae15d9b99132
---

## Observations
- [behaviour] GitHub documents Copilot Memory as enabled per user rather than per repository. Supported interactions can reuse repository facts within the same repository and that user's preferences across repositories, subject to feature, policy, and billing-entity boundaries.
- [procedure] Use native Copilot Memory as a baseline when evaluating a custom cross-session memory system. Keep its account-level memory capability distinct from installing arbitrary skill bundles globally in cloud sessions.
- [limitation] Tool-native memory remains convenience state rather than canonical evidence in Memory Mesh; documented product behavior was checked, not account enablement or runtime transfer.
- [evidence] Source: https://docs.github.com/en/copilot/concepts/agents/copilot-memory, checked September 2026. It documents cloud agent, code review, and CLI support, with code review restricted to repository facts.
