"""Filesystem safety: atomic writes, safe names, traversal guards and the
write-boundary enforcement that keeps canonical directories curator-only
(principles P4, mandate G4/G6/M)."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from . import config
from .config import Vault


class PathTraversalError(Exception):
    pass


class WriteBoundaryError(Exception):
    pass


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


def ensure_within(vault: Vault, path: Path) -> Path:
    """Resolve `path` and require it to live inside the vault root."""
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(vault.root)
    except ValueError:
        raise PathTraversalError(f"{path} escapes the vault root {vault.root}")
    return resolved


def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + os.replace so an interruption never leaves a
    truncated file. UTF-8, LF newlines."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mm-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _allowed(rel: str, boundaries: tuple[str, ...]) -> bool:
    return any(rel == b or rel.startswith(b.rstrip("/") + "/") for b in boundaries)


def _check(vault: Vault, path: Path, boundaries: tuple[str, ...], actor: str) -> Path:
    resolved = ensure_within(vault, path)
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


def curator_write(vault: Vault, rel_or_path, text: str) -> Path:
    """Write path for the curator. It may write knowledge/**, episode status
    transitions, inbox `processed:` marks, packs and its own logs — and
    nothing else (curator.md §1, §9: never skills/ bodies)."""
    p = vault.path(rel_or_path) if isinstance(rel_or_path, str) else Path(rel_or_path)
    resolved = _check(vault, p, config.CURATOR_WRITABLE, "curator")
    if _allowed(resolved.relative_to(vault.root).as_posix(), (config.SKILLS,)):
        raise WriteBoundaryError("curator never edits skills/ bodies")
    atomic_write(resolved, text)
    return resolved


def append_line(path: Path, line: str) -> None:
    """Append-only helper for logs (recall-log, curation-log). Appends are not
    atomic across crashes but never corrupt prior content."""
    path = Path(path)
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
