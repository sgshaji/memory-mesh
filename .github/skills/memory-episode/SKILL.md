---
name: memory-episode
description: Finish a GitHub Copilot work session by recording decisions, failures, retrieved knowledge, and observed outcomes in Memory Mesh.
---

1. If a Memory Mesh session id is available from automatic or manual recall,
   create the current session's stub and capture the exact path printed:

   ```text
   python "integrations/github-copilot/memory.py" session-end --tool github-copilot --session "<session-id>" --session-ref "<session-id>" --slug copilot-session --force
   ```

   If recall never established a session id, create a standalone stub instead:

   ```text
   python "integrations/github-copilot/memory.py" episode create --tool github-copilot --slug copilot-session
   ```

2. The printed path is relative to the Memory Mesh vault. Open the exact file
   at `<MEMORY_MESH_ROOT>/<episode-path>`. When running this project skill
   without the user installer, `<MEMORY_MESH_ROOT>` is the repository root.
   Fill only sections supported by available facts, without changing the
   pre-filled **Knowledge retrieved** list or outcome event identities.
   Partial episodes are useful; do not invent prose for missing sections.
   Put only exercised notes under **Knowledge used**, each
   with `held`, `failed`, `unclear`, or `not-applicable` and a short reason.
   Preserve the distinction between reported outcomes and observed actions.
   Record `recall_quality: useful | partial | missed | off-target` when the
   session provides enough evidence to judge retrieval.
3. Finish that same explicit path:

   ```text
   python "integrations/github-copilot/memory.py" episode finish "<episode-path>"
   ```

Keep the body under 400 words. Redact confidential information. Never edit an
episode after it reaches `status: mined`.

When an outcome is known during work, capture it immediately instead of
reconstructing it at session end:

```text
python "integrations/github-copilot/memory.py" feedback "<knowledge-reference>" "#held" --session "<session-id>"
python "integrations/github-copilot/memory.py" feedback "<knowledge-reference>" "#failed" --session "<session-id>" --reason behaviour_changed --detail "<short observed result>"
```

Reuse an event ID on retries; use a distinct `--event-id` only for a genuinely
independent trial. The episode pre-fill includes these outcomes without
counting the same event twice. Feedback is not permission to edit knowledge.

When this skill is installed globally, the installer replaces the script path
with the absolute path to the user's Memory Mesh vault.
