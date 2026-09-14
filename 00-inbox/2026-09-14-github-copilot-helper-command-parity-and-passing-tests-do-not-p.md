---
type: candidate
title: Helper command parity and passing tests do not prove DOCX edge cases
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T11:52:09+05:30"
domains: [agent-skills]
trust: first-party
sensitivity: checked
content_hash: b1b11d231b53bb12
---

## Observations
- [procedure] When reviewing a document-conversion helper, exercise blank paragraphs and break-only paragraphs as well as token-bearing paragraphs; command-name and archive-layout parity checks are not behavioral equivalence tests.
- [evidence] An existing 39-test suite passed, but an in-memory Word XML fixture with an empty paragraph caused apply_map to raise ValueError because fill_tokens returned an empty list instead of its usual pair.
- [procedure] Separate executed helper code from model-visible Markdown and tool output when estimating context usage; count the union of referenced text loaded during a complete run, not only the main skill.
- [limitation] Loading references by phase delays their context cost but does not remove text already retained in a conversation.
