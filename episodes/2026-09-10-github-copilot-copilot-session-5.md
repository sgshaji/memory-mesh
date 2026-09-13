---
type: episode
tool: github-copilot
domains: [agent-skills, document-processing]
captured: "2026-09-10T12:53:28+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal
Change the PD/AD conversion skill so every converted template is saved in the source file's parent
folder under the source's exact filename, with prior content retained in `Archive`.

## What happened
Updated the skill instructions and deterministic destination helper. Both PD and AD outputs now use
the same destination. Removed converted-template folders, AD root placement, and shortcut behavior.
Validated Python compilation and asserted the destination JSON contract for an AD invocation.

## Decisions
- Apply the new placement rule to both PD and AD outputs.
- Preserve the exact source filename and extension.
- Archive the original source on the first run, then archive each current conversion before the next.
- Process every supplied template; only the final template's conversion remains current.
- Stop before upload if archiving is unavailable.

## Problems
Exact-name output necessarily collides with the original source. This was resolved explicitly by
archiving the original before the first upload. Generated-state guidance was corrected so the
archived original remains unmarked while converted documents are marked generated.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — held — destination rules were encoded and checked deterministically before
  relying on prose behavior.
- [[projects/copilot-studio-skills]] — not-applicable — project context was related but did not affect
  this separate conversion skill.

## Candidate learnings
None; the decisions are workflow-specific rather than broadly reusable.
