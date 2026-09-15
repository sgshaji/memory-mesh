---
type: episode
tool: github-copilot
domains: [unclassified, copilot-studio]
captured: "2026-09-14T22:29:08+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: d99007a5-2933-4cd6-9e73-dee1da060af2
---

# Session: copilot-session

## Goal
Verify whether a generated evaluation dataset becomes a native Copilot Studio test set or requires a separate import.

## What happened
Read the evaluation workflow, output contract, and publication destination. Compared the custom CSV contract with current Microsoft Learn native single-response import guidance. Distinguished browser-driven chat execution from native test-set registration and document-library archival.

## Decisions
Kept the review read-only. Explain that existing browser execution does not require native import, whereas persistence in the native Evaluation feature needs a separate conversion and import step. Qualify the documented import route as Standard-harness guidance.

## Problems
The reviewed workflow did not provide native import/register/run operations. Its CSV uses a custom multi-column contract rather than the documented native Question and Expected response columns. Native evaluation methods, thresholds, expected capabilities, and connection identity require explicit configuration; custom rubric equivalence must not be assumed. No live import was attempted.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]

## Knowledge used
No recalled note was independently exercised in this follow-up; conclusions came from local source inspection and official import documentation.

## Candidate learnings
- [[00-inbox/2026-09-14-github-copilot-native-copilot-studio-evaluation-import-requires]] - documentation-grounded import contract and harness limitation, captured as an unvalidated candidate.
