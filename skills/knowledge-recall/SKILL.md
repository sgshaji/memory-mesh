---
name: knowledge-recall
description: Retrieve the smallest relevant prior context before starting a task - one domain index and 3-6 linked notes within a 2,000-token budget. Use at the start of any substantive task, or when the task changes domain mid-session.
---

# Recall knowledge

Goal: the smallest relevant context, never the vault.

## Local hosts (can run commands)

    memory recall "<the task in one sentence>" --tool <your-host-name> [--session <id>]

Read what it prints (the matched domain index + linked notes) and start
working. That is the whole recall. Do not search the vault beyond it.

## Cloud hosts (Lane B — files only)

1. Read `AI-Memory/context/<domain>-current.md` (a context pack).
2. Apply the freshness rule from its frontmatter:
   - `now ≤ valid_until` → use it; quote `generated_at` in your first reply.
   - expired → say "context pack is N days stale" and continue.
   - expired by more than twice the window → NOT authoritative; propose no
     changes based on it.

## Rules

- At most two domain indexes; at most six notes; ≤ 2,000 tokens. The tool
  enforces this — do not fetch more "to be safe".
- No domain matched means the general index was served and the episode must
  record `domains: [unclassified]` — that signal is how missing domains get
  discovered.
- Track which recalled notes you actually USE; the episode records each as
  held / failed / unclear / not-applicable at session end.
- Recall happens once per session plus once per domain change. Memory stays
  silent otherwise.
