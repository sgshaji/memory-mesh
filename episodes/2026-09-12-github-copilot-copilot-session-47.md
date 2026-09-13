---
type: episode
tool: github-copilot
domains: [coding-agents]
captured: "2026-09-12T23:27:42+05:30"
trust: first-party
sensitivity: checked
status: summarised
session_ref: baaae614-0f53-4f3c-bc44-f17ef02b6c17
---

# Session: copilot-session

## Goal
Enable remote control of this repository from GitHub mobile through the
Copilot coding agent.

## What happened
Clarified that "remote" meant driving the repo from a phone, not a Git push
feature, and reverted an exploratory gitutil remote-push edit. Added
`.github/workflows/copilot-setup-steps.yml` (Python 3.13, editable install,
CLI smoke check) and `.github/workflows/tests.yml` (unittest matrix on 3.10
and 3.13, plus `doctor --fix` and `lint`). Documented remote-session rules in
`.github/copilot-instructions.md` and the README. Committed the in-flight
capture work and the enablement, then pushed to `origin/master`; both
workflows completed successfully on that commit.

## Decisions
Kept the uncommitted vault content (inbox candidates and episodes) out of the
push: the repository is public and those files carry project codenames.
Validated workflow commands against a temp clone first, which showed plain
`memory doctor` cannot be used in CI.

## Problems
A "Checkpoint from VS Code" commit appeared mid-task, moved the branch back,
and cleared the worktree including 128 untracked vault files. Recovered with
`git checkout <dangling-sha> -- .` followed by `git reset`, restoring
untracked files as untracked, then re-committed and pushed.

## Knowledge retrieved
- [[validation-order]]
- [[projects/copilot-studio-skills]]

## Knowledge used
- [[validation-order]] — held — deterministic checks (temp-clone run of
  `doctor`, `lint`, and the suite) ran before trusting the workflow text.
- [[projects/copilot-studio-skills]] — not-applicable — this session was CI and
  agent enablement, not document validation.

## Candidate learnings
- Memory Mesh CI must run `doctor --fix` because `_meta/session-state/` is
  gitignored (github-copilot, 2026-09).
- VS Code cloud-agent checkpoints can reset the worktree and absorb untracked
  files (github-copilot, 2026-09).
