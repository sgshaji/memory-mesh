---
type: episode
tool: github-copilot
domains: [unclassified, copilot-studio, agent-skills]
captured: "2026-09-09T17:28:55+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 872f3e61-0ffd-4994-b791-fc2196fe7722
---

# Session: copilot-session

## Goal

Execute the agreed critical review of a reusable Word-template population skill, without implementing fixes.

## What happened

Reviewed contracts, runtime logic and validation coverage; ran existing tests and synthetic cross-business, Unicode, package-integrity, namespace-preservation and delivery-failure probes. Produced a persistent evidence-backed review in the session artifacts. Verified the original package remained unchanged. No business documents or confidential values were used.

## Decisions

Separate reusable scalar filling from universal Word-template support. Distinguish confirmed defects, trusted-environment assumptions, unfinished platform integration and intentional exclusions. Retain the narrow deterministic core; prioritize trustworthy validation, private diagnostics and authenticated approval before expanding capabilities.

## Problems

Existing tests alone did not establish the broader advertised guarantees. Deep Windows paths failed staging while a short workdir passed the same selftest; an initial diagnostic explanation was corrected after reproducing the underlying I/O error. No target tenant or Word renderer was exercised, so live approval, model behavior and visual fidelity remain unverified.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]

## Knowledge used

- [[validation-order]] - held: ordinary invalid and unresolved inputs were deterministically blocked in synthetic tests. A separate Unicode serialization failure showed that validation must also precede hashing of malformed text.

## Candidate learnings

- [[00-inbox/2026-09-09-github-copilot-tree-equality-alone-misses-ooxml-namespace-decla]]: removing a namespace referenced only through mc:Ignorable was missed by parsed-tree comparison. This is a candidate, not promoted knowledge.
