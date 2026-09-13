---
type: candidate
title: Prefer native scoped skill installation over full cross-host packs
source: "automatic capture via github-copilot, 2026-09-08"
captured: "2026-09-08T23:07:44+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: cef6616432fa2fcd
project: addyosmani/agent-skills assessment
---

## Observations
- [procedure] For GitHub Copilot, install reviewed skills into a native skills directory or with the first-party skill manager, pinning a release or commit.
- [limitation] Cross-host skill repositories may include commands and personas that are not portable even when their SKILL.md files are compatible.
- [evidence] The assessed repository uses standard SKILL.md files supported by Copilot, while its short lifecycle commands reside under Claude-specific command directories and its continuous tests do not exercise Copilot.
- [outcome] A selective 3-5 skill repository-scoped pilot was preferred over installing the complete pack globally.
