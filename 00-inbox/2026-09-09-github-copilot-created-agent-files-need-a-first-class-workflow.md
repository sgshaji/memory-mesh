---
type: candidate
title: Created agent files need a first-class workflow handoff
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T21:38:11+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: c435947f4c47c428
project: pd-ad-conversion
---

## Observations
- [scenario] A GitHub Copilot harness agent generates a binary document that a later deterministic workflow step must persist or process.
- [limitation] Created-file cards are downloadable in the conversation UI, but the workflow Agent node does not expose the attachment object or content bytes as downstream dynamic content.
- [reason] This forces makers either to perform deterministic persistence inside the reasoning agent or to host external document-generation infrastructure, creating avoidable architecture, governance, and cost tradeoffs.
- [workaround] For now, upload from the agent sandbox through a native path-aware connector and return a durable item ID or URL; never pass base64 through the model.
- [fix] A broader platform fix should expose agent-created files as typed workflow outputs containing filename, content or a secure durable handle, size, and checksum so deterministic steps can consume them without another LLM turn.
- [outcome] The PD conversion design currently keeps SharePoint upload inside the agent because no customer-hosted service is desired and downstream workflow steps cannot consume the created-file card.
- [evidence] Microsoft documentation lists workflow Agent-node outputs as text or structured values, while created files are documented as conversation file cards.
