---
type: meta
title: Domain index contract
version: 1.0
updated: 2026-09-02
---

# Domain index contract — how recall finds five notes, not five hundred

A domain index is a curated map of content: the five to twelve notes an agent should read before working in that domain. V1 recall is: classify the task → read one index → follow three to six links → stop. Context packs for cloud agents are the same selection with the note bodies inlined.

## The router: `knowledge/_index/_domains.md`

One small file (≤ 300 tokens) that the recall hook injects at session start. Each domain has a name, a one-line scope and match keywords.

```markdown
| domain | scope | match |
|---|---|---|
| copilot-studio | agents, topics, tools, knowledge sources, publishing | copilot studio, mcs, topic, agent flow, dataverse |
| cowork | skills, plugins, MCP apps, scheduled prompts | cowork, skill.md, plugin, frontier |
| coding-agents | Claude Code, Cursor, Copilot CLI behaviour and prompting | claude code, cursor, copilot cli, repo, refactor |
| agent-skills | skill design across hosts: atomicity, triggers, validation | skill, trigger, description, atomic |
| mcp | servers, transports, tool surfaces, auth | mcp, stdio, streamable, tool schema |
| document-processing | PDF and Word extraction, templates, validation | pdf, docx, template, extraction, ocr |
```

Rules: five to eight domains. A task matching two domains reads both indexes. A task matching none reads `_index/_general.md`, and the agent records `domains: [unclassified]` in its episode — the signal that a domain is missing.

## One index per domain: `knowledge/_index/<domain>.md`

```markdown
---
type: index
domain: copilot-studio
updated: 2026-09-02
links: 9                         # must stay ≤ 12
---
# Copilot Studio

## Read first
- [[capability-boundary-testing]] — test the platform limit before designing around it
- [[tool-schema-optional-properties]] — declare optional properties explicitly
- [[document-grounding-validation]] — validate grounding sources before publishing

## Known failures
- [[grounding-source-mismatch]]
- [[large-file-upload-failure]]

## Current workarounds
- [[schema-validation-workaround]]

## Active project
- [[projects/copilot-studio-skills]]

## Recently verified (30 days)
- [[tool-schema-optional-properties]] — held 2026-09-02

## Recently changed
- [[grounding-source-mismatch]] — superseded 2026-08-28 → [[grounding-source-mismatch-2026-08]]
```

Rules

- **Twelve links at most, one line each,** with a gloss of twelve words or fewer. If a thirteenth note earns a place, one leaves.
- Sections are fixed. Empty sections stay; they tell the agent there is nothing known.
- Only `validated` notes appear under *Read first* and *Current workarounds*. A note that goes `stale` moves to *Recently changed* with the reason.
- *Known failures* contains only currently applicable failures. Resolved, superseded or out-of-window failures remain in canonical knowledge but move to *Recently changed*.
- The curator, not the agent, edits indexes — on every promotion, supersession or stale transition, in the same commit.
- An index is a pointer file. Never paste note bodies into it.

## Context pack: the index, compiled

`outputs/context/<domain>-current.md` — regenerated after every curator run (and on demand), synced to OneDrive `AI-Memory/context/`, read by Cowork and Copilot Studio skills.

```yaml
---
type: context-pack
domain: copilot-studio
generated_at: 2026-09-02T18:00:00+05:30
valid_until: 2026-09-09T18:00:00+05:30      # seven days; shorter for fast-moving domains
source_commit: a8d41e7
source_index: knowledge/_index/copilot-studio.md
token_estimate: 1450                          # hard ceiling 2000
status: current
---
```

Body: the index sections, each link replaced by the note's title, `applies_to`, `confidence`, `last_verified` and its *Observations* block. Nothing else.

Consumer rule, written into every Lane B skill:

- `now ≤ valid_until` → use normally and quote `generated_at`.
- expired → say "context pack is N days stale" and continue.
- expired by more than twice the window → not authoritative; propose no changes based on it.

## Recall log

The recall hook appends one line per injected note to `_meta/recall-log.tsv`:

```
2026-09-02T17:02:11+05:30	claude-code	copilot-studio	tool-schema-optional-properties
```

This file is disposable operational telemetry used to build the episode stub during the session. It may aid diagnostics, but it is not a source of truth and may be deleted after the episode records *Knowledge retrieved*. The curator reconstructs **served** counts from episode *Knowledge retrieved* and *Knowledge used* sections (`curator.md §5`).
