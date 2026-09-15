---
type: candidate
title: Dataverse attribute expansion omits derived string limits
source: "automatic capture via github-copilot, 2026-09-15"
captured: "2026-09-15T00:36:00+05:30"
domains: [copilot-studio]
trust: first-party
sensitivity: checked
content_hash: b1fc09f69fbd9242
---

## Observations
- [evidence] Microsoft Web API metadata guidance states that expanded Attributes expose base AttributeMetadata properties. MaxLength requires querying the StringAttributeMetadata or MemoAttributeMetadata cast. Source: https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/query-metadata-web-api#query-entitymetadata-attributes
- [outcome] An isolated schema-setup test using the base-only response reproduced a false incompatible-schema result. Fetching and merging typed column limits made the setup and field-length rejection tests pass.
- [procedure] Read base attribute names/types and separately query the relevant derived metadata classes for limits. Fail explicitly when required limits cannot be retrieved rather than substituting a permissive default.
