# Cursor integration

Status: INSTRUCTION-GRADE (no lifecycle hooks in Cursor yet).

Create `.cursor/rules/memory-mesh.mdc` in projects that should use the vault:

    ---
    description: Memory Mesh vault policy
    alwaysApply: true
    ---
    Before substantive work run `memory recall "<task>"` (vault at
    <path-to-vault>) and follow at most six links from the served index.
    Capture insights with `memory learn "..." --tool cursor`.
    Before ending a session that made decisions, follow
    skills/episode/SKILL.md and run `memory episode finish`.
    Never edit knowledge/, knowledge/_index/ or skills/ — propose via /learn.

The full policy lives in the vault's `AGENTS.md`; keep the rule file short
and defer to it.
