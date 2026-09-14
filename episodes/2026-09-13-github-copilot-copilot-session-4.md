---
type: episode
tool: github-copilot
domains: [coding-agents, unclassified]
captured: "2026-09-13T00:34:10+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: copilot-session

## Goal
Refine enhancements that automatically make subsequent tasks easier, better,
and cheaper for an individual, with controlled team reuse later.

## What happened
Inspected capture, recall, episode finalization, curation, confidence rules,
integration contracts, and feedback tests without changing application code.
Read-only status reported stale context packs. Recall for this task fell back
to generic context, including an unrelated active-project note. Compared the
idea with documented Copilot Memory and Claude Code auto memory.

## Decisions
Prepared a provisional recommendation rather than an approved specification.
Explored task briefs, mistake prevention, verified recipes, cost-aware recall,
team lesson sharing, and cross-host portability. Favor a personal verified
reuse loop first; recipe automation and team distribution follow evidence
of benefit. Measure correctness, rework, and total cost against a consistent
host baseline, including memory overhead. Keep data private and require
reviewed sharing. Do not save an idea document or implement without confirmation.

## Problems
Raw session stubs are not inputs to default curator mining until summarized.
Existing confidence represents whether a claim held, not proof of task-level
savings. Host automation differs between CLI, VS Code, and cloud. Primary
execution host and first repeat-task family remain assumptions to validate.
No performance experiment or account-level cloud-memory test was run.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
None. Recalled notes did not establish the product direction; the recommendation
is based on source inspection and public product documentation.

## Candidate learnings
- Copilot Memory is user-enabled but separates repository facts from personal
  preferences; this is distinct from account-wide skill installation.
- Memory Mesh compile does not finalize raw session stubs.
