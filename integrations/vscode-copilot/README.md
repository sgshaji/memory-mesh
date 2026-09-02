# GitHub Copilot CLI and VS Code integration

## Status

- **Copilot CLI:** deterministic repository hooks are implemented for session
  start, first-prompt recall, pre-compaction checkpointing, and session end.
- **VS Code:** repository instructions plus three agent skills provide recall,
  capture, and feedback. VS Code does not execute Copilot CLI repository hooks.

The integration files are:

- `.github/copilot-instructions.md`
- `.github/hooks/memory-mesh.json`
- `.github/skills/memory-{recall,learn,episode}/SKILL.md`
- `integrations/github-copilot/hook.py`

## Use inside this repository

Restart Copilot CLI from the repository root so it loads the hooks. Verify:

```text
/instructions
/skills list
```

Copilot CLI recalls automatically. In VS Code, invoke `/memory-recall`,
`/memory-learn`, and `/memory-episode`; Copilot may also select these skills
automatically from their descriptions.

## Use from every repository on this computer

Install the user-level hooks, instructions, and skills:

```powershell
python integrations\github-copilot\install.py
```

Restart Copilot CLI and VS Code. The generated user hook configuration points
at this vault, so moving the vault requires rerunning the installer. Remove
only the Memory Mesh integration with:

```powershell
python integrations\github-copilot\install.py --uninstall
```

Repository hook output is disabled in Copilot cloud-agent environments; the
local vault remains the authority.
