---
type: candidate
title: Distinguish personal Chat customization from shared cloud-agent customization
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T00:18:39+05:30"
domains: [coding-agents]
trust: third-party
sensitivity: checked
content_hash: 91ac556ff32425ae
---

## Observations
- [behaviour] GitHub's custom-instruction support table lists personal instructions for Copilot Chat, but lists repository-wide, path-specific, agent, and organization instructions for Copilot cloud agent, without personal instructions.
- [procedure] For centralized cloud workflows across multiple organization repositories, evaluate organization-level custom agents or organization instructions. Do not present these as a personal-account-wide skill installation or as covering arbitrary repositories outside that organization.
- [limitation] A custom agent profile is not the same as installing a complete skill bundle with its resources. Adapting workflows and validating the target host remain separate steps.
- [evidence] Verified the published GitHub.com support table at https://docs.github.com/en/copilot/reference/custom-instructions-support and the repository, organization, and enterprise profile scopes at https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-custom-agents in September 2026. This was documentation verification, not a cloud execution test.
