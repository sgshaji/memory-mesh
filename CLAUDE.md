# Memory Mesh — Claude Code policy

Hooks are the mechanism (see `integrations/claude-code/`); this file carries
policy only.

You will be given a domain index at the start of the session. Follow at most
six of its links. Use `/learn` (the `capture-learning` skill, or
`memory learn "..."`) for anything worth remembering. Run `/episode` (the
`episode` skill) before ending a session that made decisions. Never edit
`knowledge/` directly — propose through `/learn`; only the curator writes
canonical knowledge.

Tool-native memory (auto-memory, CLAUDE.md edits) is convenience state:
preferences and continuity only — never evidence, never canonical, never
cited as knowledge.

Working on the Memory Mesh codebase itself:
- Specs in `_meta/spec/` are frozen contracts; do not edit them casually.
- `python -m unittest discover -s tests` must pass before any commit.
- Zero third-party dependencies (stdlib only) is a design constraint, not an
  accident.
