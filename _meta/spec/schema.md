---
type: meta
title: Note schema and vocabulary
version: 1.0
updated: 2026-09-02
---

# Schema

One vocabulary for every file in the vault. Frontmatter carries the lifecycle; the body carries content in Basic Memory's Observations/Relations syntax, so Obsidian, grep and (later) the MCP index all read the same file.

## Note types

| `type` | Folder | Purpose | Who may write |
|---|---|---|---|
| `candidate` | `00-inbox/` | Unprocessed `/learn` or Dump item | any agent, you |
| `episode` | `episodes/` | Record of one session or meeting; append-only | any agent, you |
| `pattern` | `knowledge/patterns/` | Reusable, cross-tool claim | curator |
| `tool-behaviour` | `knowledge/tools/` | How a specific tool or version behaves | curator |
| `workaround` | `knowledge/workarounds/` | Known fix for a known limitation | curator |
| `failure` | `knowledge/failures/` | What did not work, and why | curator |
| `reference` | `knowledge/references/` | Pointer to a document that stays where it is | curator |
| `index` | `knowledge/_index/` | Domain map of content (see `domain-index.md`) | curator |
| `project` | `projects/` | Working memory for one engagement or build | you, agents (light gate) |
| `context-pack` | `outputs/context/` | Compiled, expiring export for cloud agents | generated |
| `skill` | `skills/<name>/SKILL.md` | Executable procedure | curator proposes, you approve |

## Common frontmatter for knowledge types

```yaml
---
type: pattern                       # from the table above
title: Inspect dependents before API changes
domains: [coding-agents]            # 1–3 values from knowledge/_index/_domains.md
status: validated                   # candidate | validated | stale | resolved | superseded | rejected
trust: first-party                  # first-party | mixed | third-party | unknown
confidence: high                    # derived by the curator (curator.md §5); never hand-set
applies_to:
  tools: [claude-code]
  from: 2026-08                     # version or date window; open-ended when `to` is absent
first_observed: 2026-08-14
last_verified: 2026-09-02           # last time feedback said "held"
feedback: {served: 12, held: 10, failed: 1, unclear: 1}
evidence: [episodes/2026-08-14-claude-code-api-change, episodes/2026-08-21-claude-code-refactor]
superseded_by: null
source: /learn via Claude Code, 2026-08-14
---
```

Rules

- Dates are ISO `YYYY-MM-DD`; timestamps carry a UTC offset.
- `domains` values must exist in `knowledge/_index/_domains.md`.
- `evidence` lists episode paths without `.md`; a `validated` note needs at least one.
- Only the curator edits `status`, `confidence`, `last_verified`, `feedback`, `superseded_by`.

## Controlled vocabularies

- **status:** `candidate` → `validated` → one of `stale` | `superseded` | `rejected`; `failure` notes may also become `resolved`
- **trust:** `first-party` (you observed it) · `mixed` (observed and read) · `third-party` (read only) · `unknown`
- **outcome** (episodes, *Knowledge used*): `held` · `failed` · `unclear` · `not-applicable`
- **confidence:** `high` · `medium` · `low` — derived, see `curator.md §5`
- **relation types:** `derived_from` · `supports` · `contradicts` · `supersedes` · `mitigated_by` · `implemented_as` · `graduates_to` · `observed_in` · `relates_to`

A failure remains permanently recorded, but it is current only while `status: validated` and the applicable tool/version/date falls within `applies_to`. Set `status: resolved`, `status: superseded`, or close `applies_to.to` when later evidence ends its current applicability.

## Body syntax

```markdown
## Observations
- [behaviour] Agent edits an interface and skips its callers
- [fix] "List every dependent file first" removes the failure

## Relations
- derived_from [[episodes/2026-08-14-claude-code-api-change]]
- mitigated_by [[repository-exploration]]
- implemented_as [[skills/repo-explorer]]
```

`- [category] fact` and `- relation_type [[target]]` are the only two body conventions the tooling depends on. Everything else is free prose.

## Naming

- Episodes: `episodes/YYYY-MM-DD-<tool>-<slug>.md`
- Knowledge: `knowledge/<folder>/<kebab-slug>.md` — the slug names the concept, never the tool
- Indexes: `knowledge/_index/<domain>.md`; router: `knowledge/_index/_domains.md`
- Packs: `outputs/context/<domain>-current.md`
- Skills: `skills/<kebab-name>/SKILL.md`
