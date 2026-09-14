---
type: candidate
title: Repeat-work share bounds whole-workload agent gains
source: "automatic capture via github-copilot, 2026-09-14"
captured: "2026-09-14T11:45:56+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: 1277ae785539d2f7
---

## Observations
- [scenario] For a fixed task mix and unchanged acceptance quality, normalize positive baseline cost (or serial active time) to 1. Let p be the fraction eliminated by reuse and h be all added memory overhead in the same units.
- [limitation] Even perfect elimination of the eligible repeat work leaves 1-p+h, so the best possible overall multiplier is 1/(1-p+h) when that denominator is positive. This is an analytical bound, not measured agent performance or a claim about concurrent throughput.
- [procedure] Measure the eliminable repeat-work fraction and memory overhead before making a whole-workload 10x claim. Report eligible repeat-task results separately from the full task stream, and do not combine dollars with human time.
- [evidence] PowerShell Decimal arithmetic verified p=0.60,h=0 implies a maximum 2.5x multiplier; a 10x multiplier requires at least p=0.90 with zero overhead or p=0.92 with h=0.02, assuming the repeat portion disappears entirely.
- [outcome] The analytical checks passed. No live-agent benchmark, billing measurement, recurrence estimate, or product productivity result was established.
