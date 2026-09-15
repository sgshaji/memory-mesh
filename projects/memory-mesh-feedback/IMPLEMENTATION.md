---
type: project
title: Memory Mesh feedback loops and operational policy
domains: [coding-agents, agent-skills]
---

# Inspectable feedback loops

Memory Mesh keeps reported feedback separate from factual admission. A useful
recall, high-priority candidate, or successful skill invocation is not proof
that a knowledge claim is true. Only the curator updates canonical knowledge;
destructive and high-impact proposals still require human review.

The implementation remains local-first and stdlib-only. Markdown records are
inspectable in Git. No model call, vector index, database, background service,
or network dependency is required for the bookkeeping described here.

## Architecture

```text
Task -> deterministic routing -> bounded recall -> recorded recall attempt
                         |                         |
                         |                         v
                         |              reported knowledge/skill outcomes
                         |                         |
                         v                         v
                 routing suggestions <- partial/prefilled episode
                         |                         |
                         v                         v
                human review          dated, context-aware evidence
                                                   |
                  inbox signal/linkage/age ---------+
                                                   v
                              guarded curator compile + maintenance
                                |             |              |
                                v             v              v
                            confidence     index hygiene   skill health
                                |             |              |
                                +-------------+--------------+
                                              v
                                    future recall / review
```

The strict V2 task/admission/attestation path remains separate in authority.
General feedback events cannot authorize V2 publication, satisfy a required
execution check, release a held lesson, or become measured causal benefit.

## Low-friction outcomes

Use the same session identifier as recall or the host lifecycle:

```sh
memory recall "Validate a document schema" --session demo
memory feedback knowledge/patterns/validation-order "#held" --session demo
memory feedback knowledge/patterns/validation-order "#failed" --session demo \
  --reason behaviour_changed --product copilot-studio --version 2026-09
memory feedback skills/document-validation partial --subject skill --session demo
memory recall-quality off-target --session demo --detail "The task needed a different domain."
```

Quote hashtag tags so the shell does not interpret them as comments. Bare
`held`, `failed`, and `unclear` are equivalent. Knowledge also retains the
legacy `not-applicable` outcome. Skills use `succeeded`, `failed`, or `partial`;
recall quality uses `useful`, `partial`, `missed`, or `off-target`.

`--detail` is short explanatory text; `--reason` is a controlled failure code.
Tool, product, version, project, and domain context are optional. Unknown
references, outcomes, malformed timestamps, and conflicting identities fail
explicitly rather than silently creating a success-shaped record.

Identical capture intent in one session is a retry, not another observation.
Use a distinct `--event-id` for a genuinely independent trial and reuse that ID
when retrying the trial. Event timestamps are fixed at first persistence.
Feedback capture does not change a knowledge file or skill body.

Recall's existing `--tool` identifies the logging host. Use `--context-tool`,
`--product`, or `--version` for explicit applicability context; strict V2
continues to use its task-bound context instead of caller overrides.
`--attempt-id` identifies an independent recall trial. `--capture-gap` can
capture a research need from a weak/empty recorded result, but cannot be
combined with `--no-log`.

## Outcome records and provenance

The shared [`OutcomeEvent`](../../memory_mesh/outcome_types.py) contract has:

```yaml
schema_version: 1
event_id: example-trial
timestamp: 2026-09-14T12:00:00+00:00
session_id: demo
subject_type: knowledge
subject_id: knowledge/patterns/validation-order
outcome: failed
reason: behaviour_changed
domain: copilot-studio
context: {product: copilot-studio, version: 2026-09}
source: cli
detail: The deterministic check no longer matched the documented behavior.
```

One immutable Markdown record per event under `episodes/_outcomes/` avoids
multiple contributors appending to a shared history file. Canonical references
are used internally so two notes with the same basename are not conflated.
Episode projections retain event identity and are aggregated once, not once
from the journal and again from the episode.

V2 reuse keeps its one-per-task summary and additionally preserves full new
outcome history. The common journal is projected only after V2 validation and
receipt persistence. If projection fails, the command reports the partial
failure; retrying the same event ID repairs the journal with the original
timestamp. Legacy receipts lacking full history are labeled as legacy rather
than assigned invented historical timestamps.

New V2 projection IDs include the source admission namespace, so task-local
proposal and event labels cannot collide across originating lessons.
Existing persisted projection IDs remain unchanged on replay. If an older,
already-colliding ID belongs to another intent, both histories are preserved
and the error calls for a distinct feedback event ID rather than an endless
same-ID retry.

## Partial episodes and pre-fill

```sh
memory session-end --session demo --tool cli --slug validation-session
memory episode finish episodes/<printed-file>.md
```

The printed path is authoritative. Available retrieved notes, outcomes, recall
quality, and observable checkpoints can pre-fill the episode. Provenance
distinguishes recorded actions and operator-reported outcomes from inference.
Uncontrolled host transcripts are not read or silently summarized.

An episode with only `Knowledge used` and `Candidate learnings` is useful.
Missing sections need not be filled with invented prose. Existing complete
episodes and their lifecycle remain supported; a completely empty stub is not
a useful finished summary. Missing and explicitly empty sections stay
distinguishable to parsing/mining.

Empty, outcome-only, and gap-only sessions are retained. Native recall
pre-fill stays separate from manual compaction checkpoints, so existing
checkpoint counts and timestamps retain their meaning.

## Recall quality, routing, and gaps

The existing `_domains.md` table remains the domain registry and legacy
vocabulary. Optional configuration adds keywords, aliases, and concepts without
putting human-maintained metadata into regenerated index files.

Rendered recall context uses an in-memory index view containing only served
links. Expired, incompatible, invalid, or budget-excluded links are not
recommended by re-emitting the stored index. Stored indexes are unchanged,
including with `--no-log`.

After an episode, deterministic term matching compares recalled domains with
the available work, learning, and knowledge-use sections. Mismatch diagnostics
are reviewable suggestions, not automatic router rewrites.

Empty and weak recalls have durable attempt records under `episodes/_recalls/`.
An attempted empty recall differs from no attempt. Records preserve the
configured target, actual result, domain/route, and bounded redacted task
context. `--no-log` and pack generation do not create telemetry records.

```sh
memory gap "Connector authentication during solution import" \
  --domain copilot-studio --session demo
```

A `type: gap` inbox record expresses a research need. It cannot take the
factual claim promotion path merely because it is high signal, repeatedly
requested, or linked from an episode.

## Confidence and failure interpretation

The default recency factor is:

```text
recency_weight = 2 ** (-age_in_days / half_life_days)
default half_life_days = 90
effective_weight = recency_weight * context_weight * failure_reason_weight
```

Old evidence is retained, not discarded. Structured applicability determines
whether an observation matches, clearly mismatches, or has insufficient
context. Unknown versions are not guessed or compared lexicographically.
The same practical matcher is shared by evidence, recall, and skill health.

| Failure reason | Default multiplier | Interpretation |
|---|---|---|
| `behaviour_changed` | 1.0 | Strong evidence of a changed underlying behavior |
| `misapplied` | 0.1 | Weak evidence against the underlying claim |
| `context_mismatch` | 0.1 | Weak evidence outside the intended context |
| `insufficient_information` | 0.25 | Inconclusive failure rather than a definitive contradiction |
| `unknown` | 0.5 | A reported failure without a more specific diagnosis |

Context multipliers default to 1.0 for a match, 0.5 for unknown context, and
0.1 for a mismatch. Mismatched successes supply no supporting weight.
Only the strongest contribution per session and outcome bucket counts toward
weighted totals; all unique reports remain inspectable. Partial skill outcomes
are neutral/unclear, and `not-applicable` supplies no confidence weight.

The evaluator reports high confidence only with at least 3 weighted successes,
a success ratio of at least 0.9, and 3 independent matched supporting sessions.
Medium requires at least 0.5 weighted successes and a ratio of at least 0.6.
Otherwise its reported-evidence confidence is low. These are explainable
evaluation results, not permission to promote a candidate or a V2 lesson.
Recalculation never repeatedly subtracts from the previous derived score.

Repeated recent matched-context behavior-change failures recommend review
even when many old successes exist. One isolated failure does not automatically
disable a skill. Confidence explanations include weighted totals, event IDs,
context/reason diagnostics, recent change signals, and verification dates.

When the configured independent-session quorum is met, compile conservatively
quarantines a currently validated **legacy** note as `status: stale`, retaining
its body and evidence and recording the reason for human review. Existing
verification-aging policy remains a separate quarantine signal. Later positive
reports do not silently reactivate, supersede, or rewrite the claim. Strict V2
admission and hold authority are not changed by this reported-feedback path.

Legacy `applies_to.from/to` values shaped as ISO dates or months are inclusive
calendar windows; a month end includes its entire last day. Recall evaluates
them at read time, while historical evidence evaluates them at event time.
Numeric or `v`-prefixed legacy bounds require an observed version. Explicit
`applies_to.version` constraints always require version context, even when a
product uses date-like version labels. Calendar bounds and explicit version
requirements can be combined independently. Quote version strings to avoid
YAML numeric coercion. Invalid/mixed bounds are diagnosed rather than guessed.

## Candidate attention and inbox health

Candidates accept optional `signal: high | normal | low`, defaulting to normal.
Explicit episode linkage and references in `Candidate learnings` provide
context for deterministic priority. Ranking exposes its signal, linkage,
recurrence, and recency reasons. Priority controls attention, not approval.

```sh
memory learn "Run deterministic schema validation before reasoning (cli, 1.0)" \
  --signal high --source-episode episodes/demo
```

Status reports high-signal and episode-linked counts, oldest age, and warnings
when the configured review-age threshold is exceeded. Aging is operational
information, not evidence that a candidate is false.

## Read-only status

```sh
memory status
memory status --json --days 30
```

The structured report separates attempts, served notes, unique sessions,
empty/weak results, and explicitly reported recall quality. It also includes
inbox health, recorded knowledge confidence warnings, skill review flags,
routing suggestions, and curation recovery state. Status does not promote,
rewrite, or repair records.

```sh
memory explain knowledge/patterns/validation-order
memory explain knowledge/patterns/validation-order --usage
memory explain skills/document-validation --subject skill
memory explain 00-inbox/<candidate> --subject candidate
memory explain "MCP stdio transport" --subject routing
```

Explanations use the same assessment policy as maintenance. `--usage` adds
observed recall counts, not confidence votes or proof of usefulness.

## Skill health and dependency review

Human-authored skill metadata can include:

```yaml
type: skill
title: Document validation
depends_on: [knowledge/patterns/validation-order]
applies_to:
  product: copilot-studio
  version: ">=2026-01"
```

Derived health combines skill outcomes with missing, stale, superseded,
low-confidence, or incompatible knowledge dependencies and verification age.
`confidence` and `needs_review` are separate: a historically reliable skill may
need review after a product changes. Warnings do not edit, delete, or disable
the skill.

## Usage and index maintenance

Usage derives 30-day and 90-day recall counts and the last-recalled time.
The existing four-column recall TSV remains readable; new attempt identities
provide stronger replay accounting. Frequency counters need not churn every
knowledge file.

Index promotion/demotion suggestions explain usage and quality evidence and
remain human-reviewable. By contrast, excluding stale or otherwise inactive
notes from high-trust sections is deterministic hygiene. Repeated maintenance
must not restore a stale note to `Read first` or `Recently verified`.

## Optional configuration

An absent `_meta/config.md` retains single-user operation. Example:

```yaml
---
type: meta
version: 1
feedback:
  half_life_days: 90
  recent_days: 30
  behaviour_change_failures: 2
  recall_target_minimum: 2
  inbox_review_days: 14
  skill_review_days: 90
curation:
  mode: single-user
routing:
  copilot-studio:
    keywords: [copilot studio, power virtual agents]
    aliases: [pva]
    concepts: [topics, connectors, generative orchestration]
---
```

Configuration is bounded and validated. Unknown keys or invalid numeric values
are errors, not ignored spelling mistakes. The complete defaults live in
[`FeedbackPolicy`](../../memory_mesh/feedback_config.py).

## Collaboration and conflicts

Many contributors can capture candidates, episodes, and outcomes. A designated
curator can own canonical publication. Local OS locks coordinate supported
curator processes and are released when a process exits. Expected-content
checks protect decisions based on files that have since changed.

Conflict handling preserves competing sources rather than silently applying
last-write-wins. A local lock is not distributed coordination: separate clones
still require a designated Git integration workflow and review of conflicts.
Git is not a filesystem-wide atomic transaction or an authentication service.

Git publication stages proposals in a private index. A rejected commit does
not leave proposed blobs staged in the user's real index; unrelated user
staging is preserved. A successful publication reconciles the index without
resetting concurrent user changes.

```sh
memory curation-recover --inspect
memory curation-recover
# Only after verifying all involved native Git processes have stopped:
memory curation-recover --confirm-git-stopped
# Only after reviewing a conflict and choosing to retain the current files:
memory curation-recover --acknowledge <transaction-id>
```

Acknowledgement preserves the journal and current files; it does not apply the
old decision or resolve a Git merge. A fresh curation run must recompute its
decisions. Unknown in-flight Git outcomes are not guessed from a timeout.

Filesystem writes remain provisional until the run completes. Consistent
multi-file readers must coordinate with the curator OS lock (and then the
experience lock for a combined V2 view). Plain file readers can observe
provisional working-tree state; this is not distributed snapshot isolation.

## Backward compatibility

No bulk vault migration or manual rewrite is required:

- old complete episodes and partial available sections remain readable;
- legacy project/index/context references are retained in their original
  episodes but do not become canonical knowledge votes;
- unattributed legacy feedback is retained and reported for review, not
  assigned to a guessed note; immutable journal/projection corruption still
  fails explicitly;
- missing candidate signal means normal;
- missing failure reason means unknown;
- missing applicability is unrestricted/unknown, not an invented match;
- missing skill dependencies means no declared dependency edges;
- old recall TSV rows and indexes remain readable;
- early attempt records without a full-task fingerprint retain an explicit
  unknown fingerprint; no hash is invented from possibly truncated display
  text, and their files are not rewritten;
- missing curator configuration means the single-user workflow;
- strict V2 admission, task scope, evidence budgets, and holds remain enforced.

New fields and record types are additive extensions documented here, not edits
to the frozen V1 contract files. Older binaries may not understand the new
record types; use the updated CLI when linting or compiling an extended vault.
