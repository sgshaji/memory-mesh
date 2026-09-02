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

2. Open the exact path printed by step 1. Fill its seven sections without changing the
   pre-filled **Knowledge retrieved** list. Put only exercised notes under
   **Knowledge used**, each with `held`, `failed`, `unclear`, or
   `not-applicable` and a short reason.
3. Finish that same explicit path:

   ```text
   python "integrations/github-copilot/memory.py" episode finish "<episode-path>"
   ```

Keep the body under 400 words. Redact confidential information. Never edit an
episode after it reaches `status: mined`.

When this skill is installed globally, the installer replaces the script path
with the absolute path to the user's Memory Mesh vault.
