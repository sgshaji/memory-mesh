---
type: episode
tool: github-copilot
domains: [unclassified, coding-agents]
captured: "2026-09-14T13:53:35+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: admission-design

## Goal
Share an engineering approach for selective, conversation-aware learning before any implementation or project-document edits.

## What happened
Checked lifecycle hooks, episode scaffolding, filesystem helpers, frozen operation budgets, and the draft capability map. Used the earlier no-write admission finding as implementation context. Outlined 20 acceptance scenarios covering useful captures, noise, evidence attribution, task revisions, late corrections, privacy, bypass paths, budgets, and recovery. These are proposed tests, not executed results.

## Decisions
Recommend bounded task snapshots, explicit evidence origins, atomic scoped lesson proposals, deterministic boundary checks, and selective semantic review. Separate user intent, observed technical results, and agent hypotheses. A supported failure can be useful while the overall task remains open.

Use task revisions and stable source-event identity rather than message counts or episode filenames. Check revision freshness at persistence so a late proposal cannot override a newer correction. Preserve curator ownership; apply admission before automatic capture and again at promotion boundaries, with current applicability checked at recall.

Keep the four draft pilot modules. Qualify host evidence access first, then prove one vertical slice in shadow mode before guarded automatic capture. Retain V1 defaults and require approval for strict V2 schemas or budget changes. Avoid per-message model calls, full transcript copies, and a new hidden storage canon.

## Problems
Semantic usefulness remains a calibrated judgment, not something schema validation proves. Lifecycle hooks alone do not establish complete task/result observability. Atomic file replacement is not a complete concurrency protocol. Missing evidence, ambiguous follow-ups, and exhausted budgets must remain explicit.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
None. Recalled document-validation notes were not exercised in their documented scenarios.

## Candidate learnings
None. This turn produced an unimplemented design; the earlier admission limitation already has a candidate.
