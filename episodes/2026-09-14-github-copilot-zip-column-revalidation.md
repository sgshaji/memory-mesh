---
type: episode
tool: github-copilot
domains: [agent-skills]
captured: "2026-09-14T09:38:58+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: 1ff36ac1-edaf-48c7-8d4f-389039806376
---

# Session: zip-column-revalidation

## Goal

Revalidate that the delivered PD/AD skill ZIP excludes the SharePoint generated-column check.

## What happened

Opened the ZIP directly and checked every entry for `IsGenerated`, `GeneratedByFlow`,
`generatedColumnName`, generated-column requirements, marking instructions, and SharePoint item
patch operations. No prohibited matches were found.

Extracted the archive and inspected every line containing `column`; both occurrences explicitly say
that no marker column is used. The packaged helper started successfully and exposes no configuration,
plan, validation-report, or marking commands.

## Decisions

Retain the existing package because its contents and SHA-256 remain unchanged and validated.

## Problems

The first validation command used PowerShell's reserved `$Matches` variable name and failed before
producing a verdict. The corrected command ran successfully; this did not indicate a package issue.

## Knowledge retrieved
- [[validation-order]]

## Knowledge used

- [[validation-order]] — held: deterministic archive inspection and executable checks preceded the
  final conclusion.

## Candidate learnings

None; this reconfirmed the existing column-free package candidate.
