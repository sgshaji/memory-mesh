---
type: project
title: Memory Mesh V2 - Verified Experience Transfer
domains: [coding-agents, agent-skills]
---

# Initiative definition: Verified Experience Transfer

Document revision: 0.2, 2026-09-14.
Decision state: **experimental local implementation authorized; product/release gates remain open**.

The implemented personal-pilot interfaces, safety boundaries, and limitations
are documented in [IMPLEMENTATION.md](IMPLEMENTATION.md). The current host
grade is assisted; no 10x benefit, universal host automation, or production
capacity is claimed. Frozen V1 contracts and defaults remain unchanged.

This is the product-level definition accompanying the
[proposed capability map](CAPABILITY-MAP.md). The initiative contains independently
testable capabilities, so module specifications, implementation plans, and code
follow the capability map. This document remains the product-level contract;
the implementation guide records the current experimental commands and formats.

The [V1 principles](../../_meta/spec/principles.md) and other frozen contracts
remain authoritative. This proposal does not modify them.

## 1. Objective

Make a completed task leave a small, verifiable advantage for a later relevant
task: fewer repeated mistakes, less repeated investigation, and lower total
effort and cost at equal or better correctness.

The first customer is one person working across multiple projects. A later
customer is a team reusing explicitly approved lessons without pooling private
sessions. "Across projects" must mean more than this repository; "automatic"
must be demonstrated on each supported host rather than inferred from a prompt
telling an agent to remember.

The product is not another transcript store. Its central question is:

> Under these conditions, which prior experience is safe and useful to reuse,
> what changed when it was used, and did that change justify its full cost?

### Working assumptions requiring review

- Start with recurring engineering and tool-setup tasks that have observable
  checks, rather than every category of knowledge work.
- Prove personal benefit before procedure automation or team distribution.
- Use the existing local-first, Python/stdlib, Markdown/Git foundation.
- Copilot CLI is the proposed first automation qualification target because the
  repository already has lifecycle hooks. This is a proposal, not an assumption
  that the user's primary workflow is local.
- If automatic access from every GitHub cloud project with no repository setup
  is mandatory for the first release, host feasibility is a blocking gate.
  A local cross-project pilot does not satisfy that requirement.

## 2. Proposed innovation and falsifiable hypotheses

The proposed unit of reuse is a **conditional lesson**, not a free-floating
summary. It connects applicability conditions, an observed problem or approach,
supporting evidence, a verification method, and limitations. This extends the
existing candidate/knowledge model rather than creating a second canon.

A **reuse receipt** records the exact lesson version considered or applied,
the task context, observed checks/outcome, and measurement provenance. It is
evidence of an interaction, not an agent-authored assertion that money was saved.

Three distinct assessments must not be collapsed into one score:

1. **Evidence confidence:** how well supported the claim is; curator-derived.
2. **Applicability:** whether its conditions and permissions fit this task.
3. **Empirical utility:** what comparative outcomes suggest about benefit and
   overhead, with sample size, cohort, uncertainty, and missing data visible.

| Hypothesis | Test | Failure interpretation |
|---|---|---|
| H1: conditional reuse prevents repeated detours better than domain-only recall. | Compare current V1 and the proposed selector on held-out task variants, including wrong-tool, wrong-version, and unrelated-project controls. | Better storage or more notes did not produce better decisions; narrow the task family or selection policy. |
| H2: selective recall plus a complete lifecycle produces positive net benefit. | Compare accepted outcomes, retries, active time, and total measured cost against a consistent host baseline, including memory overhead. | Capture/curation/recall costs more than it saves; do not expand the rollout. |
| H3: verified experiences can become transferable procedures without carrying accidental assumptions. | In a later release, test a reviewed procedure on unseen permitted contexts and reject incompatible contexts. | The procedure is overfit or insufficiently scoped; keep it a lesson, not an automation. |

The defensible project claim is a combination of **portable evidence, conditional
reuse, auditable benefit, and controlled sharing**. It is not a claim that memory,
reflection, retrieval, or workflow generation is globally novel. A patent or
exhaustive research novelty claim is outside this specification.

## 3. Existing foundation and concrete gaps

| Existing surface | Reuse it for | Gap this initiative addresses |
|---|---|---|
| [capture.py](../../memory_mesh/capture.py) | Validated, redacted, structured candidates and exact-content deduplication. | Link observations to durable task/evidence identity without manufacturing independent confirmations. |
| [episodes.py](../../memory_mesh/episodes.py) and [CLI lifecycle](../../memory_mesh/cli.py) | Raw stubs, explicit finalization, retrieved-versus-used records. | Qualify a complete, interruption-safe handoff; a raw stub alone is not a mined lesson. |
| [recall.py](../../memory_mesh/recall.py) | Bounded domain/index retrieval, inactive-note filtering, and session telemetry. | Task applicability, complete brief accounting, and an explicitly governed abstention path. |
| [confidence.py](../../memory_mesh/confidence.py) and [curator](../../memory_mesh/curator/engine.py) | Evidence/confidence, contradiction handling, review, and graduation proposals. | Keep claim accuracy distinct from measured task benefit; do not replace these safeguards with popularity or speed. |
| [Copilot integration](../../integrations/vscode-copilot/README.md) | Existing user-level local setup and known host differences. | Capability-tested automation grades; no universal cloud support claim. |

Source inspection confirms that default `run_compile` selects summarized
episodes, not raw stubs. The current retrieval function uses task text for
domain routing, then follows index section order; its token limit alone is not
proof of task relevance. These are implementation observations, not benchmark
results.

## 4. User experience and stories

### Illustrative experience

Task A encounters a problem, rejects an unsuccessful approach, and verifies a
fix under a particular tool/environment. The host contributes the minimum
redacted evidence while its context is available. Finalization and curation make
an eligible lesson available under the existing trust rules.

Task B, in a different permitted project with matching conditions, receives a
short brief: what prior failure to avoid, the supported approach, and how to
check it. Its outcome produces a receipt. Task C with incompatible conditions
receives no such lesson. None of these examples is a claim that an experiment
has already succeeded.

| Story | Required experience |
|---|---|
| Personal continuity | A portable lesson can help in two separate authorized projects; a project-specific lesson cannot silently cross that boundary. |
| Automatic learning | On a qualified host path, no special user `learn` or `recall` prompt is required. Missing semantic evidence remains pending, not fabricated. |
| Trust and control | The user can inspect why a lesson was selected, its evidence/limitations, and the outcome record, and can withdraw it from future use. |
| Benefit visibility | A report distinguishes verified outcomes, incomplete measurements, observed correlations, and controlled comparative results. |
| Team reuse, later | Only reviewed, authorized lesson exports become import candidates; recipients do not inherit validation or access rights merely because a file says so. |

## 5. Scope and releases

### R1: personal verified-reuse pilot

Deliver the first five modules in the [capability map](CAPABILITY-MAP.md):
`experience-ledger`, `learning-admission`, `conditional-recall`, `host-lifecycle`, and
`reuse-evaluation`.

- Close capture -> finalization -> curation -> applicable recall -> receipt on
  one qualified host, across at least two independent project roots.
- Use existing knowledge promotion/review machinery. Do not automatically
  summarize an unavailable transcript or invent a verification outcome.
- Track incomplete lifecycle records and stale derived outputs visibly.
- Allow no useful result to be an explicit outcome under the approved V2
  policy, rather than filling the brief with unrelated notes.
- Produce a reproducible pilot report, not a dashboard full of claimed savings.

### Later: reviewed procedures and controlled team exchange

`procedure-promotion` and `team-exchange` may follow demonstrated R1 benefit.
Neither is required to ship the personal pilot.

Procedure proposals need applicable conditions, explicit parameters, verification,
failure behavior, and human approval. The existing human-owned skill publication
boundary remains intact; generated proposals are not executable authority.

The first team experiment is a reviewed exchange between separate private vaults,
not a shared global transcript store or a hosted multi-tenant service. Withdrawal
can prevent future authorized exports/reuse; it cannot erase already downloaded
copies or text already present in another session.

### Host coverage is a release property

| Surface | Current basis | V2 rule |
|---|---|---|
| Copilot CLI, local | Lifecycle hooks and user-level installation exist. | Qualify the full loop on recorded host versions; prove cross-project use. |
| VS Code, local | Instructions and skills; CLI repository hooks are not executed by VS Code. | Label assisted until a supported adapter proves the required events. |
| GitHub cloud agent | Local vault hook output is disabled in this integration. | Do not advertise account-wide Memory Mesh injection. Validate an authorized integration mechanism separately. |
| Additional hosts | Existing adapters/contracts have different guarantees. | Add only after capability, privacy, interruption, and measurement tests. |

Native Copilot Memory is a separate, user-enabled product capability. It does
not prove that an arbitrary external skill bundle or Memory Mesh vault can be
installed globally into every cloud workspace.

## 6. Success criteria

These are proposed product acceptance targets for scope review, not assertions
about current performance. Provider-specific cases and fixtures belong in the
module specs after approval.

| Id | Acceptance condition | Verification |
|---|---|---|
| VET-01 | A verified portable lesson from task A is eligible in a distinct permitted project on task B; a project-bound lesson is not. | Two isolated project fixtures with matching and mismatching conditions. |
| VET-02 | One logical event cannot create duplicate experience, independent evidence, or benefit counts after retry/resume. Reusing its identity with conflicting content is rejected explicitly; parallel agent runs cannot erase or finalize each other's unfinished records. | Duplicate, conflict, concurrent-producer, interrupted-write, and rebuild cases. |
| VET-03 | Incomplete or unverified outcomes remain visibly incomplete/unknown; no raw stub is presented as successfully mined experience. | Missing-evidence and interrupted-finalization cases. |
| VET-04 | Forbidden, inapplicable, inactive, or unresolved contradictory lessons are not injected. | Scope, tool/version, expiry, and contradiction negative controls. |
| VET-05 | The proposed V2 brief, including metadata and explanations, stays within 2,000 estimated tokens and six notes; abstention is explicit. | Boundary-sized brief and no-applicable-result cases. |
| VET-06 | Existing automatic-operation and privacy boundaries are not silently relaxed. Extra model calls are included in overhead, not described as free instrumentation. | Event traces and policy checks against the approved lifecycle contract. |
| VET-07 | Every reported receipt identifies the lesson revision and measurement provenance; derived reports can be rebuilt from approved canonical records. | Delete disposable report/cache state and compare reconstructed results. |
| VET-08 | A fast successful run cannot on its own promote a claim, increase evidence confidence, or authorize a procedure/team export. | Independence, trust, and unauthorized-action negative cases. |
| VET-09 | A controlled pilot has no lower acceptance-test success than its declared baseline, no regression on predeclared critical/safety cases, and lower measured cost per accepted task and median active task time. | Predeclared paired trials; include failed attempts, no-match tasks, and all memory overhead within the declared accounting boundary. |
| VET-10 | Missing billing/usage measurements never become zero or an inferred dollar saving. A non-resettable/incomparable host experiment is labeled observational. | Missing-unit, provider/version change, and contaminated-baseline cases. |
| VET-11 | Invalid input, instruction-like retrieved content, stale artifacts, and incomplete processing produce explicit bounded outcomes, not silent success. | Existing safety patterns plus new boundary and interruption cases. |
| VET-12 | Real personal/team memory is not published with the product source. Confidential content is excluded before persistence or export. | Fixture-based redaction and export-boundary tests; review release artifacts. |

The later procedure release additionally requires unseen-context verification
and explicit approval before publication/use. The team release additionally
requires authorized export/import, provenance review, and documented withdrawal
behavior.

## 7. Testing strategy and honest benefit evaluation

Use the existing stdlib `unittest` framework and hermetic temporary-vault helpers.
Do not add a new testing framework or require a live LLM for the default suite.
Preserve all existing tests; cover every new decision branch and error outcome
with targeted tests. No numeric coverage percentage is asserted for V1.

Test levels:

1. Pure units: applicability, budgets, record validation, deduplication identity,
   measurement arithmetic, and policy decisions.
2. Contract/integration: temporary vaults, real Git history where relevant,
   lifecycle replay, finalization, curation, and report reconstruction.
3. Host qualification: opt-in controlled sessions on an identified host/version.
   A passing unit test cannot certify a host event that was never observed.
4. Benefit trials: separately budgeted, approved experiments; never automatically
   execute commands mined from arbitrary past sessions.

### Pilot protocol

- Approve the host, task families, acceptance checks, run budget, sample size,
  and analysis method before collecting outcome data.
- Start with at least 20 held-out task pairs across five task families, plus
  negative controls. This is a pilot minimum, not a claim of statistical power.
  Use repeated trials where the host/model is stochastic.
- Group cases by underlying problem family and chronology, not superficial
  prompt wording. Report within-family repeat-task transfer separately from
  unseen-family generalization; paraphrases of one solved case do not establish
  broad transfer.
- Freeze the prior experiences and lesson versions. Future task answers cannot
  enter the memory snapshot used to solve those tasks.
- Compare: the consistent host baseline; the same host plus current V1 Mesh;
  and the same host plus the proposed V2 policy.
- Keep model/tool versions, native-memory settings, task/check definitions,
  context/time limits, and charging rules consistent. Randomize trial order
  and isolate task workspaces and memory writes between arms.
- Give comparison arms equivalent prior histories and warm-up opportunities.
  Separate cold-start results from amortized reuse. For online adaptation,
  score a task before updating memory and evaluate that protocol separately
  from frozen replay.
- If native state cannot be reset or held comparable, report that limitation;
  do not describe the result as a controlled estimate of memory's causal effect.
- Include task execution, capture, recall, failed attempts, revalidation, and a
  disclosed allocation of curation/maintenance cost. Do not amortize over
  hypothetical future reuses that have not happened.
- Declare the accounting boundary and rate provenance. Report human review
  time, foreground latency, and billable model/API spending separately; do not
  add unlike units or call unmetered costs zero. Report both the eligible reuse
  cohort and the entire task stream, including no-match overhead, and show the
  observed reuse frequency needed to recover learning overhead.
- Report paired outcomes, time distributions, billing coverage, sample sizes,
  and uncertainty. A favorable point estimate alone is not sufficient for a
  general "cheaper" claim. If VET-09 cannot be established, keep the release
  experimental and narrow the use case.

Task success alone is observational evidence. A per-lesson receipt must not say
"saved five minutes" when no defensible comparison measured that difference.
Attributing improvement to one lesson requires a controlled withholding or
ablation comparison; an overall policy improvement cannot be credited to every
lesson that happened to be served.

## 8. Tech stack and commands

Baseline: Python >=3.10, stdlib-only runtime, Markdown as canonical storage,
Git for attributable history/rollback, existing filesystem helpers and CLI.
The current package is version 0.1.0. No database, vector store, hosted model,
HTTP API, or new runtime dependency is selected by this proposal.

Run these existing commands from the repository root with the selected Python
environment. They are not new V2 commands:

```powershell
# Discover current commands.
python -m memory_mesh.cli --help

# Read-only vault checks. Unlike doctor --fix, these do not scaffold the vault.
python -m memory_mesh.cli --root . doctor
python -m memory_mesh.cli --root . status
python -m memory_mesh.cli --root . lint

# Focused existing tests for recall behavior.
python -m unittest discover -s tests -p "test_recall.py" -v

# Existing full suite, required before a later implementation commit.
python -m unittest discover -s tests -q
```

There is no separate build/lint service to start for a documentation change.
`memory compile`, `memory curate`, `memory pack`, and `doctor --fix` have write
effects and are not validation commands for reviewing this proposal. New
commands, flags, outputs, and exit codes must be specified by their provider
module after scope approval; do not infer that V2 commands already exist.

## 9. Project structure and compatibility

| Location | Role |
|---|---|
| [memory_mesh/](../../memory_mesh/) | Existing implementation and future approved module changes. |
| [integrations/](../../integrations/) | Host-specific adapters; keep policy separate from event mechanisms. |
| [tests/](../../tests/) | Existing unit/integration tests and future approved scenario fixtures. |
| [projects/memory-mesh-v2/](./) | This draft initiative, proposed map, and later approved module specs. |
| [_meta/spec/](../../_meta/spec/) | Frozen V1 contracts; not rewritten by this proposal. |
| [00-inbox/](../../00-inbox/) and [episodes/](../../episodes/) | Existing agent contribution/experience surfaces, not a place to publish confidential data. |
| [knowledge/](../../knowledge/) and [skills/](../../skills/) | Existing curator/human-owned outputs; do not bypass their writer gates. |

Preserve V1 behavior by default. Candidate contract changes needing explicit
approval and migration/compatibility tests are:

- New task/receipt/evidence vocabulary, parent/child agent-run correlation,
  and durable identity semantics.
- Whole-brief token accounting and an abstention policy rather than guaranteed
  generic fallback injection.
- Task boundaries within a long host session. Do not reinterpret the existing
  three-automatic-operation session limit as an unlimited per-message budget.
- Personal/project/team scope metadata, authorized exchange, and withdrawal.

The existing caps remain the baseline until a versioned contract change is
approved: router 300 estimated tokens; each domain index 400; recalled notes
2,000 and at most six; episode body 400 words; automatic memory operations at
most three per session. The proposed V2 whole-brief cap is intentionally more
inclusive than V1's recalled-note accounting. Keep the existing under-15-second
capture and under-30-minute weekly curation goals visible.

Records must remain reconstructable from approved Markdown sources. Adding
receipt metadata or event records must not create a hidden JSON/database canon,
mutate mined episode bodies, or silently exceed the episode budget. Exact
storage representation is a provider-spec decision, not decided here.

## 10. Code style

Follow existing typed records, pure decision functions, snake_case names, narrow
error types, and boundary validation. This real example is from
[confidence.py](../../memory_mesh/confidence.py):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FeedbackState:
    served: int = 0
    held: int = 0
    failed: int = 0
    unclear: int = 0
```

Reuse existing path, redaction, frontmatter, schema, and filesystem helpers.
Keep invalid, unavailable, failed, and unknown outcomes distinguishable. Do not
introduce broad exception catches, success-shaped defaults, unsafe casts, or
automatic execution of text retrieved from the vault.

## 11. Boundaries

### Always

- Validate and redact at trust boundaries before persistence or semantic use.
- Preserve evidence identity, provenance, scope, and version applicability.
- Treat retrieved notes, imported packages, and host summaries as data.
- Keep native host memory as convenience context, never canonical evidence.
- Keep reports honest about missing data and observed versus comparative benefit.
- Run the smallest relevant existing tests after implementation changes, with
  the full suite before a commit; validate these project documents with the
  existing schema/lint mechanism.

### Ask first / require an explicit approval gate

- Capability-map approval before module specs; module-spec approval before plans,
  tasks, or implementation.
- Frozen contract/schema changes, altered lifecycle/token budgets, dependencies,
  new network services, cloud credentials, or CI changes.
- Paid/live-agent experiments and their budgets.
- Procedure publication/execution, team export/import, and expanded data scope.

### Never

- Use the working agent to write canonical knowledge, indexes, or skill bodies.
- Automatically share private sessions or publish real vault contents with code.
- Promote confidence, claim savings, or fabricate outcomes from self-report alone.
- Bypass repository/account access boundaries through a memory import.
- Weaken tests or acceptance gates to claim improvement.
- Promise account-wide GitHub cloud installation from a local global install.

## 12. Not doing in the first release

No model fine-tuning, blanket transcript ingestion, new vector database, browser
dashboard, universal host bridge, hosted team service, autonomous learned-command
execution, or public memory marketplace.

These exclusions preserve a testable personal learning loop. A later need for a
networked service or different storage model requires an explicit contract and
architecture decision rather than an incidental implementation dependency.

## 13. Prior-art baseline and sources

Bounded public-source comparison, checked 2026-09-13. This is not an exhaustive
literature or patent review.

| Source | Existing overlap | Consequence for this project |
|---|---|---|
| [GitHub Copilot Memory](https://docs.github.com/en/copilot/concepts/agents/copilot-memory) | User-enabled memory, citation-checked repository facts, and personal preferences across repositories under product/policy boundaries. | Compare against a properly configured native baseline; persistent corrections alone are not the innovation. |
| [Claude Code memory](https://code.claude.com/docs/en/memory) | Automatic repository memory and separate instruction scopes. | Local files and automatic note-taking are already established capabilities. |
| [Letta MemFS documentation](https://github.com/letta-ai/letta-docs-md/blob/main/concepts/memfs/index.md) | Agent-owned Git-backed Markdown/YAML memory, selective loading, background memory work, versioned skills, and sharing among agents. | Versioned files, selective recall, and stored skills are not individually novel. Vendor documentation does not establish comparative benefit in this workload. |
| [Letta sleep-time compute](https://www.letta.com/blog/sleep-time-compute/) | A published architecture for asynchronous reasoning and memory consolidation outside the foreground agent. | Background learning is prior art. Lower foreground latency is not automatically lower total cost; the historical article is not a claim about every current MemFS implementation. |
| [Mem0 source at ed38ddf](https://github.com/mem0ai/mem0/blob/ed38ddf8731fb7fab7c41bb0f8ab3185df23e7c5/mem0/memory/main.py) | Entity-scoped storage/query paths and memory mutation history are implemented. | Scope metadata and history are prior art; identifiers/filtering alone do not establish team authorization. This is a source observation, not a hosted-service audit. |
| [ACE primary paper](https://arxiv.org/html/2510.04618v1) | Itemized playbooks, strategies/failure modes, reflection/curation, and helpful/harmful counters. | Strategy reuse and utility-like counters are prior art. Generator-assigned helpfulness is not causal attribution. Author-reported results against other baselines are not projected V2 savings. |

The proposed distinction is the evidence-governed combination: a conditional
lesson identifies when it may apply; a receipt connects its exact version to
an attempted reuse; controlled evaluation distinguishes usefulness from mere
retrieval; human review gates executable promotion and team transfer.

These sources do not establish that complete combination as a unique invention,
nor do they prove a gap that users will pay to fill. H1-H3 and the pilot protocol
must establish whether this particular implementation adds value. If a simpler
native-memory configuration achieves the same outcomes and cost, that is a
reason to narrow or stop the additional system.

## 14. Decisions still required before module specs

| Decision | Proposed position | Consequence if different |
|---|---|---|
| Primary execution host | Qualify the existing local Copilot CLI path first. | A cloud-first requirement blocks this choice until an authorized integration is demonstrated. |
| First task families | Repeated engineering/tool-setup work with observable acceptance checks. | Subjective tasks need independent evaluation rubrics before a benefit claim. |
| Module boundaries | Maintain the seven-module map, including separate learning admission. | Review boundary changes before extending the experimental interfaces. |
| Benchmark and cost reporting | Approve a bounded, predeclared pilot with honest missing-data handling. | No "better and cheaper" claim without comparable evidence. |
| Team scope | Separate private vaults and explicit reviewed exchange later. | Online multi-user operation needs additional authorization, retention, and deployment design. |

Next gate: validate the experimental implementation against the remaining
host, benefit, capacity, privacy, and release criteria. Review further contracts
in provider-first order. This implementation does not approve paid experiments,
team or hosted rollout, or changes to frozen V1 contracts.
