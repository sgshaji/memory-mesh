"""Filesystem safety: atomic writes, safe names, traversal guards and the
write-boundary enforcement that keeps canonical directories curator-only
(principles P4, mandate G4/G6/M)."""

from __future__ import annotations

import os
import re
import tempfile
import hashlib
import stat
import time
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .config import Vault, VaultError

if TYPE_CHECKING:
    from .curator.transaction import CurationTransaction


class PathTraversalError(VaultError):
    pass


class WriteBoundaryError(VaultError):
    pass


class WriteConflictError(VaultError):
    """The bytes at a destination no longer match the decision's input."""

    def __init__(self, path: Path, expected: str | None, actual: str | None):
        self.path, self.expected, self.actual = Path(path), expected, actual
        super().__init__(f"content conflict at {path}; changed bytes were not overwritten")


UNCHECKED = object()
_curation_context: ContextVar[CurationTransaction | None] = ContextVar("memory_mesh_curation", default=None)


_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_slug(text: str, max_len: int = 60) -> str:
    """Kebab-case slug safe on Windows and POSIX; never empty, never a
    reserved device name, never a dotfile, never path-traversing."""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s[:max_len].rstrip("-")
    if not s or s in _WINDOWS_RESERVED or set(s) == {"."}:
        s = "note"
    return s


def _comparison_path(path: Path) -> Path:
    """Compare equivalent Win32 spellings without treating devices as drives."""
    text = str(path)
    if os.name == "nt" and text.startswith("\\\\?\\"):
        remainder = text[4:]
        if remainder.upper().startswith("UNC\\"):
            return Path("\\\\" + remainder[4:])
        if re.match(r"^[A-Za-z]:\\", remainder):
            return Path(remainder)
    return path


def ensure_within(vault: Vault, path: Path) -> Path:
    """Resolve `path` and require it to live inside the vault root."""
    resolved = _comparison_path(Path(path).resolve())
    try:
        relative = resolved.relative_to(_comparison_path(vault.root))
    except ValueError:
        raise PathTraversalError(f"{path} escapes the vault root {vault.root}")
    return vault.root / relative


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def checked_regular_path(vault: Vault, path: Path) -> Path:
    """Reject redirected paths, including junctions and dangling symlinks."""
    path = Path(os.path.abspath(path))
    resolved = ensure_within(vault, path)
    if _comparison_path(resolved) != _comparison_path(path):
        raise PathTraversalError(f"{path} redirects through a link")
    for component in (path, *path.parents):
        if _comparison_path(component) == _comparison_path(vault.root):
            break
        if is_link(component):
            raise PathTraversalError(f"{path} redirects through a link")
    if path.exists() and not path.is_file():
        raise WriteBoundaryError(f"{path} must be a regular file")
    return resolved


def checked_read_path(vault: Vault, path: Path) -> Path:
    """Reject hard-linked read targets as well as path redirection."""
    resolved = checked_regular_path(vault, path)
    try:
        if resolved.stat().st_nlink > 1:
            raise PathTraversalError(f"{path} is a hard-linked read target")
    except FileNotFoundError:
        pass
    return resolved


def read_regular_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    """Check the opened file, not just a pathname that can change before read."""
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
        raise ValueError("read limit must be a nonnegative integer")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise WriteBoundaryError(f"{path} must be a regular read target")
        if info.st_nlink > 1:
            raise PathTraversalError(f"{path} is a hard-linked read target")
        if max_bytes is not None and info.st_size > max_bytes:
            raise WriteBoundaryError(f"{path} exceeds its read limit")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read() if max_bytes is None else source.read(max_bytes + 1)
        if max_bytes is not None and len(data) > max_bytes:
            raise WriteBoundaryError(f"{path} exceeds its read limit")
        if os.fstat(fd).st_nlink > 1:
            raise PathTraversalError(f"{path} is a hard-linked read target")
        return data
    finally:
        os.close(fd)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str | None:
    try:
        return content_hash(read_regular_bytes(Path(path)))
    except FileNotFoundError:
        return None


def _expect(path: Path, expected_hash) -> None:
    if expected_hash is UNCHECKED:
        return
    actual = file_hash(path)
    if actual != expected_hash:
        raise WriteConflictError(path, expected_hash, actual)


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes, *, expected_hash=UNCHECKED) -> None:
    """Adjacent durable replacement; caller supplies exclusion, not this helper.

    The final hash check is optimistic, not an OS compare-and-swap against
    arbitrary editors. Cooperating writers must hold the shared curator lock.
    """
    path = Path(path)
    _expect(path, expected_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mm-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(6):
            _expect(path, expected_hash)
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                if os.name != "nt" or exc.winerror not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (attempt + 1))
        _sync_directory(path.parent)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes, *, expected_hash=UNCHECKED) -> None:
    tx = _curation_context.get()
    if tx is not None and tx.handles(Path(path)):
        tx.write(Path(path), data, expected_hash=expected_hash)
    else:
        _atomic_write_bytes(path, data, expected_hash=expected_hash)


def atomic_write(path: Path, text: str, *, expected_hash=UNCHECKED) -> None:
    """Atomic UTF-8 replacement, optionally guarded by a SHA-256 input hash.

    ``None`` requires an absent destination; omitted means unchecked. An
    active curation transaction intercepts writes to its owned paths.
    """
    atomic_write_bytes(path, text.encode("utf-8"), expected_hash=expected_hash)


def _atomic_unlink(path: Path, *, expected_hash=UNCHECKED, missing_ok=False) -> None:
    _expect(path, expected_hash)
    Path(path).unlink(missing_ok=missing_ok)
    _sync_directory(Path(path).parent)


def _allowed(rel: str, boundaries: tuple[str, ...]) -> bool:
    return any(rel == b or rel.startswith(b.rstrip("/") + "/") for b in boundaries)


def _check(vault: Vault, path: Path, boundaries: tuple[str, ...], actor: str) -> Path:
    resolved = checked_regular_path(vault, path)
    rel = resolved.relative_to(vault.root).as_posix()
    if not _allowed(rel, boundaries):
        raise WriteBoundaryError(f"{actor} may not write {rel}")
    return resolved


def agent_write(vault: Vault, rel_or_path, text: str) -> Path:
    """Write path for agents/hosts: inbox, episodes, projects, session state.
    Never knowledge/, never indexes, never skills (P4)."""
    p = vault.path(rel_or_path) if isinstance(rel_or_path, str) else Path(rel_or_path)
    resolved = _check(vault, p, config.AGENT_WRITABLE, "agent")
    atomic_write(resolved, text)
    return resolved


def curator_write(vault: Vault, rel_or_path, text: str, *, expected_hash=UNCHECKED) -> Path:
    """Write path for the curator. It may write knowledge/**, episode status
    transitions, inbox `processed:` marks, packs and its own logs — and
    nothing else (curator.md §1, §9: never skills/ bodies).

    A complete read/decide/write run must opt into curation_transaction.
    Outside that context this remains a single atomic write, without acquiring
    a lock that an existing V2 caller may already own.
    """
    p = vault.path(rel_or_path) if isinstance(rel_or_path, str) else Path(rel_or_path)
    resolved = _check(vault, p, config.CURATOR_WRITABLE, "curator")
    if _allowed(resolved.relative_to(vault.root).as_posix(), (config.SKILLS,)):
        raise WriteBoundaryError("curator never edits skills/ bodies")
    from .collaboration import require_curator
    from .curator.transaction import current_transaction

    require_curator(vault)
    tx = current_transaction(vault)
    if tx is not None:
        tx.write(resolved, text.encode("utf-8"), expected_hash=expected_hash)
    else:
        atomic_write(resolved, text, expected_hash=expected_hash)
    return resolved


def curator_unlink(vault: Vault, rel_or_path, *, missing_ok: bool = False) -> None:
    """Journaled deletion. Direct Path.unlink bypasses transaction protection."""
    from .curator.transaction import current_transaction, curation_transaction

    path = vault.path(rel_or_path) if isinstance(rel_or_path, str) else Path(rel_or_path)
    path = _check(vault, path, config.CURATOR_WRITABLE, "curator")
    tx = current_transaction(vault)
    if tx is not None:
        tx.unlink(path, missing_ok=missing_ok)
    else:
        with curation_transaction(vault, inputs=(path,)) as tx:
            tx.unlink(path, missing_ok=missing_ok)


def curator_rename(vault: Vault, source, destination) -> Path:
    """Recoverable move without overwriting an existing destination."""
    from .curator.transaction import current_transaction, curation_transaction

    source = vault.path(source) if isinstance(source, str) else Path(source)
    destination = vault.path(destination) if isinstance(destination, str) else Path(destination)
    source = _check(vault, source, config.CURATOR_WRITABLE, "curator")
    destination = _check(vault, destination, config.CURATOR_WRITABLE, "curator")
    tx = current_transaction(vault)
    if tx is not None:
        return tx.rename(source, destination)
    with curation_transaction(vault, inputs=(source, destination)) as tx:
        return tx.rename(source, destination)


def append_line(path: Path, line: str) -> None:
    """Append-only helper for logs (recall-log, curation-log). Appends are not
    atomic across crashes but never corrupt prior content."""
    path = Path(path)
    tx = _curation_context.get()
    if tx is not None and tx.handles(path):
        previous = tx.read_bytes(path, missing_ok=True) or b""
        tx.write(path, previous + (line.rstrip("\n") + "\n").encode("utf-8"))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line.rstrip("\n") + "\n")


def unique_path(path: Path) -> Path:
    """First free of  x.md, x-2.md, x-3.md …"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        cand = path.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError(f"could not find a free name for {path}")
