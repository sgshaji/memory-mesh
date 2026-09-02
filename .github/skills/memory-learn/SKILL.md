---
name: memory-learn
description: Capture a reusable observation as a Memory Mesh candidate when the user says remember this, worth noting, or invokes /memory-learn.
---

Phrase the observation as one factual sentence and run:

```text
python "integrations/github-copilot/memory.py" learn "<observation>" --tool github-copilot
```

Add `--domain`, `--project`, or `--trust mixed|third-party` only when known.
Report the created candidate path. Never write directly to `knowledge/` or
claim that the candidate is validated. Do not include confidential material.

When this skill is installed globally, the installer replaces the script path
with the absolute path to the user's Memory Mesh vault.
