---
type: candidate
title: Provision Copilot cloud skills separately from local user skills
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T00:14:53+05:30"
domains: [agent-skills]
trust: mixed
sensitivity: checked
content_hash: 2e05178c5667bde7
---

## Observations
- [scenario] A skill collection can be discoverable in a local Copilot user profile while remaining absent from a repository's cloud-agent environment.
- [procedure] For cloud use, provision skills as project skills in a supported repository skill directory and include their referenced resources. Do not infer cloud availability from a successful local global install.
- [evidence] GitHub's Adding agent skills documentation explicitly supports Copilot cloud agent and distinguishes repository project skills from personal skills in the local home directory: https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills (checked September 2026).
- [evidence] The inspected cloud setup workflow installed Python and the project package but did not provision the externally installed skill collection. No cloud skill invocation was tested during this check.
