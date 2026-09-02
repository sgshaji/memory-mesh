---
name: episode
description: Record what a working session left behind - goal, what happened, decisions, problems, which knowledge was used and whether it held. Use when a session that made decisions or hit problems is ending, or when the user says /episode.
---

# Write the episode

An episode is a RECORD, not knowledge. Messy is fine; dead ends are the
valuable part. Target ≤ 400 words.

## Steps

1. Find the stub: `memory episode show` (the latest `status: raw` episode).
   If none exists: `memory episode create --tool <host> --slug <short-slug>`.
2. Fill the seven sections IN THE FILE (keep the section order):
   - **Goal** — one or two lines.
   - **What happened** — short chronological bullets; keep failures.
   - **Decisions** — `<decision> — <why>`.
   - **Problems** — what broke; short error text; tool + version.
   - **Knowledge retrieved** — already pre-filled by the hook; leave intact.
   - **Knowledge used** — ONLY notes you actually exercised, each as
     `- [[note]] — held|failed|unclear|not-applicable — <short reason>`.
     A retrieved-but-unused note stays out of this section. Never mark a
     note `held` merely because it was retrieved.
   - **Candidate learnings** — observations that might generalise, phrased
     as observations with tool + version, never as rules.
3. Run `memory episode finish` — it validates the sections, redacts, and
   flips the status to `summarised`. Fix anything it rejects and re-run.

## Rules

- Redact at capture: `[customer]`, `[tenant]`, `[internal doc → Reference note]`.
- If the session leaned on web/email content, set `trust: mixed` in the
  frontmatter and prefix those bullets with `(read)`.
- Never edit an episode after it reaches `status: mined`.
- A short session with no decisions may skip this; a session that retrieved
  knowledge must still preserve *Knowledge retrieved*.
