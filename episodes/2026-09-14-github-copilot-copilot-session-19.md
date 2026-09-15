---
type: episode
tool: github-copilot
domains: [agent-skills, coding-agents, unclassified]
captured: "2026-09-14T23:05:58+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: faeca167-1cb9-476e-a9cf-a04e2dc7b0ba
completeness: complete
recall_quality: partial
prefilled:
  knowledge_retrieved: {source: provided-retrievals, evidence: reported}
---

# Session: Local curation consistency

## Goal
Protect local multi-contributor curation, canonical writes, recovery, and Git
ownership without changing canonical vault data.

## What happened
- Implemented designated-curator policy, shared OS locking, immediate journaled
  transactions, optimistic source checks, and guarded rollback.
- Hardened note references, before-read containment, Windows namespace comparison,
  opened-handle hard-link rejection, and exact-path Git commits.
- Git command failures now abort the opted-in transaction and restore canonical
  bytes and pending approved reviews. Missing Git remains explicit local-only mode.
- Added exact bounded-read registration, complete durable publication paths,
  and shared experience locking for V2 publication and rollback.
- Fixed F3 with isolated Git staging: rejected hooks leave working files and
  the real index unchanged; retry succeeds without removing user stages.
- Latest focused suite: 249 tests, 248 passed, one privilege skip. Full discovery:
  734 tests, 731 passed, three Windows privilege skips, zero errors/failures.
- Preserved original, proposed, and conflicting bytes in fixture recovery tests,
  including actual records, both receipt kinds, process death and later writers.
- Earlier 10,000-file/eight-write measurement: content reads decreased from 100,016 to
  30,024; isolated time decreased from 124.651s to 36.424s/36.802s.

## Decisions
- Reused the existing curator lock; did not introduce another lock mechanism.
- Kept full checks before first mutation and publication/exit, plus target-local
  checks between. Reads remain provisional, not snapshot-isolated.
- Kept the run boundary opt-in; low-level legacy writes do not reacquire a lock
  already owned by V2.
- Treated local actor identity as a configuration guard, not authentication.
- Retained conflicts for explicit review and fresh recomputation; never silently
  replayed an outdated decision.

## Problems
- The caller must place RecordStore transactions inside the curator boundary,
  register missing reads too, and include all publishable paths in Git.
- Discarded a 146.761s timing sample contaminated by concurrent tests; isolated
  confirmations agreed. No validation was removed to obtain the improvement.
- Unknown native Git processes must be confirmed stopped before rollback.
  Post-commit index conflicts preserve published files and user staging.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — not-applicable — this run had no LLM stage; deterministic
  filesystem validation was exercised, not the recalled model-behavior claim.

## Skill outcomes


## Candidate learnings
- [[00-inbox/2026-09-14-github-copilot-reject-parent-git-repositories-for-nested-vaults]]
- [[00-inbox/2026-09-14-github-copilot-normalize-equivalent-windows-namespaces-before-c]]
- [[00-inbox/2026-09-15-github-copilot-bound-curator-validation-reads-without-dropping]]
- [[00-inbox/2026-09-15-github-copilot-isolate-git-staging-from-recoverable-curator-wri]]
