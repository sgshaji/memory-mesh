---
type: candidate
title: Lime Green ingestion needs main-content boundaries and explicit FAQ pairs
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T20:28:48+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: 210c894fe34cd1d4
---

## Observations
- [procedure] For the inspected Lime Green product pages, scope text and heading metadata to the main product content, excluding navigation, related cards, colour swatches and download calls to action. Extract FAQ dt/dd pairs and preserve the question as the citation title.
- [evidence] Live inspection on 2026-09-12 of https://www.lime-green.co.uk/products/lime-render/duro found numerous unrelated product h1 headings in navigation before the actual main article. https://www.lime-green.co.uk/support/faq contained 32 dt/dd questions in six FAQ sections; several section labels use p.h2-style rather than heading elements.
- [limitation] These selectors and counts describe the observed site version, not a guaranteed stable interface. Recheck DOM boundaries after site changes.
