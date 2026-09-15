---
type: episode
tool: github-copilot
domains: [copilot-studio]
captured: "2026-09-15T00:35:59+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: d99007a5-2933-4cd6-9e73-dee1da060af2
completeness: complete
prefilled:
  knowledge_retrieved: {source: provided-retrievals, evidence: reported}
---

# Session: copilot-session

## Goal
Implement opt-in evaluation dataset ingestion and a persistent agent association through Copilot Agent Kit, without running tests against a live agent.

## What happened
Implemented create-only Dataverse upload, a companion binding table, explicit test-type mapping, no-network planning, remote verification, and hash-bound local receipts. Wired evaluator publication checks and refreshed both distributions. Consulted official Dataverse documentation and inspected the public Kit managed package's field names and option values.
Both evaluator suites passed 35 tests each. Builder, optimizer, plugin, and most routing/checkpoint checks passed. Two input-routing fixture failures were reproduced on pristine HEAD and left unchanged. No live Dataverse writes occurred.

## Decisions
Keep integration disabled unless configured and require explicit write confirmation. Use an existing verified Kit agent configuration; do not create runs or mutate agents/Kit metadata. Store cross-environment logical references in a separately deployed companion table. Include configuration identity in immutable binding keys and preserve unresolved receipts before allowing a different import identity.

## Problems
Independent review found missing derived metadata limits, loss of unresolved-write history on input changes, and binding-key collisions across configurations. Reproduction tests failed before fixes and passed afterward. Live environment setup and end-to-end tenant verification remain deployment prerequisites.

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]
- [[large-file-upload-failure]]
- [[schema-validation-workaround]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] - held: invalid mappings, incompatible metadata, and identity mismatches were rejected before remote writes in isolated tests.

## Skill outcomes
Incremental tests covered retries, unknown outcomes, tampering, config mismatch, pagination, schema setup, receipt publication, default environment identifiers, and distribution parity. Review findings were fixed rather than deferred. Dependencies were unchanged and temporary research artifacts were removed.

## Candidate learnings
- [[00-inbox/2026-09-15-github-copilot-dataverse-attribute-expansion-omits-derived-stri]] - public-source-backed typed metadata retrieval behavior, captured as an unvalidated candidate.
