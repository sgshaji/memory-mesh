---
type: candidate
title: Global agent-skills installation needs shared reference preservation
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T17:16:10+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: 5ac7f5e82fa17cdc
---

## Observations
- [scenario] Installed all 25 addyosmani/agent-skills skills on Windows for GitHub Copilot with skills CLI 1.5.23, using --global --agent github-copilot --skill '*' --yes.
- [behaviour] The installer placed 30 skill files under the shared user directory ~/.agents/skills, left existing ~/.copilot/skills untouched, and omitted the seven repository-level references used by ../../references links.
- [workaround] Keep the complete upstream checkout in a user-level source directory and create a non-overwriting directory junction from ~/.agents/references to the checkout's references directory.
- [procedure] Verify the installed files against the checkout, check relative reference targets, and use the installer global list plus the upstream skill validator before reporting success.
- [evidence] The global registry listed all 25 upstream skills for GitHub Copilot. SHA-256 comparison confirmed all 30 installed files matched source commit be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39, and all three existing Memory Mesh skill hashes were unchanged.
