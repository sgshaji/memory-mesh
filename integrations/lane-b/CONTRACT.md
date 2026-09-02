# Lane B — file contract (Cowork · Copilot Studio · M365 Copilot · Teams)

Status: CONTRACT ONLY. No OneDrive/Power Automate code ships in V1 (mandate
§I); everything crosses as files. Nothing in Lane B reaches the vault
directly.

## Outbound: context packs (vault → cloud)

The curator regenerates `outputs/context/<domain>-current.md` after every
run. A sync job (OneDrive client, robocopy, anything) mirrors that folder to:

    OneDrive: AI-Memory/context/<domain>-current.md

Pack frontmatter (consumer-visible contract):

    type: context-pack
    domain: <domain>
    generated_at: <ISO timestamp with offset>
    valid_until: <generated_at + 7 days>
    source_commit: <git short sha or "uncommitted">
    source_index: knowledge/_index/<domain>.md
    token_estimate: <int, hard ceiling 2000>
    status: current

Consumer freshness rule (verbatim into every Lane B skill):
- `now ≤ valid_until` → use normally and quote `generated_at`.
- expired → say "context pack is N days stale" and continue.
- expired by more than twice the window → not authoritative; propose no
  changes based on it.

## Inbound: candidates and episodes (cloud → vault)

Cloud skills write Markdown files (never edits to existing vault files) to:

    OneDrive: AI-Memory/inbox/<YYYY-MM-DD>-<source>-<slug>.md      → 00-inbox/
    OneDrive: AI-Memory/episodes/<YYYY-MM-DD>-<tool>-<slug>.md     → episodes/

File shapes: `_meta/templates/candidate.md` and `_meta/templates/episode.md`.
A local drop-folder watcher (or the human) moves files in; the local curator
redacts AGAIN on ingest (defence in depth) and processes them like any input.

## Teams Dump bridge (specification)

Channel `AI-Memory Dump` → Power Automate: on new message →
1. redact BEFORE file creation (customer/tenant strings, deep links);
2. create `AI-Memory/inbox/<timestamp>.md` containing only the sanitised
   message, a sender classification, and an opaque source reference id —
   never a resolving deep link;
3. the local watcher assigns `trust: first-party` when the author is you,
   `third-party` when the message summarises an external source.

Customer data, tenant data and sensitive deep links never enter OneDrive or
the vault. Where provenance matters, keep a system name plus a
non-resolving reference id, or create a Reference note pointing at the
original location.
