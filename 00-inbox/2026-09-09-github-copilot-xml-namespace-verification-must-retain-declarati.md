---
type: candidate
title: XML namespace verification must retain declaration scope independently of expanded names
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T17:53:19+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: cd20852395595868
---

## Observations
- [scenario] A document verifier compares parsed XML before and after authorised text edits.
- [behaviour] Expanded-name tree comparison cannot detect deletion or rebinding of otherwise unused namespace declarations referenced only by prefix-valued markup compatibility attributes.
- [procedure] Use namespace parser events to validate prefix and QName references in the element's actual in-scope declarations, and compare original declaration locations independently of text equality.
- [evidence] Synthetic standard-library tests rejected deleted unused declarations, changed namespace URIs, descendant and sibling scope moves, and unbound markup compatibility references; genuine alias/default namespace documents and tab/newline text replacements passed.
