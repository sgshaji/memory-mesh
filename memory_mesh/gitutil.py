"""Git as history and rollback (mandate §N). Local-only; no remote needed.

One curator run = one logical change set. The curator stages ONLY paths it
owns and never touches unrelated user changes (issues.md I-006). If Git is
unavailable, writes still happen atomically and the caller reports that a
manual commit is required — never a destructive fallback.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Vault

CURATOR_AUTHOR = "curator <curator@memory-mesh.local>"


@dataclass
class CommitResult:
    committed: bool
    sha: str | None
    message: str


def _git(vault: Vault, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(vault.root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def available(vault: Vault) -> bool:
    try:
        return _git(vault, "rev-parse", "--is-inside-work-tree").returncode == 0
    except (OSError, FileNotFoundError):
        return False


def head_commit(vault: Vault) -> str | None:
    r = _git(vault, "rev-parse", "--short", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def dirty_paths(vault: Vault) -> list[str]:
    r = _git(vault, "status", "--porcelain")
    if r.returncode != 0:
        return []
    return [line[3:].strip().strip('"') for line in r.stdout.splitlines() if line.strip()]


def commit_paths(vault: Vault, rel_paths: list[str], message: str, author: str = CURATOR_AUTHOR) -> CommitResult:
    """Stage exactly `rel_paths` and commit them with `author`. A failure
    unstages what we staged and reports; it never resets user work."""
    if not available(vault):
        return CommitResult(False, None, "git unavailable — changes written; manual commit required")
    existing = [p for p in rel_paths if (vault.root / p).exists()]
    deleted = [p for p in rel_paths if not (vault.root / p).exists()]
    if not existing and not deleted:
        return CommitResult(False, None, "nothing to commit")
    add = _git(vault, "add", "--", *existing) if existing else None
    if deleted:
        _git(vault, "add", "--all", "--", *deleted)
    if add is not None and add.returncode != 0:
        return CommitResult(False, None, f"git add failed: {add.stderr.strip()}")
    staged = _git(vault, "diff", "--cached", "--name-only")
    if not staged.stdout.strip():
        return CommitResult(False, None, "nothing to commit")
    commit = _git(
        vault,
        "-c", "user.name=curator",
        "-c", "user.email=curator@memory-mesh.local",
        "commit",
        "--only",
        "--author", author,
        "-m", message,
        "--", *rel_paths,
    )
    if commit.returncode != 0:
        _git(vault, "reset", "HEAD", "--", *rel_paths)  # unstage ours only
        return CommitResult(False, None, f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
    return CommitResult(True, head_commit(vault), "committed")
