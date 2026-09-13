---
type: episode
tool: github-copilot
domains: [coding-agents, agent-skills, document-processing]
captured: "2026-09-09T19:18:46+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 872f3e61-0ffd-4994-b791-fc2196fe7722
---

# Session: copilot-session

## Goal

Review a user-replaced document-processing skill against the previously agreed reuse criteria and earlier findings, without editing it.

## What happened

Compared the replacement with the verified prior release. Existing validation passed: 181 unit/component tests and 95 selftest checks, also repeated without site packages. Ran 37 focused synthetic probes and an old/new diagnostic comparison. The original 48 files and the tested copy retained their captured hashes. Produced a persistent follow-up report with closed, partial and open findings.

## Decisions

Keep approval outside the skill as agreed. Distinguish passing built-in tests from closure of review findings. Preserve separate classifications for real regressions, known compatibility defects, documented operational mitigations and intentional localization limitations. Recommend focused non-sensitive tenant testing, not general production sign-off.

## Problems

Raw semantic diagnostics reintroduced a private-input path through unknown configuration keys. Several earlier representation, metadata discovery, preservation and path/delivery issues remained. The new input preflight is useful but is not a complete execution or layout preview. No live tenant, Word renderer or external skill validator was exercised.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] - held - for deterministic rejection of invalid and unresolved inputs. Diagnostic privacy must be validated independently of rejection correctness.

## Candidate learnings

- [[00-inbox/2026-09-09-github-copilot-unknown-configuration-keys-can-leak-private-inpu]] records the verified unknown-key diagnostic privacy pattern; it is a candidate, not canonical knowledge.
