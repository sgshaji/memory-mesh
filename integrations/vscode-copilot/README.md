# VS Code Copilot / Copilot CLI integration

Status: INSTRUCTION-GRADE (no deterministic hooks offered by these hosts
yet — session-lifecycle.md marks this lane as a known gap; the weekly review
asks "which sessions left no episode?" and treats the answer as backlog).

1. Point the host at the vault's `AGENTS.md` (Copilot reads
   `AGENTS.md`; also works as `.github/copilot-instructions.md` content).
2. RECALL: instruct the agent to run `memory recall "<task>"` — or read
   `knowledge/_index/_domains.md` and follow one index — before substantive
   work.
3. CONTRIBUTE: a `/learn` prompt runs `memory learn "..." --tool vscode-copilot`.
4. FEEDBACK: an `/episode` prompt follows `skills/episode/SKILL.md`.

When these hosts ship lifecycle hooks, wire them like
`../claude-code/settings-template.json` — the CLI surface is identical.
