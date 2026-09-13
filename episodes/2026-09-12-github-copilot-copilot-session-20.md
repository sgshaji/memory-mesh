---
type: episode
tool: github-copilot
domains: [document-processing, agent-skills]
captured: "2026-09-12T12:32:54+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Validate a completed PD/AD execution trace and harden semantic and credit-efficiency gaps.

## What happened

The run archived, uploaded, verified, and marked both outputs successfully, but removed guidance needed to resolve two retained AD variants and returned narrative rather than only workflow JSON. It also retried pruning after a missing target, attempted a network shortcut in a networkless sandbox, and generated ad-hoc source extraction code. Added deterministic DOCX extraction, protected prune paragraphs, missing-target failure status, no-network/re-read guidance, archive-move integrity checks, and no-progress agent instructions. Rebuilt the upload ZIP.

## Decisions

Retained variants require retained reviewer-selection guidance. `prune` protection is explicit exact text and enforced against direct or spanning removals. DOCX source extraction writes detailed JSON locally and returns only a compact summary.

## Problems

The existing prune status omitted `not_found`, allowing contradictory success. This was fixed and regression-tested.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- `held` — `validation-order`: semantic protection and missing-target conditions now fail deterministically before deployment.

## Candidate learnings

Captured `00-inbox/2026-09-12-github-copilot-protect-reviewer-guidance-when-retaining-documen.md`.
