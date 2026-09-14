---
type: project
title: Memory Mesh V2 - capability map
domains: [coding-agents, agent-skills]
---

# Capability map: Verified Experience Transfer

Document revision: 0.2, 2026-09-14.
Scope: **experimental personal implementation; later release gates remain separate**.

The local core now follows the five pilot boundaries below. Admission was split
from neutral ledger storage during implementation review. See
[IMPLEMENTATION.md](IMPLEMENTATION.md) for the working interfaces and the
unverified host, benefit, capacity, and launch requirements.

This map decomposes the initiative described in [INITIATIVE.md](INITIATIVE.md).
It belongs under project working documents; it does not amend the
[frozen V1 contracts](../../_meta/spec/principles.md).

## Objective

Turn an observed experience into a conditional, verifiable advantage on a later
task, across a person's supported projects, and eventually through explicitly
approved team sharing. Do not equate captured notes with learning, or successful
recall with demonstrated savings.

## Capability map

Dependencies name providers whose contracts the consumer needs. Module ids are
stable; a later spec must use its module id rather than introduce another
decomposition.

| Module id | Responsibility and primary output | Depends on | Release |
|---|---|---|---|
| `experience-ledger` | Versioned experience and reuse records, evidence references, scope/provenance, measurement units, and durable deduplication. Owns the shared record vocabulary. | None | Personal pilot |
| `learning-admission` | Enforce evidence, current-context, scope, and review gates before automatic capture and promotion; return explicit ignore/defer/review/admit outcomes. | `experience-ledger` | Personal pilot |
| `conditional-recall` | Select applicable, permitted lessons within a context budget; explain selection or abstention and reference exact lesson versions. | `experience-ledger`, `learning-admission` | Personal pilot |
| `host-lifecycle` | Translate supported host events into capture, finalization, recall, and outcome records. Declare verified automation coverage rather than infer it from instructions. | `experience-ledger`, `learning-admission`, `conditional-recall` | Personal pilot |
| `reuse-evaluation` | Reconstruct outcome/overhead reports and compare frozen memory policies on approved, isolated task trials. Keep measured utility separate from claim confidence. | `experience-ledger`, `learning-admission`, `conditional-recall`, `host-lifecycle` | Personal pilot |
| `procedure-promotion` | Propose parameterized, evidence-backed procedures with preconditions and verification steps; retain human approval before graduation or execution. | `experience-ledger`, `reuse-evaluation` | After pilot benefit is demonstrated |
| `team-exchange` | Export/import only reviewed, authorized lessons with provenance and revocation handling; never pool private raw sessions. | `experience-ledger`, `reuse-evaluation` | Controlled team pilot |

## Dependency and build order

```text
experience-ledger
  -> learning-admission
    -> conditional-recall
      -> host-lifecycle
        -> reuse-evaluation
          -> procedure-promotion
          -> team-exchange
```

The table is authoritative for direct dependencies; the diagram shows one valid
build order. The last two modules need not depend on each other. Writing a reuse
receipt back through the ledger's contract is data flow, not a reverse module
dependency.

Baseline scenarios and acceptance checks must be designed before implementation.
This build order is not permission to defer evaluation design until the end.

## Boundary ownership to settle in module specs

| Provider | Boundary it must define after map approval |
|---|---|
| `experience-ledger` | Identity and correlation of a task, session, agent run, attempt, event, and lesson version; evidence and scope rules; measurement provenance; validation errors; replay/deduplication behavior. |
| `learning-admission` | Proposal structure, evidence eligibility, review authority, current-revision checks, explicit deferral, and promotion-bypass prevention. |
| `conditional-recall` | Valid query context, applicability requirements, selected references, budget accounting, abstention reasons, and missing-context behavior. |
| `host-lifecycle` | Capability declaration, host/version qualification, event mapping, actual versus assisted capture, interruption/retry handling, and unsupported-host behavior. |
| `reuse-evaluation` | Outcome definitions, comparison protocol, cost allocation, missing measurements, uncertainty, and the distinction between observational and controlled results. |
| `procedure-promotion` | Proposal contents, evidence threshold, safety review, approval, rollback, and the boundary with existing human-owned skill publication. |
| `team-exchange` | Authorized publisher/recipient scope, permitted payload, validation and review on import, withdrawal, and limits of offline revocation. |

These are provider responsibilities. The current experimental formats and
commands are described in [IMPLEMENTATION.md](IMPLEMENTATION.md). No REST
service, global cloud profile, or additional runtime dependency is implied.

## Independently verifiable outcomes

- `experience-ledger`: replaying one event does not duplicate an observation or
  manufacture independent supporting evidence; deleting derived caches does not
  change the reconstructable history. Parallel producers cannot finalize or
  clear another producer's unfinished evidence.
- `learning-admission`: structurally plausible text cannot grant itself execution
  evidence or human approval; a stale or unsupported proposal is not captured as knowledge.
- `conditional-recall`: a matching lesson can be selected; a forbidden,
  inapplicable, contradicted, or over-budget lesson is not injected.
- `host-lifecycle`: a demonstrated supported path closes the loop without a
  special user memory prompt; an interrupted or unsupported path remains
  explicitly incomplete or assisted.
- `reuse-evaluation`: another run can reproduce the report from frozen inputs;
  missing billing data never becomes zero cost or a dollar-savings claim.
- `procedure-promotion`: an unapproved or inapplicable proposal cannot become an
  executable automatic action.
- `team-exchange`: a private or withdrawn lesson cannot enter a newly generated
  authorized export; imported assertions alone cannot validate a claim.

## Why these boundaries

- Storage/evidence rules must not depend on a particular assistant or retrieval
  policy. That permits different hosts to report comparable records.
- Recall can be tested without live assistant sessions; adapters can be tested
  without changing selection policy.
- Evaluation consumes evidence. It must not rewrite history or inflate confidence
  merely because a faster run happened to succeed.
- Procedure generation and team exchange can be deferred independently without
  weakening the personal learning loop.

## Scope gate and next artifacts

Human review must confirm or revise:

1. Further changes to the seven module boundaries and dependency direction.
2. The personal pilot's execution host and task families.
3. Whether zero-repository-setup GitHub cloud coverage is a first-release
   requirement. If it is, host feasibility blocks the proposed local pilot from
   being called a complete solution.
4. The privacy boundary and the experimental success criteria in the initiative.

Future provider specifications use the stable module ids above. The local
experimental implementation is not approval for production rollout, paid
experiments, team exchange, or a hosted service.
