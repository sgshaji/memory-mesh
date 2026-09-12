---
type: episode
tool: github-copilot
domains: [agent-skills, cowork]
captured: "2026-09-12T11:59:50+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: ed89e9cd-b56c-4b96-a8fa-7d2ccdfefdc4
---

# Session: copilot-session

## Goal

Reduce PD/AD skill context cost and externalize deployment assumptions without changing default behavior.

## What happened

Replaced the approximately 740-line monolithic skill with a 214-line control flow and four phase-specific references. Added a versioned deployment JSON for folder names, metadata column, connector name/semantic parameter mapping, writable directory, orchestration owner, and upload-overhead threshold. Python now validates configuration before deployment-aware commands and applies custom paths and thresholds. Added configuration regression coverage and future-template acceptance guidance.

## Decisions

Keep development tests in the skill source package but outside runtime prompt context. Treat live SharePoint integration as an opt-in CI/staging harness because credentials and tenant state must not be assumed by the skill. Use synthetic representative DOCX fixtures for Word mechanisms, not business field names.

## Problems

A custom-threshold report test initially used a stored-byte delta above its configured allowance. Correcting the fixture to the boundary resolved it; product logic was correct.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- `held` — `validation-order`: configuration validation now runs before planning and model-driven mapping.

## Candidate learnings

Captured `00-inbox/2026-09-12-github-copilot-progressive-disclosure-and-validated-bindings-im.md`.
