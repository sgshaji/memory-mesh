---
type: candidate
title: Preserve deployed field IDs when extending generated SharePoint schemas
source: "automatic capture via github-copilot, 2026-09-04"
captured: "2026-09-04T21:41:28+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: c69bdf6ff2d24463
project: file-iterator
---

## Observations
- [scenario] A PnP template generator assigned field GUIDs by consuming a seeded pseudo-random sequence in column order.
- [behaviour] Inserting new columns shifted every later generated GUID, reassigning existing deployed field identities even though generation remained deterministic.
- [fix] Keep legacy fields on the original sequence and assign newly added fields explicit stable IDs derived from their list and column identity.
- [procedure] Before shipping schema additions, compare the regenerated template with the previous revision and assert that every pre-existing field name retains its GUID.
- [evidence] The comparison initially found shifted WalkFrontier and IndexWalkRun field IDs; after the fix it reported zero changes for existing fields and the complete validation suite passed.
