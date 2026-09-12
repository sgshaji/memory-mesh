---
type: candidate
title: GitHub Copilot harness workflow agent nodes do not expose created-file bytes
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T21:05:41+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: 32f15471fc7e5c4b
project: pd-ad-conversion
---

## Observations
- [behaviour] A GitHub Copilot harness agent can create a file card in its conversation response.
- [limitation] The Copilot Studio workflow Agent node documents only text, structured, and custom structured downstream outputs; it does not expose created-file content as a workflow token.
- [reason] A path such as /app/created/file.docx belongs to the agent runtime and is not SharePoint Create file content.
- [procedure] For deterministic downstream upload, generate or materialize the document in a flow action that returns content bytes, or perform persistence through a connector/tool inside the agent run and return a durable identifier.
- [evidence] Microsoft Learn created-files documentation describes conversation file cards, while Agent node workflow documentation lists only text and structured output shapes.
