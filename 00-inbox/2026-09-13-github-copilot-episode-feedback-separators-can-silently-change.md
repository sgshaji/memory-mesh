---
type: candidate
title: Episode feedback separators can silently change outcome parsing
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T11:02:18+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: fdf0079ff3ff3626
---

## Observations
- [behaviour] In Memory Mesh 0.1.0, a Knowledge used entry with an outcome followed by a colon can be parsed as unclear with the outcome embedded in its reason. Outcome-first backtick entries can be ignored entirely.
- [fix] Normalize explicitly stated historical feedback to the documented wikilink, outcome, and dash-separated reason grammar. Preserve the original assertion and metadata; do not invent a knowledge reference for unkeyed narrative.
- [evidence] The branch audit identified and normalized 43 such outcome lines in 30 summarized episodes. The unchanged episode parser then recovered 22 held, 20 not-applicable, and one unclear outcome. Full tests and vault lint passed; no curation or confidence promotion was run.
