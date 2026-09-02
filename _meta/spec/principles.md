---
type: meta
title: Principles
version: 1.0
updated: 2026-09-02
---

# Principles of the Personal AI Memory & Knowledge System

Ten rules. Every contract in `_meta/` derives from them. If a contract and a principle disagree, the principle wins and the contract is wrong.

1. **Markdown is the only source of truth.** Indexes, packs, databases, telemetry logs and tool memories are derived and disposable. Delete them; rebuild them from episodes and canonical notes.
2. **Three tiers, never mixed.** `episodes/` remember what happened. `knowledge/` preserves what is worth knowing. `skills/` encode what is worth doing repeatedly.
3. **Experience is not truth.** An episode is a record and may be messy. Only the curator turns records into claims, and only with evidence.
4. **Agents propose; the curator writes; you gate.** Agents read, search, contribute and report. CREATE and UPDATE auto-commit with attribution. MERGE, SUPERSEDE and REJECT wait for a human.
5. **Mechanism over instruction.** If failing to perform an action breaks the lifecycle, use a deterministic hook wherever the host tool offers one. Instructions shape behaviour; hooks guarantee it.
6. **Smallest relevant context.** Recall is one domain index and three to six linked notes, inside a token budget. Never the vault.
7. **Every claim carries evidence and a clock.** `applies_to`, `first_observed`, `last_verified` and feedback counts. Confidence is derived, never asserted.
8. **Feedback closes the loop.** Every episode records which knowledge was used and whether it held. Trust, decay and supersession follow from that, not from opinion.
9. **Tool-native memory is convenience state.** Preferences and continuity only. Never evidence, never canonical, never cited.
10. **Nothing confidential enters the vault.** Customer and tenant specifics become Reference notes pointing at the original location; episodes are redacted at capture.

**North star:** every AI tool can retrieve relevant prior context, contribute something worth remembering, and report whether the knowledge it used actually held.

**Acid test:** capture in under 15 seconds, curation in under 30 minutes a week. If either fails, fix the system, not the habit.
