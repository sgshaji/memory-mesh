---
type: build
title: Specification issues, ambiguities and resolutions
updated: 2026-09-02
---

# Build issues log

Contradictions/ambiguities found during spec traversal, with the chosen (safest,
reversible, minimal) interpretation. principles.md wins on conflict.

## I-001 — hook script location: `_meta/hooks/` vs `integrations/claude-code/`
session-lifecycle.md places hook scripts in `_meta/hooks/`; the build mandate
(Section O) isolates host-specifics under `integrations/claude-code/`.
**Resolution:** deterministic, host-agnostic hook entry points live in
`_meta/hooks/` (they only call the `memory` CLI); Claude-Code-specific settings
templates, payload adapters and docs live in `integrations/claude-code/`. The
memory core imports nothing from either. Severity: LOW. Status: resolved.

## I-002 — `ai-knowledge/_meta/hooks/` path in session-lifecycle.md
The spec references `ai-knowledge/_meta/hooks/` — a stale vault name. This repo
is `memory-mesh/`; the path is `_meta/hooks/` relative to the vault root.
Severity: LOW. Status: resolved (documented, spec left frozen).

## I-003 — YAML dependency vs stdlib
Frontmatter is YAML. Mandate allows one focused YAML dependency but prefers
stdlib (<100 lines). The vault's frontmatter is a controlled subset (scalars,
ISO dates, inline lists/dicts, one nesting level). **Resolution:** strict
stdlib subset parser in `memory_mesh/frontmatter.py`; malformed or
out-of-subset YAML is a lint error, which the schema wants anyway. Zero
third-party dependencies repo-wide (tests use `unittest`). Reversible: swap in
PyYAML behind the same two functions later. Severity: LOW. Status: resolved.

## I-004 — "processed:" vs episode lifecycle
curator.md §2 is explicit: inbox items get `processed: <run-id>`; episodes
transition `summarised → mined` and never receive `processed:`. Mandate
clarification 4 confirms. Implemented exactly so. Status: resolved.

## I-005 — who writes `status: summarised`?
session-lifecycle.md: `/episode` or nightly `episode-compile` fills raw stubs.
episode.md's example shows `/episode` output as `summarised`. Deterministic
code cannot summarise (Section G). **Resolution:** `memory episode finish`
validates a filled body (all seven sections, retrieved⊆served logic, word
budget) and flips `raw → summarised`; the *content* comes from the agent/human
while context is warm. Without a model, stubs stay `raw` — valid, mineable
later. The curator never fakes summarisation. Severity: MEDIUM. Status: resolved.

## I-006 — auto-commit vs dirty user tree
curator.md §1: every run commits as author `curator`; a failed run leaves no
partial commit. Mandate Section N: never swallow unrelated user changes.
**Resolution:** the curator stages **only** paths it owns (knowledge/,
episodes/ status flips, 00-inbox/ processed marks, _meta/curation-log.md,
_meta/review/, _meta/graduation-candidates.md, outputs/context/ is gitignored)
and commits only those. Unrelated dirty files are left untouched and reported.
If `git` itself is unavailable or the repo is absent, changes are written and
the run reports "manual commit required" — canonical writes are still atomic
per file. Severity: MEDIUM. Status: resolved.

## I-007 — `served` derivation window
curator.md §3 says "episodes since the last run". Tracking a run watermark adds
state that must be reconstructable. **Resolution:** tally is recomputed from
**all** episodes' *Knowledge retrieved* ∪ *Knowledge used* on every lint —
idempotent, watermark-free, and consistent with P1 (rebuild from canonical
files). `feedback` counts are therefore absolute totals, not increments.
Severity: LOW. Status: resolved.

## I-008 — token estimation
No tokenizer dependency allowed. **Resolution:** conservative estimator
`ceil(max(chars/3.5, words*1.34))` — deliberately over-counts (real Markdown
prose runs ~4 chars/token), so budget enforcement fails safe. Severity: LOW.
Status: resolved.

## I-009 — index `links:` count field
domain-index.md frontmatter carries `links: 9`. A hand-count can drift.
**Resolution:** the count is derived at write time by `indexes.py`; lint flags
drift. Severity: LOW. Status: resolved.

## I-010 — curator writes `outputs/context/*` but packs are gitignored
Packs are derived and disposable (P1); committing them would imply authority.
The pack carries `source_commit` instead, so provenance survives without
tracking. domain-index.md never requires packs in Git. Severity: LOW.
Status: resolved.

## I-011 — `/learn` idempotence
"Idempotence where reasonable": same-content same-day recapture returns the
existing candidate path (content hash match) instead of a duplicate file.
Different day or wording creates a new candidate — dedup is the curator's job
(§3 Duplicates), not capture's. Severity: LOW. Status: resolved.

## I-012 — episode append-only vs redaction
episode.md: never edited after `status: mined`, **except to redact**. The
redaction path is the single exception allowed to modify a mined episode
(and must log it). Severity: LOW. Status: resolved.

## I-013 — SessionEnd stub domain classification
The stub writer may not know domains. **Resolution:** stub records the domains
the recall hook matched this session (from the session's recall-log lines);
`[unclassified]` when none. `/episode finish` may correct it. Severity: LOW.
Status: resolved.

## I-014 — Claude Code hook payloads
Mandate Section O: do not assume hook names/payload formats without verifying.
The installed host here supports SessionStart/UserPromptSubmit/PreCompact/
SessionEnd hooks; scripts read stdin JSON defensively (missing keys tolerated,
fall back to env/args) and settings snippets are shipped as TEMPLATE with a
verification note. Severity: MEDIUM. Status: resolved (defensive design).

## I-015 — schema.md `status` vocabulary vs `unreviewed`
curator.md §3 (inbox pressure) moves stale inbox items to
`episodes/_unreviewed/` with `status: unreviewed`, which is absent from
schema.md's status vocabulary. **Resolution:** `unreviewed` is accepted only on
files under `episodes/_unreviewed/`; lint treats it elsewhere as an error.
Severity: LOW. Status: resolved.

## I-016 — episode word budget is a warning, not a gate
session-lifecycle.md budgets "Episode body ≤ 400 words"; episode.md calls it a
target. **Resolution:** `finish` warns above 400 words but never blocks the
raw → summarised flip — losing a summary over length would hurt more than a
long one. Found by the convergence audit. Severity: LOW. Status: resolved.

## I-017 — context packs may carry an "Omitted for budget" section
domain-index.md says the pack body is the index sections "nothing else". When
the 2,000-token ceiling forces entries out, the pack appends an
`## Omitted for budget` list — the mandate's no-silent-caps rule (Q) wins
over body purity; the section counts inside the ceiling. Severity: LOW.
Status: resolved.

## I-018 — SessionStart telemetry lives in session state, not recall-log
session-lifecycle.md's wiring table says `recall-start` appends to
recall-log.tsv, but domain-index.md fixes recall-log at exactly one 4-column
line per injected note. The 4-column contract wins: session-start telemetry
goes to disposable `_meta/session-state/`; recall-log gains lines only when
notes are served. PreCompact checkpoints parked before the stub exists keep
their original timestamp in session state and are folded in with it.
Severity: LOW. Status: resolved (audit finding).

## I-020 — monthly compaction is deterministic aggregation, not summarisation
episode.md rule 6 assigns monthly `episodes/_summaries/YYYY-MM.md` to the
curator, but deterministic code cannot summarise (mandate §G). **Resolution:**
`_compaction_pass` writes a *digest*, not a summary — each mined episode's
goal line, decisions, problems and knowledge outcomes carried verbatim. Only
complete months compact; existing summaries are never rewritten; raw episodes
stay. The spec's "recall prefers the summary once it exists" clause has no
consumer in V1 because recall reads `knowledge/`, never `episodes/`; that
clause activates only if episode-backed recall is ever added. Severity: MEDIUM
(found by the convergence audit). Status: resolved.

## I-021 — review alternatives are decisions, and are remembered
curator.md §7 offers "keep both", "hold", "keep as candidate" and "edit"
alongside "approve", and says ticking a box is the decision. V1 originally
parsed only `[x] approve`, so alternatives were silently ignored, the file
never archived, and duplicate MERGEs were re-proposed every run.
**Resolution:** every ticked box retires its item; non-approve choices append
to `_meta/review/decided.tsv` and suppress regeneration of that exact
proposal (MERGE pair, SUPERSEDE target, REJECT target). New evidence still
reopens a claim through compile. HOLD/FLAG notices retire on
`[x] acknowledged`. Severity: MEDIUM (audit). Status: resolved.

## I-022 — a supersession without a successor records no `superseded_by`
The lint contradiction pass can propose SUPERSEDE before any replacement note
exists. Writing `superseded_by: <ref>` for a note that was never created
leaves a dangling link and breaks §6's promise that history stays navigable.
**Resolution:** when there is no successor, the window closes
(`applies_to.to`) and `superseded_by` stays null; the successor arrives later
with its own evidence through compile. Severity: MEDIUM (audit).
Status: resolved.

## I-023 — redaction must survive malformed frontmatter
An inbox item with unparseable frontmatter *and* a secret used to abort the
whole compile run — leaving the secret on disk, nothing else processed and
nothing committed. **Resolution:** `_redaction_pass` writes the redacted text
back verbatim when the document will not parse, reports it, and the item is
skipped for claim extraction only. Bridges (Teams/OneDrive) feed the inbox, so
malformed input is expected, not exceptional. Severity: HIGH (audit).
Status: resolved.

## I-024 — session scratch is redacted and short-lived
PreCompact checkpoints parked raw user-prompt text in
`_meta/session-state/<sid>.json` unredacted, and the file was never removed.
**Resolution:** checkpoint text is redacted before it touches disk (like every
other capture path), and `session-end` deletes the session's state file once
the stub carries its contents. Severity: MEDIUM (audit). Status: resolved.

## I-025 — Reference-note fallback for content that cannot be redacted
curator.md §2.1 and principle 10 require content that cannot be redacted
meaningfully to become a Reference note pointing at the original location.
V1 originally token-substituted and then mined the result, so a mostly-
confidential item could become a knowledge note built out of `[customer]` and
`[redacted-secret]` tokens. **Resolution:** deterministic density test — three
or more redaction tokens *and* tokens exceeding 20% of the words — routes the
item to a `knowledge/references/` pointer note carrying only the source
reference and the reason, and marks the item processed. No confidential
substance is admitted. Severity: MEDIUM (audit). Status: resolved.

## I-019 — index `links:` counts recall-feeding sections only
domain-index.md's example counts every section's entries (`links: 9`); the
implementation counts and caps only Read first / Known failures / Current
workarounds / Active project. Rationale: the twelve-link cap protects bounded
recall, and Recently verified / Recently changed are curator-maintained
mirrors whose growth must never evict live links. Severity: LOW.
Status: resolved (documented interpretation).
