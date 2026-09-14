---
type: candidate
title: Memory Mesh compile does not finalize raw session stubs
source: "automatic capture via github-copilot, 2026-09-13"
captured: "2026-09-13T00:32:50+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: ea3f20a436aeec2e
---

## Observations
- [behaviour] Session-end scaffolding creates a raw episode, while the default curator compile selects only episodes whose status is summarised. Creating a stub alone does not make session experience ready for mining.
- [procedure] Verify the raw-to-summarised handoff separately when claiming automatic learning. Finalize an evidence-bearing episode while session context is available, then run curation; keep unresolved raw records visibly pending.
- [evidence] Inspected memory_mesh/episodes.py create_stub, memory_mesh/cli.py cmd_session_end, and memory_mesh/curator/engine.py run_compile. The compiler's episodes_ready filter requires status == summarised. This finding is from source inspection, not a new runtime experiment.
