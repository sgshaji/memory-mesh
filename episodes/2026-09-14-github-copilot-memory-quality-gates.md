---
type: episode
tool: github-copilot
domains: [unclassified, coding-agents]
captured: "2026-09-14T12:48:42+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: memory-quality-gates

## Goal
Explain how persisted memory is filtered and assess the concern that blind conversation capture produces junk.

## What happened
Inspected capture, host hooks, claim extraction, promotion, and confidence rules. Hooks create episode stubs rather than copying full conversations. Structured admission checks labels and shape; curation and promotion are separate stages.

A no-write Python check rejected a record without an actionable label but allowed correctly labeled chatter to reach a mocked candidate writer. Nonempty plain-text chatter also reached that boundary. No example chatter was persisted and no curator was run.

## Decisions
Recommend learning from the task's supported outcome and relevant corrections, not individual messages. A new follow-up task, polite acknowledgement, or repeated retelling must not count as independent confirmation.

Propose explicit usefulness, evidence, scope, novelty, contradiction, and privacy gates before durable learning. Keep unresolved work separate from reliable knowledge and allow zero lessons. These are design recommendations, not implemented changes or approved V2 contract revisions.

## Problems
Schema-valid evidence text does not establish that an outcome happened. Distinct episode references alone do not establish independent observations. No current mechanism was demonstrated that reliably interprets conversational follow-ups as semantic quality evidence.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
None. The recalled document-validation notes were not exercised in their documented tool scenarios.

## Candidate learnings
- [[00-inbox/2026-09-14-github-copilot-schema-valid-learning-can-still-be-chatter]]: reproducible admission-boundary limitation; candidate only.
