---
type: candidate
title: "Tree equality alone misses OOXML namespace declarations used by mc:Ignorable"
source: "automatic capture via github-copilot, 2026-09-09"
captured: "2026-09-09T17:23:32+05:30"
domains: [document-processing]
trust: first-party
sensitivity: checked
content_hash: c52513f9c84f6299
---

## Observations
- [scenario] A synthetic WordprocessingML document references a namespace prefix only through the text of an mc:Ignorable attribute.
- [behaviour] Removing that namespace declaration can leave ElementTree tags, attributes and text unchanged, so a tree-only preservation check can accept the altered document.
- [procedure] Supplement parsed-tree comparisons with namespace-scope validation or byte-preservation checks for declarations referenced by QName-valued attributes; include a mutation test that removes a still-referenced declaration.
- [evidence] A local synthetic mutation removed xmlns:w15 while retaining w15 in mc:Ignorable; the tested tree-based preservation verifier returned passed for both package and replacement checks. No claim of Word rendering validation was made.
