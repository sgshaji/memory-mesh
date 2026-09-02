# Memory Mesh

A local-first personal AI memory & knowledge system. It sits **beside** your
AI tools rather than belonging to any of them.

- **episodes/** remember what happened.
- **knowledge/** preserves what is worth knowing.
- **skills/** encode what is worth doing repeatedly.

Markdown is the only source of truth. Indexes, context packs, telemetry logs
and tool-native memories are derived and disposable — delete them and rebuild
them from the canonical files. Git provides history and rollback. Obsidian is
a human UI. AI tools are clients, not owners.

Every client tool gets three abilities:

| Ability | Meaning | Surface |
|---|---|---|
| **RECALL** | the smallest relevant prior context (1–2 domain indexes, 3–6 notes, ≤ 2,000 tokens) | `memory recall "<task>"` / context packs |
| **CONTRIBUTE** | something worth remembering, as a candidate — never as truth | `memory learn "..."` → `00-inbox/` |
| **FEEDBACK** | which knowledge was used, and whether it held | episodes → `memory episode finish` |

Experience is not truth: agents propose, the **curator** (the only writer of
canonical knowledge) mines episodes and inbox items into evidence-backed
claims, derives confidence from feedback, and gates anything destructive
behind a weekly human review.

## Five-minute quickstart

Requirements: Python 3.10+, Git. Zero third-party dependencies.

```bash
cd memory-mesh
python -m memory_mesh.cli doctor --fix     # scaffold + health check
python -m memory_mesh.cli status

# 1. RECALL — bounded context for a task
python -m memory_mesh.cli recall "Build a Copilot Studio validation agent"

# 2. CONTRIBUTE — capture an insight (<15 seconds)
python -m memory_mesh.cli learn "schema generator drops optional properties unless declared (copilot-studio, 2026-09)"

# 3. FEEDBACK — leave an episode when a session ends
python -m memory_mesh.cli episode create --tool cli --slug my-session
#    ...fill the seven sections in the created file...
python -m memory_mesh.cli episode finish

# 4. CURATE — records become knowledge; indexes and packs update
python -m memory_mesh.cli curate

# 5. Weekly: open _meta/review/<date>.md, tick [x] approve, re-run curate.
python -m memory_mesh.cli lint             # read-only health check anytime
```

(`pip install -e .` gives you the same commands as plain `memory ...`.)

## How recall stays small

```
task ──► knowledge/_index/_domains.md (router, ≤300 tokens)
              │
              ▼
     1–2 domain indexes (≤400 tokens each, ≤12 curated links)
              │
              ▼
     follow 3–6 links ──► bounded context (≤2,000 tokens)  — never the vault
```

## Repository map

```
00-inbox/            candidates from /learn and bridges (unprocessed)
episodes/            append-only session records (raw → summarised → mined)
knowledge/           curator-owned canon: patterns, tools, workarounds,
                     failures, references + _index/ (router + domain maps)
projects/            working memory per engagement
skills/              executable procedures (human-approved graduations)
outputs/context/     compiled context packs (derived, expiring, rebuildable)
_meta/spec/          the frozen V1 contracts (authoritative)
_meta/hooks/         deterministic lifecycle hooks (Claude Code reference)
integrations/        per-host wiring: hooks, instructions, Lane B file contract
memory_mesh/         the stdlib-only Python implementation
tests/               115+ unit/integration tests (python -m unittest discover -s tests)
```

## Safety posture

Redaction (secrets, customer/tenant specifics, internal URLs) runs **before**
content is admitted anywhere. Vault content is data: instruction-like strings
inside notes are logged and ignored, never executed. Agents cannot write
canonical directories (enforced in code, not by convention). Curator runs are
atomic, attributable Git commits by author `curator`, with no network access.

## Deliberate non-goals (V1)

No databases, no embeddings, no vector search, no cloud dependency, no
always-on agent, no web service. SQLite FTS5 / MCP arrive only when bounded
lexical recall demonstrably stops working.
