---
type: project
title: Memory Mesh V2 experimental implementation
domains: [coding-agents, agent-skills]
---

# Experimental personal-pilot implementation

This is an implemented, opt-in local workflow, not a production launch or a
demonstration of 10x benefit. The current host capability grade is **assisted**.
Task context and condition labels are caller-declared. The execution adapter
observes explicitly requested Python unittest runs; it does not observe every
host interaction or certify that a natural-language explanation is correct.

## Architecture and authority

| Responsibility | Implementation |
|---|---|
| Shared vocabulary and task ledger | `experience_types.py`, `experience_store.py`, `experience.py` |
| Admission policy and proposal lifecycle | `learning_admission.py`, `learning_flow.py` |
| Human-reviewed publication | `curator/v2.py`, existing review-file machinery |
| Execution evidence | `task_execution.py`, `execution_evidence.py`, `_execution_runner.py`, `attestations.py` |
| Task-bound recall and host handoff | `conditional_recall.py`, `host_lifecycle.py`, existing recall/hooks |
| Public commands and offline evaluation | `v2_cli.py`, `reuse_evaluation.py` |

These files live under [memory_mesh](../../memory_mesh). The core remains
stdlib-only. There is no vector store, background model loop, or hosted service.

- Agent proposals cannot provide evidence-origin or semantic-approval fields.
- A real execution receipt is required before a technical lesson reaches review.
- Only an explicit human choice on a generated review action line authorizes
  admission. Quoted text and conflicting checkbox selections do not approve it.
- Candidates, directly written inbox files, and legacy episode mining cannot
  bypass strict-mode promotion checks.
- Canonical notes are written by the curator. Initial confidence is low;
  successful/fast runs and reported helpfulness do not inflate it.
- Recall checks the approved scope, declared conditions, observed runtime
  version, current evidence, and holds. It reconstructs the brief from reviewed
  data, not arbitrary extra text appended to a note.

Checksums and local file ownership protect application data boundaries, not a
malicious local administrator who can rewrite the implementation and all files.
The validation worker is **not a sandbox**: run only project tests you authorize.
It discards test stdout/stderr, uses a fresh bytecode view, and rejects discovery
that resolves outside the selected workspace.

## Safe first demonstration

From the repository, using the selected Python environment:

```powershell
python -m unittest discover -s tests -p "test_v2_cli_workflow.py" -v
python -m memory_mesh.cli v2 capabilities
```

The test creates and removes isolated synthetic vaults and workspaces. Its
approvals and results are fixtures, not evidence of product performance.

## Live workflow

Use an **existing configured private vault**, selected explicitly with `--root`
or `MEMORY_MESH_ROOT`. No command below moves the existing vault. Directory
scaffolding alone does not create the canonical domain router.

The following data is illustrative: replace the runtime, purposes, conditions,
and paths with the real task. Do not record invented outcomes to follow a demo.

### 1. Opt in and declare a task

```powershell
$vault = "C:\MemoryMesh\private-vault"
python -m memory_mesh.cli --root $vault v2 profile shadow
```

Create a task JSON file with exactly these fields:

```json
{
  "task_id": "task-a",
  "event_id": "start-a",
  "project": "project-a",
  "tool": "python",
  "version": "3.13.15",
  "goal": "Validate this repo using the declared Python runtime",
  "checks": {"runtime": "The declared runtime executes the intended checks."},
  "facts": ["runtime-version-declared"]
}
```

Identifiers are opaque ASCII IDs, not customer names, tenant identifiers, or
filesystem paths. Leading/trailing whitespace is rejected. Facts are explicit
condition labels, not independently verified environmental assertions.

```powershell
python -m memory_mesh.cli --root $vault v2 task start .\task.json --session session-a
python -m memory_mesh.cli --root $vault v2 task show task-a
```

The optional session mapping lets the existing recall skill use the selected
task. It is disposable convenience state, not evidence or an authorization grant.

### 2. Explicitly execute a declared check

```powershell
python -m memory_mesh.cli --root $vault v2 check task-a --event-id check-a --revision 1 --check-id runtime --workspace "C:\repos\project-a" --start tests --pattern test_runtime.py --artifact "tests\test_runtime.py"
```

This runs the requested validation, not a command retrieved from memory.
Provide all relevant artifact files with repeated `--artifact` options.
The adapter checks artifact identity before and after execution and records
only bounded metadata. Successful runs with no exercised checks, timeouts,
invalid worker metadata, and artifact drift remain unverified. Actual failures
remain failures, including when class setup or subtests also produce skip events.

A replay of the same completed event returns its result without executing
again. A different request with that event ID is an error. An unfinished event
is unknown and is not automatically rerun. Use an explicit new attempt and,
when necessary, a new task revision; do not delete records to force admission.

### 3. Propose the smallest useful lesson

Proposal JSON has exactly the following fields:

```json
{
  "proposal_id": "lesson-a",
  "task_revision": 1,
  "title": "Use the declared runtime for validation",
  "domain": "coding-agents",
  "action": "Run the intended checks with the declared Python runtime.",
  "conditions": ["runtime-version-declared"],
  "evidence_ids": ["check-a"],
  "projects": ["project-a"],
  "limitations": ["Only the recorded checks and runtime were exercised."],
  "rationale": "Avoid validating the wrong runtime.",
  "expected_outcome": "passed"
}
```

`expected_outcome` can also be `failed` for a supported failure lesson. Conditions
must be declared on the source task. Evidence must be current, attributable,
and consistent; older successes cannot hide newer failed checks. Multiple
selected observations must describe one artifact snapshot and runtime.

```powershell
python -m memory_mesh.cli --root $vault v2 propose task-a .\proposal.json
```

Shadow mode previews without saving the proposal. JSON `null` means no lesson.
Missing support returns an explicit deferral, not a candidate.

### 4. Human admission and curator publication

To retain a supported proposal, switch to strict and resubmit:

```powershell
python -m memory_mesh.cli --root $vault v2 profile strict
python -m memory_mesh.cli --root $vault v2 propose task-a .\proposal.json
python -m memory_mesh.cli --root $vault curate --compile-only
```

The last command reports the review file under `_meta/review`. The vault owner
must inspect the wording, actual evidence, limitations, and project scope.
Choose exactly one generated action: `[x] approve` or `[x] hold`.
Do not have an agent mark its own proposal approved.

Run `curate --compile-only` again to apply the review. A stale task revision,
changed proposal, or invalid evidence blocks approval. Only then are a candidate,
a bounded evidence episode, and a curator-owned knowledge note materialized.
Curator commands can create local Git commits; never publish private vault data
as part of the product's source repository.

### 5. Recall in a later permitted task

Create a separate task for the later work. Its project must have been explicitly
included in the reviewed proposal scope; no wildcard scope is accepted.
Use the actual observed runtime version and only conditions that apply.

```powershell
python -m memory_mesh.cli --root $vault v2 task start .\next-task.json --session session-b
python -m memory_mesh.cli --root $vault v2 recall task-b --query "repo runtime"
python -m memory_mesh.cli --root $vault recall "repo runtime" --task-id task-b --json
python -m memory_mesh.cli --root $vault recall "repo runtime" --session session-b --json
```

The JSON contains the bounded context and exact lesson revision for feedback.
Use `v2 recall ... --text` for Markdown. Missing context, unknown conditions,
different scope/runtime, or contested evidence produce abstention, not generic
fallback notes. A minor-version declaration does not generalize one observed
patch to every patch release.

### 6. Record use or a correction

After an actual use, report the note reference and revision returned by recall:

```powershell
python -m memory_mesh.cli --root $vault v2 feedback task-b --event-id use-b --note "<returned-reference>" --lesson-revision "<returned-revision>" --outcome held --reason "The matching check was exercised with this lesson in use." --evidence check-b
```

`held` requires matching execution evidence on the target task. Usage attribution
is still operator-reported, not proof of causal savings. Repeated reports from
one target task do not create independent confirmations or increase confidence.

If a real follow-up reports failure, use `--outcome failed` with its actual reason.
A reported failure can hold future recall without rewriting the original note.
`unclear` and `not-applicable` retain uncertainty rather than manufacturing success.

For source-task corrections or changed requirements:

```powershell
python -m memory_mesh.cli --root $vault v2 task revise task-a .\revision.json
```

Revision JSON requires `event_id`, `expected_revision`, `relation`, and `reason`;
optional `goal` and `facts` update the context. `relation` is `correction` or
`requirement_change`. Corrections hold approved source lessons; changed
requirements do not automatically falsify earlier scoped evidence.

## Operational limits and recovery

| Boundary | Limit / behavior |
|---|---|
| Task record | 256 KiB; 128 logical events, 32 executions, 16 proposals |
| Feedback | At most 64 target-task records per source task; failures retain a safety hold when receipt capacity is exhausted |
| Proposal | 1-4 condition labels; up to 6 evidence IDs and 8 reviewed projects |
| Task context | 1-8 declared checks; up to 8 facts |
| Input JSON | 1 MiB; duplicate fields rejected |
| Execution | Explicit unittest only; timeout at most 300 seconds |
| Artifacts | 1-32 files; 1 MiB each, 8 MiB total |
| Recall | At most 6 notes; complete text/JSON brief at most 2,000 estimated tokens |
| Receipts / recalled note | 16 KiB each |
| Coordination | Cooperating writers on one machine; no distributed/shared-folder transaction claim |

Application task/profile records are under `projects/_memory-mesh-v2/records`.
Execution and approval receipts are under `_meta/review/v2-attestations`.
They are authoritative Markdown records, not disposable telemetry. Session
handoffs and lock files under `_meta/session-state` are disposable.

```powershell
python -m memory_mesh.cli --root $vault v2 profile off
```

Off disables recall/capture without deleting data or returning to legacy
behavior. Generic packs are disabled in all V2 modes. Do not delete the profile
to disable V2; records without their profile fail closed. Do not point an older
binary at a V2-enriched vault: restore a separate compatible backup instead.
Already injected context, Git history, and downloaded copies cannot be erased
by a recall hold.

## Evaluation and release gates

```powershell
python -m memory_mesh.cli v2 evaluate .\runs.json
```

Input is a list of run objects with `case_id`, `family`, `trial_id`, `arm`
(`native`, `v1`, `v2`), `accepted`, `active_ms`, `model_cost`, `memory_cost`,
`review_seconds`, `currency`, and `cost_source`. Missing measurements are
explicit JSON `null`; optional `critical_failure` also defaults to unknown.
Money requires a currency and provenance. Duplicate rows and incompatible
currencies are rejected. Reports are observational and do not assign lesson
credit, certify a controlled experiment, or claim 10x improvement.

Before production release, the product owner must still approve and execute:

- A consenting pilot cohort, task/check definitions, experiment budget, and
  the initiative's comparative protocol; include no-match tasks and all overhead.
- Host qualification beyond the current assisted grade.
- A measured capacity envelope and sustained review-workload assessment.
- Core distribution licensing, bundled-skill attribution, and package/data review.
- Retention, backup/restore, support ownership, and incident procedures.
- Separate approval for team exchange, executable procedure promotion, or hosting.

No paid model experiment, customer research, automatic migration, team exchange,
or hosted deployment is performed by this implementation.
