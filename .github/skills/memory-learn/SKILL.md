---
name: memory-learn
description: Automatically capture a verified reusable insight as a structured Memory Mesh candidate when one emerges during work, or when the user says remember this, worth noting, or invokes /memory-learn.
---

Do not wait for the user to compose or request a learning. When work produces a
finding that is reusable beyond the current task and is supported by an observed
outcome or reproducible evidence, capture it while the context is warm. Do not
capture routine progress, plans, guesses, user preferences, or recalled
knowledge that was not independently exercised.

Build a compact JSON object with:

- `title`: a specific factual title;
- `observations`: 2-9 `{kind, text}` entries. Allowed kinds are `scenario`,
  `behaviour`, `procedure`, `fix`, `workaround`, `limitation`, `reason`,
  `outcome`, and `evidence`. Include at least one actionable kind and one
  `outcome` or `evidence`;
- optional `domain`, `project`, `trust`, `signal` (`high`, `normal`, or `low`),
  and `source_episode` when an existing episode supplies context. Signal
  controls review attention, not truth or approval.

Pass the JSON as one safely quoted argument, or on standard input. For example:

```text
python "integrations/github-copilot/memory.py" learn '{"title":"Validate grounding sources before publishing","observations":[{"kind":"procedure","text":"Validate every configured grounding source before publishing."},{"kind":"evidence","text":"The validation rejected an unavailable source during the test run."}],"domain":"copilot-studio","trust":"first-party"}' --structured --tool github-copilot
```

The deterministic writer validates the shape, assigns a domain when omitted,
redacts before persistence, deduplicates, and writes only to `00-inbox/`.
Continue the task without asking a capture-specific follow-up question. Mention
the candidate path in the final summary. Never write directly to `knowledge/`
or claim that the candidate is validated. Do not include confidential material.

When this skill is installed globally, the installer replaces the script path
with the absolute path to the user's Memory Mesh vault.
