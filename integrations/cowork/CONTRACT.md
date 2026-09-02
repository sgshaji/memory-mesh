# Cowork integration contract

Status: CONTRACT ONLY — wire it by installing the three vault skills into
Cowork and pointing them at the OneDrive folders from
`../lane-b/CONTRACT.md`. Nothing in Cowork reaches the vault directly.

- **RECALL** — the `knowledge-recall` skill reads
  `AI-Memory/context/<domain>-current.md`, applies the freshness rule, and
  quotes `generated_at` in its first reply.
- **CONTRIBUTE** — the `capture-learning` skill writes
  `AI-Memory/inbox/<date>-cowork-<slug>.md` (shape:
  `_meta/templates/candidate.md`). OneDrive sync delivers it; the local
  curator moves it into `00-inbox/`.
- **FEEDBACK** — the end-of-task step of any task that used a pack writes an
  episode file (shape: `_meta/templates/episode.md`) with retrieved notes
  and outcomes for the ones actually used, into `AI-Memory/episodes/`.

Everything crosses as files; the local curator redacts again on ingest.
