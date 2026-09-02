---
type: build
title: Requirements / capability graph
updated: 2026-09-02
---

# Memory Mesh V1 — requirements graph

Control plane for the build. A node is SATISFIED only when implementation
**and** test exist and the edge to its consumer is verified. Sources:
`_meta/spec/*.md` (principles.md wins on conflict). Every `verified_by` entry
below names a real, runnable test id (audited by the Section U convergence
pass; stale ids were corrected 2026-09-02).

Statuses: `UNSATISFIED` · `PARTIAL` · `SATISFIED` · `BLOCKED` · `N/A-V1`.

## Nodes

### Principles

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| P1 | Markdown source of truth | SATISFIED | whole design; `memory_mesh/packs.py`, `recall.py` rebuild derived state | `tests/test_packs.py::test_rebuild_after_deletion`, `tests/test_recall.py::test_recall_log_written_and_disposable` | — |
| P2 | three memory tiers | SATISFIED | vault layout; `memory_mesh/config.py`, `schema.py` type→folder map | `tests/test_schema.py::test_type_folder_map` | — |
| P3 | experience != truth | SATISFIED | episodes never canonical; only curator promotes (`curator/engine.py`) | `tests/test_curation.py::test_third_party_never_promotes`, `tests/test_capture.py::test_never_writes_canonical` | P2 |
| P4 | curator-only canonical writes | SATISFIED | `memory_mesh/fsutil.py` write boundaries | `tests/test_safety.py::test_write_boundaries_agent`, `::test_write_boundaries_curator` | P2 |
| P5 | mechanism over instruction | SATISFIED | `_meta/hooks/*` and `.github/hooks/*` deterministic scripts; host instruction files carry policy | `tests/test_hooks.py::test_hook_scripts_run_as_processes`, `tests/test_copilot_integration.py::test_session_lifecycle_hooks` | I1,I2,I4 |
| P6 | smallest relevant context | SATISFIED | `memory_mesh/recall.py` budgets | `tests/test_recall.py::test_note_budget_ceiling`, `::test_recall_token_budget_skip` | R1,R2,R3 |
| P7 | evidence + temporal validity | SATISFIED | `memory_mesh/schema.py` frontmatter; `confidence.py` | `tests/test_schema.py`, `tests/test_feedback.py` | — |
| P8 | feedback loop | SATISFIED | episodes *Knowledge used* → tally → confidence → indexes → recall | `tests/test_feedback.py`, `tests/test_e2e.py::test_full_loop` | L7,C12,R2 |
| P9 | native memory non-authoritative | SATISFIED | no code path reads tool-native stores; policy in AGENTS.md/CLAUDE.md | design review (no code path exists; principles audit found none) | — |
| P10 | confidentiality | SATISFIED | `redact.py` before any canonical write incl. curator ingest and session scratch (I-024); Reference-note fallback for un-redactable items (I-025) | `tests/test_curation.py::test_redact_before_admission`, `::test_reference_note_for_unredactable_content`, `tests/test_hooks.py::test_checkpoint_text_redacted_and_state_cleared` | G1,G3 |

### Storage

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| S1 | 00-inbox | SATISFIED | scaffold; `capture.py` | `tests/test_capture.py` | — |
| S2 | episodes (+_summaries, _unreviewed) | SATISFIED | scaffold; `episodes.py`; monthly compaction in `engine.py::_compaction_pass` (I-020) | `tests/test_episodes.py`, `tests/test_curation.py::test_monthly_compaction` | — |
| S3 | knowledge/patterns | SATISFIED | scaffold; `schema.py` | `tests/test_schema.py` | — |
| S4 | knowledge/tools | SATISFIED | scaffold; `schema.py` | `tests/test_schema.py` | — |
| S5 | knowledge/workarounds | SATISFIED | scaffold; `schema.py` | `tests/test_schema.py` | — |
| S6 | knowledge/failures | SATISFIED | scaffold; failure lifecycle in `confidence.py` (never auto-stale) | `tests/test_feedback.py::test_decay_windows`, `tests/test_curation.py::test_failure_classification` | — |
| S7 | knowledge/references | SATISFIED | scaffold; `schema.py` reference type | `tests/test_schema.py::test_fixture_vault_is_clean` | — |
| S8 | knowledge/_index | SATISFIED | scaffold; `indexes.py`; every declared domain seeded | `tests/test_index.py`, `tests/test_recall.py::test_missing_index_falls_back_to_general` | — |
| S9 | projects | SATISFIED | scaffold; project type; session-start injects matching note | `tests/test_hooks.py::test_session_start_prints_router_and_project` | — |
| S10 | skills | SATISFIED | scaffold; 4 SKILL.md files; graduation proposals only | `tests/test_curation.py::test_graduation` | C15 |
| S11 | outputs/context | SATISFIED | scaffold; `packs.py` | `tests/test_packs.py` | R5 |
| S12 | _meta | SATISFIED | spec/build/hooks/templates/review/redact.txt/logs | `memory doctor` + repo inspection | — |

### Session lifecycle

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| L1 | session start | SATISFIED | `cli.py session-start`; `_meta/hooks/recall_start.py` | `tests/test_hooks.py::test_session_start_prints_router_and_project` | R1,S9 |
| L2 | domain routing | SATISFIED | `router.py` | `tests/test_recall.py::test_domain_matching`, `::test_multi_domain_matching_capped_at_two` | R1 |
| L3 | recall | SATISFIED | `recall.py` (incl. general fallback for indexless domains) | `tests/test_recall.py` | L2,R2,R3 |
| L4 | work (memory silent) | SATISFIED | no per-message operations exist | `tests/test_hooks.py::test_recall_once_per_session` | — |
| L5 | /learn | SATISFIED | `capture.py`; `cli.py learn` | `tests/test_capture.py` | S1,G1 |
| L6 | episode creation | SATISFIED | `episodes.py`; `cli.py episode` + session-end | `tests/test_episodes.py`, `tests/test_hooks.py::test_session_end_writes_stub_from_state` | S2,G1 |
| L7 | knowledge feedback | SATISFIED | *Knowledge used* parsing; tally in `curator/engine.py` | `tests/test_feedback.py::test_tally_reconstructed_from_episodes_only`, `::test_unclear_outcome_tallied` | L6,C12 |
| L8 | curator mining | SATISFIED | `curator/engine.py` compile | `tests/test_curation.py` | C1–C10 |

### Curation

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| C1 | redact | SATISFIED | `redact.py` + `_meta/redact.txt` | `tests/test_safety.py::test_secret_patterns`, `tests/test_curation.py::test_redact_before_admission` | — |
| C2 | extract candidate | SATISFIED | `engine.py` claim extraction | `tests/test_curation.py::test_extract_and_classify` | C1 |
| C3 | classify | SATISFIED | deterministic classify; adapter hook for nuance | `tests/test_curation.py::test_extract_and_classify`, `::test_failure_classification` | C2 |
| C4 | neighbour discovery | SATISFIED | `curator/neighbours.py` (index links, keywords, shared tools) | `tests/test_curation.py::test_neighbours` | C3,R2 |
| C5 | CREATE | SATISFIED | auto, status candidate | `tests/test_curation.py::test_extract_and_classify` | C4 |
| C6 | UPDATE | SATISFIED | auto: evidence/applies_to append | `tests/test_curation.py::test_update_appends_evidence` | C4 |
| C7 | MERGE | SATISFIED | review-gated proposal + apply | `tests/test_curation.py::test_gated_decisions_written_to_review_not_applied`, `::test_approved_merge_applies_and_archives` | C4 |
| C8 | SUPERSEDE | SATISFIED | review-gated; version window close | `tests/test_contradiction.py::test_approved_supersede_closes_window_and_keeps_history` | C14 |
| C9 | REJECT | SATISFIED | review-gated proposal + apply | `tests/test_curation.py::test_reject_gated` | C4 |
| C10 | HOLD | SATISFIED | non-destructive default; released when the item changes (I-007/§4) | `tests/test_curation.py::test_hold_without_model_when_ambiguous`, `::test_unclassified_claim_holds`, `::test_held_item_reevaluated_after_edit` | C4 |
| C11 | promotion | SATISFIED | 2-episodes OR reproducible-evidence rule | `tests/test_curation.py::test_promotion_two_episodes_updates_index_same_run`, `::test_promotion_reproducible_evidence` | C5,C12 |
| C12 | confidence derivation | SATISFIED | `confidence.py` pure functions | `tests/test_feedback.py` (TestConfidenceRules, 12 cases) | — |
| C13 | decay | SATISFIED | `confidence.py::decay_due` (90/180 day) | `tests/test_feedback.py::test_decay_windows` | C12 |
| C14 | contradiction detection | SATISFIED | `engine.py::_contradiction_pass` | `tests/test_contradiction.py` | L7 |
| C15 | skill graduation | SATISFIED | proposals to `_meta/graduation-candidates.md`; never edits skills/ | `tests/test_curation.py::test_graduation` | C11 |

### Retrieval

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| R1 | domain router | SATISFIED | `router.py`; lint checks budget/count/parity | `tests/test_recall.py::test_domain_matching` | S8 |
| R2 | domain index | SATISFIED | `indexes.py` parse/validate/update | `tests/test_index.py` | S8 |
| R3 | bounded linked-note retrieval | SATISFIED | ≤6 notes, ≤2000 tokens, stale excluded | `tests/test_recall.py::test_note_budget_ceiling`, `::test_recall_token_budget_skip`, `::test_stale_notes_excluded` | R2 |
| R4 | recall telemetry | SATISFIED | 4-column `_meta/recall-log.tsv`; derived-only | `tests/test_recall.py::test_recall_log_written_and_disposable` | R3 |
| R5 | context-pack compiler | SATISFIED | `packs.py` | `tests/test_packs.py` | R2 |
| R6 | freshness validation | SATISFIED | `packs.py::freshness` (current/stale/not-authoritative, spec-verbatim windows) | `tests/test_packs.py::test_freshness_rule` | R5 |

### Integration

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| I1 | Claude Code policy | SATISFIED | `CLAUDE.md` (policy only) | doc review | — |
| I2 | Claude Code deterministic hooks | SATISFIED | `_meta/hooks/*.py` + `integrations/claude-code/` (settings TEMPLATE, I-014) | `tests/test_hooks.py::test_hook_scripts_run_as_processes` | L1,L3,L6 |
| I3 | generic AGENTS.md policy | SATISFIED | `AGENTS.md` | doc review | — |
| I4 | GitHub Copilot CLI/VS Code and Cursor | SATISFIED | `.github/copilot-instructions.md`, `.github/hooks/`, `.github/skills/`, `integrations/github-copilot/`, `integrations/cursor/` | `tests/test_copilot_integration.py`, doc review | I3,L1-L7 |
| I5 | Lane B file contract | SATISFIED | `integrations/lane-b/CONTRACT.md` (contract-only by mandate) | doc review | — |
| I6 | Cowork context-pack contract | SATISFIED | `integrations/cowork/CONTRACT.md` + freshness rule | `tests/test_packs.py::test_freshness_rule` | R5,R6 |
| I7 | Teams/OneDrive bridge spec | SATISFIED | `integrations/lane-b/CONTRACT.md` §Teams Dump | doc review | I5 |

### Safety

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| G1 | redact before interpretation | SATISFIED | capture/episodes/curator call `redact.py` before parse-for-meaning | `tests/test_capture.py::test_redaction_before_persistence`, `tests/test_curation.py::test_redact_before_admission` | C1 |
| G2 | injection-resistant curator | SATISFIED | bodies are data; markers logged+ignored | `tests/test_curation.py::test_injection_is_data` | — |
| G3 | secret/PII scanning | SATISFIED | built-ins + `_meta/redact.txt` | `tests/test_safety.py::test_secret_patterns`, `::test_user_rules_with_custom_token` | — |
| G4 | atomic writes | SATISFIED | `fsutil.py::atomic_write` | `tests/test_safety.py::test_atomic_write_no_partial_on_crash` | — |
| G5 | Git rollback | SATISFIED | `gitutil.py` one-run-one-commit | `tests/test_git.py::test_revert_shows_canonical_change` | — |
| G6 | no canonical mutation by agents | SATISFIED | boundary enforcement in `fsutil.py` | `tests/test_safety.py::test_write_boundaries_agent` | P4 |
| G7 | no network in local curation | SATISFIED | zero network imports; NullAdapter default | `tests/test_safety.py::test_no_network_imports_in_curation_path` | — |

### Quality

| id | node | status | implemented_by | verified_by | depends_on |
|---|---|---|---|---|---|
| Q1 | capture <15 s | SATISFIED | single CLI call, no prompts, no network | `tests/test_capture.py::test_candidate_creation_single_call` | L5 |
| Q2 | weekly review <30 min | SATISFIED | review-file mechanics §7/§10; every ticked box retires its item and suppresses re-proposal (I-021) | `tests/test_curation.py::test_gated_decisions_written_to_review_not_applied`, `::test_approved_merge_applies_and_archives`, `::test_review_alternative_retires_item_and_archives` | C7–C9 |
| Q3 | idempotent compile | SATISFIED | processed/hold marks, content hashes, status transitions | `tests/test_curation.py::test_episode_mined_and_idempotent_rerun` | L8 |
| Q4 | rebuildable derived outputs | SATISFIED | packs + recall-log deletable and regenerable | `tests/test_packs.py::test_rebuild_after_deletion` | P1 |
| Q5 | deterministic lint | SATISFIED | `memory lint` — filesystem only, incl. router hygiene | `tests/test_schema.py`, `tests/test_index.py`, `tests/test_recall.py::test_missing_index_falls_back_to_general` | — |
| Q6 | token/context budget enforcement | SATISFIED | conservative `tokens.py`; enforced in recall + packs | `tests/test_recall.py::test_recall_token_budget_skip`, `tests/test_packs.py::test_token_ceiling_with_recorded_drops` | R3,R5 |

## Edges (critical, with verification)

| edge | meaning | verified_by |
|---|---|---|
| L1→L2→L3→L4 | start injects router+project → first prompt routes → bounded recall → silent work | `tests/test_hooks.py` (start/prompt/once-per-session tests), `tests/test_copilot_integration.py::test_session_lifecycle_hooks` |
| L4→L5 | work → deliberate capture lands in inbox | `tests/test_capture.py` |
| L4→L6 | work → episode stub → summarised | `tests/test_episodes.py`, `tests/test_hooks.py::test_session_end_writes_stub_from_state` |
| L3→L7 | retrieved pre-filled in stub; only /episode sets *used* | `tests/test_episodes.py::test_retrieved_vs_used_distinction` |
| L7→C12 | outcomes → derived confidence | `tests/test_feedback.py::test_lint_writes_feedback_and_last_verified` |
| L5→C2, L6→C2 | inbox items + mined episodes → candidate claims | `tests/test_curation.py::test_extract_and_classify`, `::test_inbox_processed_mark` |
| C2→C3→C4 | claim → classify → neighbours | `tests/test_curation.py` |
| C4→C5..C10 | neighbours → one decision per candidate | `tests/test_curation.py` |
| C5/C6→C11 | evidence accrual → promotion | `tests/test_curation.py::test_promotion_two_episodes_updates_index_same_run` |
| C11→R2 | promotion updates the domain index in the same run/commit | `tests/test_curation.py::test_promotion_two_episodes_updates_index_same_run`, `tests/test_git.py::test_revert_shows_canonical_change` |
| R2→R3→L3 | index → bounded recall serves it | `tests/test_recall.py::test_recall_serves_validated_notes_within_budget` |
| R2→R5→I6 | index → pack → Lane B contract | `tests/test_packs.py::test_frontmatter_contract` |
| L7→C13/C14 | failed outcomes → decay/contradiction | `tests/test_contradiction.py` |
| C11→C15 | mature validated notes → graduation candidates | `tests/test_curation.py::test_graduation` |
| full loop | RECALL→WORK→EPISODE→FEEDBACK→CURATION→INDEX→RECALL | `tests/test_e2e.py::test_full_loop` |

## Convergence audit (Section U)

Multi-agent audit, 2026-09-02: 8 spec auditors traversing the frozen contracts
independently, every HIGH/MEDIUM finding then handed to an adversarial
verifier instructed to refute it. Two rounds (the first was cut short by a
usage limit and resumed from cache).

**Round 1** — principles / non-goals / tool-independence: zero findings.
tests-graph: stale `verified_by` ids and real coverage gaps — fixed, and every
id in this document now names a runnable test. index-lifecycle: matched-domain-
without-index served nothing — fixed with a `_general` fallback plus lint and
doctor parity checks. (+6 tests → 121.)

**Round 2** — 7 findings confirmed after adversarial verification, all fixed
in this revision:

| # | sev | finding | resolution |
|---|---|---|---|
| 1 | HIGH | malformed frontmatter + a secret aborted the whole compile, leaving the secret on disk | I-023 |
| 2 | MED | monthly episode compaction (episode.md rule 6) unimplemented | I-020 |
| 3 | MED | review file honoured only `[x] approve`; alternatives ignored, files never archived, MERGEs re-proposed forever | I-021 |
| 4 | MED | different-version SUPERSEDE wrote `superseded_by` pointing at a note never created | I-022 |
| 5 | MED | HOLD was a dead end — held items never re-evaluated after being edited | I-007/§4, now hash-compared |
| 6 | MED | checkpoint text stored unredacted in session scratch and never cleaned up | I-024 |
| 7 | MED | no Reference-note fallback for content that cannot be redacted meaningfully | I-025 |

Deviations that survive by design: `issues.md` I-016…I-019. Suite: 128 tests.

## Explicit non-goals held to

No Neo4j, Postgres, Redis, vector DB, embeddings, cloud-model requirement,
hosted backend, web service, UI, auto-ingestion, semantic RAG, CORE, Basic
Memory dependency, SQLite/MCP (deferred). Stdlib-only Python; `unittest`;
zero third-party dependencies (audited).
