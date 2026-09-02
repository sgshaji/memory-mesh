---
type: build
title: Implementation log
updated: 2026-09-02
---

# Implementation log

## Slice 1 — repo baseline
- Frozen the six contracts under `_meta/spec/` (commit e28b292); .gitignore
  marks derived state (packs, recall-log, session-state) as untracked.
- Graph nodes: S12 partially; edges: none yet.

## Slice 2 — control plane
- `requirements-graph.md` (all nodes/edges), `issues.md` (15 resolved
  spec ambiguities I-001…I-015).

## Slice 3 — foundations
- `config.py` (vault layout, budgets, write-boundary sets), `frontmatter.py`
  (strict YAML-subset parser/serialiser, I-003), `fsutil.py` (atomic writes,
  safe slugs, traversal guard, agent/curator write boundaries), `tokens.py`
  (conservative estimator, I-008), `redact.py` (built-in secret/tenant/URL
  patterns + `_meta/redact.txt`, injection markers).
- Nodes: G1 G3 G4 G6 P4 P10 Q6(partial). Tests: test_frontmatter, test_safety.

## Slice 4 — notes, schema, router, indexes
- `notes.py` (observations/relations conventions, ref resolution),
  `schema.py` (vocabularies + deterministic validation), `router.py`
  (router table, hyphen-normalised keyword matching), `indexes.py`
  (fixed sections, derived link count, validation).
- Nodes: P2 P7 S3–S8 R1 R2 Q5. Tests: test_schema, test_index.

## Slice 5 — lifecycle surfaces
- `capture.py` (/learn: redact-before-write, hash idempotence I-011),
  `episodes.py` (stub/checkpoint/finish/mined; retrieved-vs-used enforced;
  redaction as the only post-mined edit I-012), `recall.py` (bounded recall,
  4-column recall-log, disposable session state I-013), `gitutil.py`
  (curator-only staging, I-006), `packs.py` (compiler + freshness R6).
- Nodes: L1–L7 S1 S2 R3 R4 R5 R6 Q1 Q4. Tests: test_capture, test_episodes,
  test_recall, test_packs, test_git.

## Slice 6 — curator
- `curator/engine.py` (compile: redact → extract → classify → neighbours →
  decide; lint: tally I-007, confidence, decay, contradictions, duplicates,
  orphans, index hygiene, inbox pressure, graduation), `neighbours.py`
  (lexical), `decisions.py`, `review.py` (checkbox blocks + machine payload),
  `adapter.py` (NullAdapter default; no-model → HOLD/review, never
  hallucinated confidence).
- Fix during build: identical claim from a NEW episode routes to UPDATE
  (+evidence) instead of duplicate-hash skip — otherwise the two-episode
  promotion rule could never fire.
- Nodes: L8 C1–C15 G2 G5 G7 P3 P8 Q2 Q3. Tests: test_curation,
  test_contradiction, test_feedback.

## Slice 7 — CLI, hooks, seed, docs
- `cli.py` (learn/recall/episode/session-*/compile/curate/lint/pack/status/
  doctor), `_meta/hooks/*` (defensive stdin JSON, I-014), live vault seed +
  `tests/fixtures/vault` (Section R dataset), four SKILL.md files, CLAUDE.md,
  AGENTS.md, README, integrations (claude-code template; lane-b/cowork
  contracts; vscode/cursor instructions — honestly labelled by grade).
- Nodes: I1–I7 P5 P6 P9 S9–S12 L1–L3 edges. Tests: test_hooks, test_e2e.

## Test state
- 128 tests, all passing (`python -m unittest discover -s tests`).
- `memory lint` on the live vault: 0 errors, 0 warnings.
- Calibration during first runs: router hyphen/space normalisation;
  classifier checks fix-words before fail-words; CREATE similarity threshold
  0.25, UPDATE 0.6 (middle band HOLDs for review — no-model safety).

## Slice 8 — convergence audit (Section U), two rounds
Eight independent spec auditors + adversarial verifiers; see
`requirements-graph.md` §Convergence audit for the table.

Round 1 fixes: `_general` fallback when a matched domain has no index (plus
lint/doctor parity checks and indexes seeded for all six declared domains);
pack freshness now uses the spec's 2×-window rule; PreCompact checkpoints keep
their original timestamp; episode word budget warns at 400 not 800; every
`verified_by` id in the graph corrected to a real test. +6 tests.

Round 2 fixes (7 confirmed findings): redaction survives malformed frontmatter
without aborting the run (HIGH); monthly episode compaction implemented as
deterministic aggregation; review alternatives retire their item and suppress
re-proposal via `_meta/review/decided.tsv`; no dangling `superseded_by`;
HOLD releases when the item changes (hash over frontmatter+body); session
scratch redacted and deleted after the stub is written; Reference-note
fallback for items too sensitive to admit as claims. +7 tests → 128.

## Open items / discovered gaps
- Claude Code settings wiring is a TEMPLATE pending verification against the
  installed host version (I-014) — scripts themselves are process-tested.
- Lane B is contract-only by mandate (§I): no OneDrive automation shipped.
- Adapter layer ships with NullAdapter only; a local-model adapter is a
  V1.x extension point behind the existing interface.
