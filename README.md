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

### GitHub Copilot CLI and VS Code

Repository hooks and skills are included. To make Memory Mesh available to
GitHub Copilot from every repository on this computer:

```powershell
python integrations\github-copilot\install.py
```

Restart Copilot CLI and VS Code, then verify `/instructions` and
`/skills list`. Copilot CLI performs recall and episode-stub creation through
hooks. During work, Copilot can autonomously turn a verified reusable finding
into a validated, redacted structured candidate in `00-inbox/`; it does not
promote candidates into canonical knowledge. VS Code exposes `/memory-recall`,
`/memory-learn`, and `/memory-episode`.

### Driving this repository from a phone

The Copilot coding agent can work on this repository from GitHub mobile or
github.com. Assign an issue to Copilot, or start a session from the Agents
panel; it opens a pull request you review and merge from the phone.

- `.github/workflows/copilot-setup-steps.yml` prepares its environment
  (Python 3.13, `pip install -e .`) before the agent starts.
- `.github/workflows/tests.yml` runs the full suite plus `memory lint` on
  every pull request — the signal you rely on when reviewing on mobile.
- `.github/copilot-instructions.md` tells remote sessions how to validate
  changes and to keep vault records out of code pull requests.

One-time repository setting: **Settings → Copilot → Coding agent** must be
enabled for the repository (an active Copilot subscription is required).

### Repository skills for Copilot cloud sessions

Three additional, repository-local skills are included in `.github/skills/`:

| Skill | Ask Copilot |
|---|---|
| `interview-me` | “Use interview-me to clarify my goal, one question at a time.” |
| `idea-refine` | “Use idea-refine to explore how previous work can improve my next task.” |
| `spec-driven-development` | “Use spec-driven-development to specify the agreed idea before coding.” |

They are adapted from the MIT-licensed
[Addy Osmani Agent Skills collection](https://github.com/addyosmani/agent-skills/tree/be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39)
at commit `be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39`. Each skill includes
its license and adaptation notes; `idea-refine` also includes its three
supporting reference documents. The optional setup script, plugin hooks,
personas, and other upstream skills are not installed.

No Copilot CLI installation or setup workflow is needed. Start a **new cloud
task using a branch containing these files**; for default-branch tasks, merge
the changes first. Ask for a skill by name and verify that the new session
discovers it; adding files does not guarantee a running session reloads them.
These skills are repository-local, not installed into your other repositories
or Microsoft 365 tools. The user-level installer above still installs only
the three Memory Mesh lifecycle skills.

Clarification can continue through cloud follow-up messages. Drafts stay in
the conversation unless you explicitly request a file at a permitted path.
The skills preserve Memory Mesh's bounded recall, privacy, and curator-owned
knowledge rules; they do not grant permission to modify frozen V1 specs.

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
.github/              GitHub Copilot instructions, hooks, skills and agents
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
