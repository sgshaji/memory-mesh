"""Note model: load Markdown files, read the two body conventions the
tooling depends on (`- [category] fact` and `- relation_type [[target]]`),
and resolve wikilinks to vault paths."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import config, frontmatter
from .config import Vault

OBSERVATION_RE = re.compile(r"^\s*-\s*\[([a-z][a-z0-9 _-]*)\]\s+(.+)$")
RELATION_RE = re.compile(r"^\s*-\s*([a-z_]+)\s+\[\[([^\]]+)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


@dataclass
class Note:
    path: Path
    meta: dict[str, Any]
    body: str
    vault: Vault | None = None
    parse_error: str | None = None

    @property
    def rel(self) -> str:
        if self.vault:
            return self.vault.rel(self.path)
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
    text = Path(path).read_text(encoding="utf-8")
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
    """
    ref = ref.strip().strip("/")
    if ref.endswith(".md"):
        ref = ref[:-3]
    if ".." in ref.split("/"):
        return None  # never resolve traversal-shaped refs
    direct = vault.path(ref + ".md")
    if direct.exists():
        return direct
    name = ref.split("/")[-1] + ".md"
    search_dirs = [*config.KNOWLEDGE_FOLDERS, config.PROJECTS, config.EPISODES, config.SKILLS]
    for d in search_dirs:
        base = vault.path(d)
        if not base.is_dir():
            continue
        cand = base / name
        if cand.exists():
            return cand
    skill = vault.path(config.SKILLS) / ref.split("/")[-1] / "SKILL.md"
    if skill.exists():
        return skill
    return None


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
