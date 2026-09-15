"""Git as history and rollback (mandate §N). Local-only; no remote needed.

One curator run = one logical change set. Proposed blobs are staged in an
isolated index, never the user's index. After a commit, Git's index-only
two-tree merge reconciles published entries without overwriting conflicting
user stages. If Git is
unavailable, writes still happen atomically and the caller reports that a
manual commit is required — never a destructive fallback.
"""

from __future__ import annotations

import subprocess
import os
import re
import tempfile
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import Vault, VaultError
from . import fsutil

CURATOR_AUTHOR = "curator <curator@memory-mesh.local>"
_INDEX_CONTEXT: ContextVar[tuple[Path, Path] | None] = ContextVar("memory_mesh_git_index", default=None)
_INDEX_CACHE = "_meta/session-state/curation-git"


class GitError(VaultError):
    pass


@dataclass
class CommitResult:
    """Missing Git metadata is manual-only, not successful publication or a failed command."""

    committed: bool
    sha: str | None
    message: str
    failed: bool = False
    manual_commit_required: bool = False


def _git(vault: Vault, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    index = _INDEX_CONTEXT.get()
    if index is not None and index[0] == vault.root:
        env["GIT_INDEX_FILE"] = str(index[1])
    return subprocess.run(
        ["git", "--no-pager", "-C", str(vault.root), "--literal-pathspecs", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _checked_git(vault: Vault, *args: str) -> str:
    result = _git(vault, *args)
    if result.returncode:
        raise GitError(f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


@contextmanager
def _isolated_index(vault: Vault) -> Iterator[Path]:
    directory = vault.path(_INDEX_CACHE)
    fsutil.checked_regular_path(vault, directory / ".path-check")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="index-", dir=directory) as temporary:
        path = fsutil.checked_regular_path(vault, Path(temporary) / "index")
        token = _INDEX_CONTEXT.set((vault.root, path))
        try:
            yield path
        finally:
            _INDEX_CONTEXT.reset(token)


def _full_head(vault: Vault) -> str | None:
    result = _git(vault, "rev-parse", "--verify", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def transaction_commit(vault: Vault, transaction_id: str) -> str | None:
    """Find our explicit commit marker, including a recently moved branch."""
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise GitError("invalid Git transaction identity")
    result = _git(
        vault, "log", "--all", "--reflog", "-1", "--format=%H", "--fixed-strings",
        "--grep", f"Memory-Mesh-Transaction: {transaction_id}",
    )
    if result.returncode:
        if _full_head(vault) is None:
            return None
        raise GitError("Git publication outcome could not be inspected")
    return result.stdout.strip() or None


def reconcile_index(vault: Vault, commit: str) -> None:
    """Index-only, native Git compare-and-merge; never reset user stages.

    The two-tree merge preserves entries outside the published change and
    refuses overlapping staged changes. Git holds its own index lock while
    comparing and replacing the index. No working files are checked out.
    """
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise GitError("invalid published Git commit")
    token = _INDEX_CONTEXT.set(None)
    try:
        if not available(vault):
            raise GitError("Git index cannot be reconciled without this repository")
        ancestry = _git(vault, "merge-base", "--is-ancestor", commit, "HEAD")
        if ancestry.returncode:
            raise GitError("HEAD moved away from the published commit; user index left unchanged")
        parents = _checked_git(vault, "rev-list", "--parents", "-n", "1", commit).split()
        if len(parents) > 2 or not parents or parents[0] != commit:
            raise GitError("unexpected curator commit ancestry")
        if len(parents) == 2:
            base = parents[1]
        else:
            with _isolated_index(vault):
                _checked_git(vault, "read-tree", "--empty")
                base = _checked_git(vault, "write-tree")
        _checked_git(vault, "read-tree", "-i", "-m", base, commit)
    finally:
        _INDEX_CONTEXT.reset(token)


def available(vault: Vault) -> bool:
    try:
        result = _git(vault, "rev-parse", "--show-toplevel")
        return result.returncode == 0 and fsutil._comparison_path(
            Path(result.stdout.strip()).resolve()
        ) == fsutil._comparison_path(vault.root)
    except (OSError, FileNotFoundError):
        return False


def head_commit(vault: Vault) -> str | None:
    if not available(vault):
        return None
    r = _git(vault, "rev-parse", "--short", "--verify", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def dirty_paths(vault: Vault) -> list[str]:
    if not available(vault):
        return []
    r = _git(vault, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if r.returncode != 0:
        return []
    entries = iter(r.stdout.split("\0"))
    paths = []
    for entry in entries:
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            next(entries, None)
    return paths


def commit_paths(vault: Vault, rel_paths: list[str], message: str, author: str = CURATOR_AUTHOR) -> CommitResult:
    """Commit only literal named files, never directories or unrelated stages.

    A rejected commit never stages proposed blobs in the real index. An active
    curation boundary rolls back its working files. After a successful commit,
    index reconciliation either preserves user staging or fails explicitly;
    published files are never rolled back after Git has recorded their commit.
    No Git remains a supported, explicitly local-only mode.
    """
    from .curator.transaction import current_transaction

    tx = current_transaction(vault)
    with tx.publication_lock() if tx is not None else nullcontext():
        return _commit_paths(vault, rel_paths, message, author)


def _commit_paths(vault: Vault, rel_paths: list[str], message: str, author: str) -> CommitResult:
    from .collaboration import require_curator
    from .curator.transaction import CurationRecoveryError, current_transaction

    require_curator(vault)
    tx = current_transaction(vault)
    published: str | None = None

    def failed(detail: str) -> CommitResult:
        if tx is not None:
            try:
                tx.fail_publication(detail)
            except OSError as exc:
                raise CurationRecoveryError(
                    f"cannot record publication failure; recovery retained at {tx.journal_path}"
                ) from exc
        return CommitResult(published is not None, published, detail, True)

    try:
        if not available(vault):
            if vault.path(".git").exists():
                return failed("existing Git repository could not be inspected; manual inspection required")
            if tx is not None:
                tx.record_git_unavailable()
            return CommitResult(
                False, None, "git unavailable — changes written; manual commit required",
                manual_commit_required=True,
            )
        if not rel_paths:
            if tx is not None and tx.publishable_paths:
                return failed("Git publication omits all transaction-owned durable paths")
            return CommitResult(False, None, "nothing to commit")
        normalized = []
        for relative in rel_paths:
            if not isinstance(relative, str):
                return failed("invalid Git commit path")
            relative = relative.replace("\\", "/")
            if (not relative or relative.startswith("/") or ":" in relative
                    or any(p in ("", ".", "..") for p in relative.split("/"))
                    or relative.split("/")[0].casefold() == ".git"):
                return failed("invalid Git commit path")
            try:
                fsutil.checked_read_path(vault, vault.path(relative))
            except (fsutil.PathTraversalError, fsutil.WriteBoundaryError, OSError, RuntimeError):
                return failed("Git commit paths must be regular vault files")
            normalized.append(relative)
        rel_paths = sorted(set(normalized))
        if tx is not None:
            tx.validate()
            changed = tx.changed_paths
            rel_paths = [path for path in rel_paths if path in changed]
            missing = tx.publishable_paths - set(rel_paths)
            if missing:
                return failed(
                    "Git publication omits transaction-owned paths: " + ", ".join(sorted(missing))
                )
            if not rel_paths:
                return CommitResult(False, None, "nothing to commit")
        previous = _git(vault, "diff", "--cached", "--name-only", "-z", "--", *rel_paths)
        if previous.returncode:
            return failed(f"git index inspection failed: {previous.stderr.strip()}")
        if previous.stdout:
            return failed("requested paths already contain staged user changes; manual commit required")
        status = _git(vault, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *rel_paths)
        if status.returncode:
            return failed(f"git status failed: {status.stderr.strip()}")
        if not status.stdout:
            return CommitResult(False, None, "nothing to commit")
        identity = tx.journal["id"] if tx is not None else uuid.uuid4().hex
        if tx is not None:
            marker = tx.prepare_git_commit(isolated_index=True)
        else:
            marker = f"Memory-Mesh-Transaction: {identity}"
        message = f"{message}\n\n{marker}"
        base = _full_head(vault)
        with _isolated_index(vault):
            _checked_git(vault, "read-tree", base if base is not None else "--empty")
            _checked_git(vault, "add", "--all", "--", *rel_paths)
            staged = _checked_git(vault, "diff", "--cached", "--name-only", "-z", "--", *rel_paths)
            if not staged:
                return failed("Git staging produced no requested change; real index left unchanged")
            if tx is not None:
                tx.validate()
            if _full_head(vault) != base:
                return failed("Git HEAD changed during preparation; real index left unchanged")
            if tx is not None:
                tx.git_commit_started()
            commit_result = _git(
                vault, "-c", "user.name=curator", "-c", "user.email=curator@memory-mesh.local",
                "commit", "--only", "--author", author, "-m", message, "--", *rel_paths,
            )
            if tx is not None:
                tx.git_commit_finished()
            published = transaction_commit(vault, identity)
            if commit_result.returncode:
                return failed(
                    f"git commit failed: {commit_result.stderr.strip() or commit_result.stdout.strip()}; "
                    "real index left unchanged"
                )
            if published is None:
                return failed("Git returned success but its commit could not be verified")
        reconcile_index(vault, published)
        sha = _checked_git(vault, "rev-parse", "--short", "--verify", published)
        if tx is not None:
            tx.validate()
            tx.finish_git_commit(committed=True, sha=sha)
        return CommitResult(True, sha, "committed")
    except (OSError, GitError) as exc:
        return failed(f"git execution failed: {exc}; manual commit required")
