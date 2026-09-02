---
type: meta
title: Session integration contract
version: 1.0
updated: 2026-09-02
---

# Session integration contract — start, end, and hook versus instruction

Every tool gets three abilities: **RECALL** (the smallest relevant prior context), **CONTRIBUTE** (something worth remembering) and **FEEDBACK** (what knowledge was used, and whether it held). This contract says how each is delivered per tool and which parts are deterministic.

## The lifecycle

```
SESSION START   hook injects the router and the matching project note
FIRST PROMPT    hook matches the domain, injects its index; agent follows 3–6 links (≤ 2,000 tokens)
WORK            normal; memory is silent
DISCOVERY       /learn <observation> → 00-inbox/ — no interruption
TASK CHANGE     agent re-reads the new domain's index (instruction)
SESSION END     hook writes the episode stub and transcript reference; /episode or the nightly compile fills the body
LATER           curator mines inbox and episodes (curator.md)
```

Automatic memory acts at most three times per session: start, domain recall and end. Never per message. Deliberate `/learn` captures are user- or agent-triggered and do not count against this budget.

## Per-tool matrix

| Ability | Claude Code | Cowork | VS Code Copilot · Copilot CLI · Cursor | Copilot Studio · M365 Copilot | Phone |
|---|---|---|---|---|---|
| RECALL | **Hook** — `SessionStart` injects `_domains.md` and the project note; `UserPromptSubmit` (first prompt) injects the matched index | Skill reads `AI-Memory/context/<domain>-current.md` from OneDrive, honours the freshness rule | Instruction file (`AGENTS.md`, `.cursor/rules`) → read the index; hook when the host offers one | Skill or instruction reads the context pack | — |
| CONTRIBUTE | `/learn` command → `00-inbox/` file | Skill writes a candidate file to the Cowork folder → OneDrive → inbox | `/learn` prompt → file | "Save this learning" → Teams Dump → Power Automate → OneDrive → inbox | Teams Dump post |
| FEEDBACK | **Hook** — `SessionEnd` writes the stub with *Knowledge retrieved* pre-filled from session telemetry; `/episode` records which notes were used and sets outcomes | End-of-task step writes the episode with retrieved notes and outcomes for those used | `/episode` prompt | Not available; feedback arrives through later local sessions | — |
| Grade | deterministic | instruction | instruction | bridge | bridge |

Where a cell says *instruction*, that is a known gap. The weekly review asks "which sessions left no episode?" and treats the answer as backlog, not failure.

## Claude Code wiring — the V1 reference implementation

Hooks are configured in the Claude Code settings `hooks` section; each runs a small script from `ai-knowledge/_meta/hooks/`.

| Event | Script | What it does |
|---|---|---|
| `SessionStart` | `recall-start` | prints `_index/_domains.md` and the `projects/` note matching the working directory to stdout (becomes context); appends disposable session telemetry to `recall-log.tsv` |
| `UserPromptSubmit` | `recall-domain` | on the first prompt of a session, keyword-matches the router and prints the matched index; marks the session as recalled; logs each injected link in disposable session telemetry |
| `PreCompact` | `episode-checkpoint` | appends a checkpoint (time, last user prompt) to the episode stub so long sessions lose nothing when context is compacted |
| `SessionEnd` | `episode-stub` | creates `episodes/<date>-claude-code-<slug>.md` with frontmatter, `status: raw`, the session's recall-log entries under *Knowledge retrieved*, and `session_ref` |

A hook is a shell script, so it cannot summarise. Two ways the body gets written:

- `/episode` — a custom command that summarises the current session into the stub while the context is warm. Preferred whenever decisions were made.
- nightly `episode-compile` (part of the curator) — fills any `status: raw` stub from its transcript reference and sets `status: summarised`.

`CLAUDE.md` then carries policy only:

> You will be given a domain index at the start of the session. Follow at most six links. Use `/learn` for anything worth remembering. Run `/episode` before ending a session that made decisions. Never edit `knowledge/` directly — propose through `/learn`.

## Cowork wiring

- **RECALL** — the `knowledge-recall` skill reads `AI-Memory/context/<domain>-current.md`, applies the freshness rule, and quotes `generated_at` in its first reply.
- **CONTRIBUTE** — the `capture-learning` skill writes `00-inbox/<date>-cowork-<slug>.md` into the Cowork folder; OneDrive sync delivers it to the vault drop folder; the local curator moves it in.
- **FEEDBACK** — the end-of-task step of any task that used a pack writes an episode file the same way.
- Nothing in Cowork reaches the vault directly. Everything crosses as files.

## Lane B bridge — Teams Dump

Channel `AI-Memory Dump` → Power Automate: on new message → redact before file creation, then create `AI-Memory/inbox/<timestamp>.md` in OneDrive with only the sanitised message, sender classification and an opaque source reference. Customer data, tenant data and sensitive deep links never enter OneDrive or the vault; retain only a system name plus a non-resolving reference id when provenance is needed. The local drop-folder watcher moves the file to `00-inbox/` with `trust: first-party` when you wrote it and `third-party` when it summarises an external source.

## Budgets

| Item | Budget |
|---|---|
| Router | ≤ 300 tokens |
| One domain index | ≤ 400 tokens |
| Notes read at recall | ≤ 6 notes, ≤ 2,000 tokens in total |
| Context pack | ≤ 2,000 tokens |
| Episode body | ≤ 400 words |
| Automatic memory operations per session | ≤ 3 — start, domain recall, end; deliberate `/learn` captures are uncapped |
