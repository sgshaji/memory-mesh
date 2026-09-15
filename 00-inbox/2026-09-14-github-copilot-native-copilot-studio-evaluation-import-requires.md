---
type: candidate
title: Native Copilot Studio evaluation import requires its own CSV contract
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T22:29:08+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: 2037db902b7d1c73
---

## Observations
- [evidence] Microsoft Learn's Create a single response test set documentation, consulted on 2026-09-14, specifies Question and Expected response column headings in that order for CSV import, a maximum of 100 questions per file, and 1000 characters per question. Source: https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-create#create-a-test-set-file-to-import
- [procedure] Convert custom evaluation datasets to the documented native import columns and validate limits before import; configure evaluation methods, pass scores, expected capabilities, and test account connections separately rather than assuming custom rubric fields transfer.
- [limitation] The cited documentation applies to the Standard harness. Verify native evaluation availability separately for other harnesses. Browser-driven chat tests and document-library uploads do not themselves register native test sets.
