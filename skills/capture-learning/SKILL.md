---
name: capture-learning
description: Capture an observation worth remembering into the memory vault's inbox. Use when the user says /learn, "remember this", "worth noting", or when a session surfaces a reusable insight worth keeping. Never writes canonical knowledge.
---

# Capture a learning

Goal: insight → safely stored candidate in under 15 seconds. One call, no
follow-up questions.

## Steps

1. Phrase the observation as ONE factual sentence, preserving the user's
   wording where safe. Append the tool and version in parentheses when known:
   `schema generator drops optional properties unless declared (copilot-studio, 2026-09)`.
2. Run:

       memory learn "<observation>" --tool <your-host-name> [--domain <domain>] [--project <project>] [--trust first-party|mixed|third-party]

   - `--trust mixed` when the insight leans on web/email content you read;
     `third-party` when it is purely read, not observed.
   - Omit `--domain` when unsure; the curator classifies later.
3. Report the created path to the user in one line. Done.

## Rules

- This creates a CANDIDATE in `00-inbox/` only. Never edit `knowledge/`,
  never claim the item is validated — validation is the curator's job.
- Secrets, customer names, tenant ids and internal URLs are redacted by the
  tool before anything is written; do not paste confidential material anyway.
- Capturing the same insight twice is safe (content-hash idempotent).
- If the host cannot run commands, write the file yourself into `00-inbox/`
  using `_meta/templates/candidate.md` — same rules apply.
