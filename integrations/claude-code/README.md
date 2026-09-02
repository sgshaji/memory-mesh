# Claude Code integration (V1 reference host)

Status: hook SCRIPTS are implemented and tested (`tests/test_hooks.py` runs
them as real processes with JSON stdin). The settings wiring below is a
TEMPLATE — hook event names and payload fields vary by Claude Code version,
so verify against your installed version's `/hooks` docs before enabling
(mandate §O; the scripts read stdin defensively and tolerate missing keys).

## Wiring

Merge `settings-template.json` into your Claude Code settings (project
`.claude/settings.json` or user settings). Each entry runs a small script
from `_meta/hooks/`:

| Event | Script | Effect |
|---|---|---|
| SessionStart | `recall_start.py` | prints router + matching project note (becomes context) |
| UserPromptSubmit | `recall_domain.py` | first prompt only: domain-matched bounded recall |
| PreCompact | `episode_checkpoint.py` | checkpoint so long sessions lose nothing |
| SessionEnd | `episode_stub.py` | episode stub with *Knowledge retrieved* pre-filled |

The automatic-memory budget is three operations per session (start, domain
recall, end). `recall_domain.py` self-limits to the first prompt.

## Commands

- `/learn` → the `capture-learning` skill → `memory learn`
- `/episode` → the `episode` skill → fill the stub → `memory episode finish`

`CLAUDE.md` carries policy only; the hooks are the mechanism (P5).

The memory core has no dependency on Claude Code: everything here calls the
same `memory` CLI any other host can call.
