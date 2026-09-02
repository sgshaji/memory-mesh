---
type: meta
title: Episode contract
version: 1.0
updated: 2026-09-02
---

# Episode contract — what a session must leave behind

An episode is a compact record of one working session or one meeting. It is **append-only, first-party by default, and allowed to be messy**. It is not knowledge; the curator decides what, if anything, it teaches.

## When one is written

| Trigger | Mechanism | Tool |
|---|---|---|
| Session ends | `SessionEnd` hook writes the stub and a transcript reference; `/episode` or the nightly compile fills the body | Claude Code |
| Task wraps up | End-of-task step of the skill writes the file into the Cowork folder → OneDrive → `episodes/` | Cowork |
| Session ends | Instruction file plus an `/episode` prompt (no hooks in these hosts yet) | VS Code Copilot, Copilot CLI, Cursor |
| Meeting ends | Transcript → meeting-note step (Lobster pattern) | Teams |

A session under ten minutes with no decision, failure or candidate learning may leave only a minimal episode, but it must still preserve any *Knowledge retrieved*. A session that retrieved nothing may skip the episode. Everything else writes one.

## File

`episodes/YYYY-MM-DD-<tool>-<slug>.md` — one per session. Never edited after `status: mined`, except to redact.

```yaml
---
type: episode
tool: claude-code                    # source tool
project: copilot-studio-skills       # matches a projects/ note, or none
domains: [copilot-studio]            # from knowledge/_index/_domains.md
captured: 2026-09-02T17:40:00+05:30
duration_min: 45
trust: first-party                   # mixed if the session leaned on web or email content
sensitivity: checked                 # checked | redacted — never absent
status: summarised                   # raw → summarised → mined
session_ref: local transcript id or path (never a URL to confidential content)
---
```

## Body — seven sections, in this order

```markdown
# Session: <one line>

## Goal
What the session set out to do. One or two lines.

## What happened
- tried A → failed because …
- changed B → worked
Short, chronological bullets. Keep the dead ends; they are the valuable part.

## Decisions
- <decision> — <why>

## Problems
- <what broke; short error text; environment or version>

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]
- [[skill-atomicity]]

## Knowledge used
- [[validation-order]] — held — validator passed after applying the sequence
- [[cs-optional-properties]] — failed — Copilot Studio 2026-09 build; behaviour appears changed

## Candidate learnings
- <observation that might generalise> (tool, version)
```

**Knowledge retrieved preserves rebuildable telemetry; Knowledge used closes the feedback loop.** `SessionEnd` copies every injected note into *Knowledge retrieved*. `/episode` adds every note that was actually exercised to *Knowledge used*, with an outcome from `held | failed | unclear | not-applicable` and a short reason. A note may remain only under *Knowledge retrieved* when it was never used. The curator derives `served` from the union of both sections, so disposable recall telemetry is never canonical.

## Rules

1. **Redact at capture.** No customer names, tenant ids, internal URLs, credentials or verbatim confidential text. Use `[customer]`, `[tenant]`, `[internal doc → Reference note]`. Set `sensitivity: redacted` when anything was removed.
2. **Records, not claims.** Write what happened. Generalisations go only under *Candidate learnings*, phrased as observations ("X behaved Y when Z"), never as rules.
3. **Length.** Target 400 words or fewer. A long session earns a longer *What happened*, not an essay.
4. **Trust.** If the session summarised web or email content, set `trust: mixed` and prefix those bullets with `(read)`.
5. **Append-only.** The curator changes episode processing metadata only: `status: mined` and, optionally, `mined: [<notes it produced>]`. It never adds `processed:` to an episode. Nothing else changes.
6. **Compaction.** Monthly, the curator writes `episodes/_summaries/YYYY-MM.md`. Raw episodes stay; recall prefers the summary once it exists.

## Example

```markdown
---
type: episode
tool: claude-code
project: copilot-studio-skills
domains: [copilot-studio, agent-skills]
captured: 2026-09-02T17:40:00+05:30
duration_min: 45
trust: first-party
sensitivity: checked
status: summarised
session_ref: cc-7f3a
---
# Session: document-validation skill, schema stage

## Goal
Make the validation skill reject malformed tool payloads before the LLM step.

## What happened
- inspected the generated tool schema
- tried tightening the prompt → payloads still malformed
- declared optional properties explicitly in the schema → validation passed

## Decisions
- deterministic validation runs before any LLM reasoning — cheaper and reproducible

## Problems
- schema generator silently omitted optional properties (Copilot Studio, 2026-09 build)

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]
- [[skill-atomicity]]

## Knowledge used
- [[validation-order]] — held — sequence worked as documented
- [[cs-optional-properties]] — held — fix applied exactly as the note says

## Candidate learnings
- schema generator drops optional properties unless declared (copilot-studio, 2026-09)
```
