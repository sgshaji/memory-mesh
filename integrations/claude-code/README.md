# Claude Code integration (V1 reference host)

**Status: installed and verified** against Claude Code **2.1.240** on Windows.
This is no longer a template — the hook contract below was checked against the
host's own documentation and every script was executed with real payloads.

## Install

```powershell
python integrations\claude-code\install.py
```

Merges into `~/.claude/settings.json` (existing settings and anyone else's
hooks are preserved), writes a timestamped backup, and prints where it went.
Restart Claude Code, or start a new session, to load the hooks.

To remove only Memory Mesh, leaving everything else untouched:

```powershell
python integrations\claude-code\install.py --uninstall
```

Hooks are installed at **user** level, so memory works in every repository —
the vault is addressed by absolute path, not by working directory.

## What is wired

| Event | Matcher | Script | Effect |
|---|---|---|---|
| `SessionStart` | `startup\|resume\|clear` | `recall_start.py` | injects the domain router and the `projects/` note matching the working directory |
| `UserPromptSubmit` | — | `recall_domain.py` | **first prompt only**: matches the router, injects that domain index and its linked notes (≤6 notes, ≤2,000 tokens); silent afterwards |
| `PreCompact` | `manual\|auto` | `episode_checkpoint.py` | parks a redacted checkpoint so a long session loses nothing when context is compacted |
| `SessionEnd` | — | `episode_stub.py` | writes the episode stub with *Knowledge retrieved* pre-filled, then clears the session scratch |

That is three automatic memory operations per session — start, domain recall,
end — never per message. `/learn` is deliberate and uncapped.

`SessionStart` deliberately excludes the `compact` matcher: compaction rebuilds
context inside an existing session, it does not begin a new one, and re-injecting
the router there would spend a second recall the budget does not allow.

## Commands

`/learn` and `/episode` are installed as user skills in `~/.claude/skills/`, so
they are available in every repository. They wrap the same CLI any other host
calls — the memory core has no dependency on Claude Code.

## Contract details that matter

Learned from the host docs and confirmed by execution; these constrain the
implementation, so change them only against fresh documentation.

- **Payload fields.** `UserPromptSubmit` delivers the prompt as `user_prompt`
  (not `prompt`); `SessionStart` carries `source`, `SessionEnd` an exit reason.
  All events carry `session_id`, `cwd` and `transcript_path`. The scripts read
  every field defensively — a missing key means "nothing to do", never a crash.
- **Context injection.** Output uses the documented JSON form,
  `{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}`.
  For `UserPromptSubmit` a top-level `additionalContext` is silently ignored.
- **Exit codes are dangerous here.** On `UserPromptSubmit`, exit 2 **blocks the
  prompt and erases the user's input**, and any nonzero code raises a visible
  error. Every hook therefore exits 0 unconditionally: a memory failure must
  cost silence, never someone's prompt. This is enforced in `_common.run()`.
- **Timeouts.** `UserPromptSubmit` allows 30s; `SessionEnd` hooks share a ~1.5s
  budget unless a per-hook `timeout` raises it, so one is set explicitly. The
  stub write measures ~0.2s.
- **Windows paths.** The exec form (`command` + `args` array) is used rather
  than a shell string, because this vault's path contains spaces
  (`OneDrive - Microsoft`) and exec form needs no quoting. The installer writes
  the absolute interpreter path, so nothing depends on `PATH`.

## Verifying it works

Start a fresh session and check that the router appears in context, then:

```powershell
python "<vault>\memory-mesh.py" status
```

After a session ends, a `status: raw` stub should be waiting in `episodes/`.
Run `/episode` to fill and seal it while the context is still warm.
