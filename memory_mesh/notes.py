"""Note model: load Markdown files, read the two body conventions the
tooling depends on (`- [category] fact` and `- relation_type [[target]]`),
and resolve wikilinks to vault paths."""

from __future__ import annotations

import re
import os
from pathlib import PureWindowsPath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import config, frontmatter, fsutil
from .config import Vault, VaultError

OBSERVATION_RE = re.compile(r"^\s*-\s*\[([a-z][a-z0-9 _-]*)\]\s+(.+)$")
RELATION_RE = re.compile(r"^\s*-\s*([a-z_]+)\s+\[\[([^\]]+)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


class NoteReferenceError(VaultError):
    """Invalid, escaping, or ambiguous references are not missing notes."""


@dataclass
class Note:
    path: Path
    meta: dict[str, Any]
    body: str
    vault: Vault | None = None
    parse_error: str | None = None

    def __post_init__(self) -> None:
        self._identity: tuple[Path, Path, str] | None = None

    @property
    def rel(self) -> str:
        """Snapshot identity; filesystem access helpers still recheck live paths."""
        if self.vault:
            if self._identity is None or self._identity[:2] != (self.path, self.vault.root):
                self._identity = (self.path, self.vault.root, self.vault.rel(self.path))
            return self._identity[2]
        return self.path.as_posix()

    @property
    def ref(self) -> str:
        """Vault-relative path without extension — the wikilink/evidence form."""
        rel = self.rel
        return rel[:-3] if rel.endswith(".md") else rel

    @property
    def type(self) -> str | None:
        t = self.meta.get("type")
        return t if isinstance(t, str) else None

    @property
    def status(self) -> str | None:
        s = self.meta.get("status")
        return s if isinstance(s, str) else None

    @property
    def title(self) -> str:
        t = self.meta.get("title")
        if isinstance(t, str) and t:
            return t
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return self.path.stem

    def observations(self) -> list[tuple[str, str]]:
        return [(m.group(1), m.group(2).strip()) for line in self.body.splitlines() if (m := OBSERVATION_RE.match(line))]

    def relations(self) -> list[tuple[str, str]]:
        return [(m.group(1), m.group(2).strip()) for line in self.body.splitlines() if (m := RELATION_RE.match(line))]

    def observations_block(self) -> str:
        """The `## Observations` section verbatim (for context packs)."""
        return section(self.body, "Observations")

    def wikilinks(self) -> list[str]:
        return [m.group(1).strip() for m in WIKILINK_RE.finditer(self.body)]


def section(body: str, heading: str) -> str:
    """Return the content of a `## <heading>` section (without the heading)."""
    lines = body.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^#{1,2}\s", line):
            break
        if inside:
            out.append(line)
    return "\n".join(out).strip("\n")


def load_note(path: Path, vault: Vault | None = None) -> Note:
    if vault is not None:
        path = fsutil.checked_read_path(vault, Path(path))
    tx = fsutil._curation_context.get()
    if vault is not None and tx is not None and tx.vault.root == vault.root:
        data = tx.read_bytes(Path(path))
        if data is None:
            raise FileNotFoundError(path)
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = fsutil.read_regular_bytes(Path(path)).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    try:
        meta, body = frontmatter.parse(text)
        return Note(Path(path), meta, body, vault)
    except frontmatter.FrontmatterError as e:
        # Malformed files stay loadable as data so lint can report them.
        return Note(Path(path), {}, text, vault, parse_error=str(e))


def resolve_ref(vault: Vault, ref: str) -> Path | None:
    """Resolve a wikilink/evidence ref to an existing file.

    Accepts vault-relative refs (`knowledge/patterns/x`, `episodes/2026-...`)
    and bare slugs (`x`), with or without `.md`.

    Missing valid refs return None. Malformed, ambiguous, or redirected refs
    raise NoteReferenceError. A qualified ref never falls back to a basename.
    """
    if not isinstance(ref, str):
        raise NoteReferenceError("note reference must be a string")
    ref = ref.strip().replace("\\", "/")
    parts = ref.split("/")
    if (not ref or ref.startswith("/") or PureWindowsPath(ref).drive
            or any(c in ref for c in ':*?"<>|\0') or any(ord(c) < 32 for c in ref)
            or any(p in ("", ".", "..") or p.rstrip(" .") != p for p in parts)):
        raise NoteReferenceError(f"invalid vault-relative note reference: {ref!r}")
    if any(p.split(".")[0].casefold() in fsutil._WINDOWS_RESERVED for p in parts):
        raise NoteReferenceError(f"reserved note reference: {ref!r}")
    name = ref if ref.lower().endswith(".md") else ref + ".md"

    def checked(path: Path) -> Path | None:
        try:
            path = fsutil.checked_read_path(vault, path)
        except (fsutil.PathTraversalError, fsutil.WriteBoundaryError, OSError, RuntimeError) as exc:
            raise NoteReferenceError(f"unsafe note reference: {ref!r}") from exc
        return path if path.is_file() else None

    if "/" in ref:
        return checked(vault.path(name))
    matches: set[Path] = set()
    direct = checked(vault.path(name))
    if direct is not None:
        matches.add(direct)
    search_dirs = [*config.KNOWLEDGE_FOLDERS, config.PROJECTS, config.EPISODES, config.SKILLS]
    for d in search_dirs:
        base = vault.path(d)
        if not base.is_dir() or fsutil.is_link(base):
            continue
        try:
            if base.resolve() != base or not base.resolve().is_relative_to(vault.root):
                raise NoteReferenceError(f"unsafe note search directory: {d}")
            for parent, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = [child for child in dirs if not (
                    fsutil.is_link(Path(parent) / child)
                )]
                for filename in files:
                    if filename == name or (
                        os.name == "nt" and filename.casefold() == name.casefold()
                    ):
                        target = checked(Path(parent) / filename)
                        if target is not None:
                            matches.add(target)
        except OSError as exc:
            raise NoteReferenceError(f"cannot inspect note references under {d}") from exc
    slug = ref[:-3] if ref.lower().endswith(".md") else ref
    skill = checked(vault.path(config.SKILLS) / slug / "SKILL.md")
    if skill is not None:
        matches.add(skill)
    if len(matches) > 1:
        raise NoteReferenceError(f"ambiguous note reference {ref!r}; use a full vault-relative path")
    return next(iter(matches), None)


def iter_notes(vault: Vault, *rel_dirs: str) -> Iterator[Note]:
    """Yield notes under the given vault-relative directories (recursive)."""
    for rel in rel_dirs:
        base = vault.path(rel)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name == ".gitkeep":
                continue
            yield load_note(path, vault)


def knowledge_notes(vault: Vault) -> list[Note]:
    return [n for n in iter_notes(vault, config.KNOWLEDGE) if n.type != "index"]
