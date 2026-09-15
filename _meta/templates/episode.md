---
type: episode
tool: <tool>
project: <projects/ note name or omit>
domains: [<from knowledge/_index/_domains.md>]
captured: <YYYY-MM-DDTHH:MM:SS+05:30>
duration_min: 0
trust: first-party
sensitivity: checked
status: raw
completeness: partial
session_ref: <local transcript id or path — never a URL to confidential content>
# session_id: <opaque capture-session identifier>
# recall_quality: useful | partial | missed | off-target
# outcome_events: [<IDs of immutable reports projected in this episode>]
---

# Session: <one line>

<!-- Sections are optional. Keep useful available observations; do not invent
content to fill gaps. `memory episode finish` marks completeness partial or
complete. A title, goal, or blank scaffold alone is not a useful summary.
Session references are provenance, never permission to read a transcript.
Capture validates fields and redacts metadata, references and titles before
constructing filenames or writing. Unsupported field types fail explicitly. -->

## Goal

## What happened
- tried A → failed because …
- changed B → worked
<!-- Prefilled checkpoints distinguish an observed capture from reported
contents. Reported success never establishes verified tool execution. -->

## Decisions
- <decision> — <why>

## Problems
- <what broke; short error text; environment or version>

## Knowledge retrieved
- [[<every note injected at recall>]]

## Knowledge used
- [[<note>]] — held|failed|unclear|not-applicable — <short reason>
<!-- Failed reports may use: reason=behaviour_changed; <detail>
Other reasons: misapplied, context_mismatch, insufficient_information, unknown.
Journal-prefilled bullets carry an outcome-event ID and a reported marker.
Keep those markers: capture a new event to report a different outcome.
Do not move used-only reports into Knowledge retrieved unless recall served them. -->

## Skill outcomes
- [[skills/<slug>]] — succeeded|failed|partial — <short reported outcome>

## Candidate learnings
- <observation that might generalise> (<tool>, <version>)
