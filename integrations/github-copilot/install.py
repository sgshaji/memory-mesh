"""Install or remove the user-level GitHub Copilot integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = Path(__file__).with_name("hook.py")
SKILLS = ("memory-recall", "memory-learn", "memory-episode")
MANIFEST = "memory-mesh-install.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".memory-mesh-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _powershell_command(action: str) -> str:
    python = str(Path(sys.executable).resolve()).replace("'", "''")
    script = str(HOOK_SCRIPT.resolve()).replace("'", "''")
    return f"& '{python}' '{script}' {action}"


def _hook_config() -> dict:
    hooks = {}
    for event, action in (
        ("sessionStart", "session-start"),
        ("userPromptTransformed", "session-prompt"),
        ("preCompact", "pre-compact"),
        ("sessionEnd", "session-end"),
    ):
        hooks[event] = [{
            "type": "command",
            "bash": shlex.join([sys.executable, str(HOOK_SCRIPT.resolve()), action]),
            "powershell": _powershell_command(action),
            "env": {"MEMORY_MESH_ROOT": str(ROOT)},
            "timeoutSec": 10,
        }]
    return {"version": 1, "hooks": hooks}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _managed_content(home: Path) -> dict[Path, str]:
    root_text = str(ROOT)
    content = {
        home / "hooks" / "memory-mesh.json": json.dumps(_hook_config(), indent=2) + "\n",
    }
    instructions = (Path(__file__).with_name("user-instructions.md")
                    .read_text(encoding="utf-8")
                    .replace("<MEMORY_MESH_ROOT>", root_text))
    content[home / "instructions" / "memory-mesh.instructions.md"] = instructions

    source_skills = ROOT / ".github" / "skills"
    script_rel = '"integrations/github-copilot/memory.py"'
    script_abs = f'"{Path(__file__).with_name("memory.py").resolve()}"'
    for name in SKILLS:
        target = home / "skills" / name / "SKILL.md"
        skill = (source_skills / name / "SKILL.md").read_text(encoding="utf-8")
        content[target] = (skill.replace(script_rel, script_abs)
                           .replace("<MEMORY_MESH_ROOT>", root_text))
    return content


def _load_manifest(home: Path) -> dict | None:
    path = home / MANIFEST
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("files"), dict):
        raise RuntimeError(f"invalid Memory Mesh install manifest: {path}")
    if not all(isinstance(rel, str) and isinstance(digest, str) for rel, digest in value["files"].items()):
        raise RuntimeError(f"invalid Memory Mesh install manifest entries: {path}")
    return value


def _managed_path(home: Path, rel: str) -> Path:
    relative = Path(rel)
    if relative.is_absolute():
        raise RuntimeError(f"managed path must be relative to Copilot home: {rel}")
    target = home / relative
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"managed path contains a symlink: {rel}")
    resolved = target.resolve()
    try:
        resolved.relative_to(home.resolve())
    except ValueError as exc:
        raise RuntimeError(f"managed path escapes Copilot home: {rel}") from exc
    return target


def _changed_managed_files(home: Path, manifest: dict) -> list[Path]:
    changed = []
    for rel, expected in manifest["files"].items():
        path = _managed_path(home, rel)
        if path.exists() and _digest(path.read_text(encoding="utf-8")) != expected:
            changed.append(path)
    return changed


def install(home: Path, force: bool = False) -> list[Path]:
    content = _managed_content(home)
    for path in content:
        _managed_path(home, path.relative_to(home).as_posix())
    manifest = _load_manifest(home)
    if manifest:
        owned = {_managed_path(home, rel) for rel in manifest["files"]}
        changed = _changed_managed_files(home, manifest)
        if changed and not force:
            raise RuntimeError("refusing to overwrite modified managed files: " + ", ".join(map(str, changed)))
        collisions = [path for path in content if path.exists() and path not in owned]
        if collisions and not force:
            raise RuntimeError("refusing to overwrite newly managed existing files without --force: "
                               + ", ".join(map(str, collisions)))
    elif not force:
        collisions = [path for path in content if path.exists()]
        if collisions:
            raise RuntimeError("refusing to overwrite existing files without --force: " + ", ".join(map(str, collisions)))

    written = []
    for path, text in content.items():
        _atomic_write(path, text)
        written.append(path)
    manifest_value = {
        "version": 1,
        "vault": str(ROOT),
        "files": {
            path.relative_to(home).as_posix(): _digest(text)
            for path, text in content.items()
        },
    }
    manifest_path = home / MANIFEST
    _atomic_write(manifest_path, json.dumps(manifest_value, indent=2) + "\n")
    written.append(manifest_path)
    return written


def uninstall(home: Path, force: bool = False) -> list[Path]:
    manifest = _load_manifest(home)
    if manifest:
        changed = _changed_managed_files(home, manifest)
        if changed and not force:
            raise RuntimeError("refusing to remove modified managed files: " + ", ".join(map(str, changed)))
        targets = [_managed_path(home, rel) for rel in manifest["files"]]
    elif force:
        targets = list(_managed_content(home))
    else:
        raise RuntimeError(f"Memory Mesh install manifest not found: {home / MANIFEST}")

    removed = []
    for path in targets:
        if path.exists():
            path.unlink()
            removed.append(path)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    manifest_path = home / MANIFEST
    if manifest_path.exists():
        manifest_path.unlink()
        removed.append(manifest_path)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Memory Mesh for GitHub Copilot CLI and VS Code")
    parser.add_argument("--home", type=Path, help="Copilot home (default: COPILOT_HOME or ~/.copilot)")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace or remove modified Memory Mesh-managed files")
    args = parser.parse_args(argv)
    home = (args.home or Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))).expanduser().resolve()
    try:
        changed = uninstall(home, force=args.force) if args.uninstall else install(home, force=args.force)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    action = "removed" if args.uninstall else "installed"
    for path in changed:
        print(f"{action}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
