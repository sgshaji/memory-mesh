---
type: candidate
title: VS Code cloud-agent checkpoints can reset the worktree and absorb untracked files
source: "automatic capture via github-copilot, 2026-09-12"
captured: "2026-09-12T23:27:31+05:30"
domains: [coding-agents]
trust: first-party
sensitivity: checked
content_hash: ecbfb9218b2957b9
---

## Observations
- [behaviour] During a VS Code cloud agent session, a Checkpoint from VS Code commit was created mid-task; it captured untracked files, then the branch was reset so HEAD moved back and the worktree lost both new files and previously untracked content.
- [limitation] An agent commit made just before a checkpoint can end up dangling and off the branch, so a successful git commit is not proof the change is still on HEAD.
- [procedure] After an unexpected checkpoint, recover with git checkout <dangling-sha> -- . followed by git reset, which restores files to the worktree and returns previously untracked content to untracked state instead of committing it.
- [outcome] Recovery restored two modified files, two new workflows, and 128 untracked vault files; the intended commit was then re-made and pushed successfully.
