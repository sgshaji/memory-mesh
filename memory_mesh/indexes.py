"""Domain indexes: the curated maps recall follows (domain-index.md).

Only the curator edits these files; agents read them. An index is a pointer
file — twelve links at most, fixed sections, never note bodies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config, frontmatter, fsutil, tokens
from .applicability import match_applicability
from .config import Vault
from .notes import WIKILINK_RE, Note, load_note, resolve_ref
from .schema import Issue, KNOWLEDGE_TYPES

SECTIONS = (
    "Read first",
    "Known failures",
    "Current workarounds",
    "Active project",
    "Recently verified (30 days)",
    "Recently changed",
)
# Sections whose links count against the ≤12 budget and feed recall.
LINK_SECTIONS = ("Read first", "Known failures", "Current workarounds", "Active project")
VALIDATED_ONLY_SECTIONS = ("Read first", "Current workarounds", "Recently verified (30 days)")


def _same_reference(entry: str, requested: str) -> bool:
    entry, requested = entry.removesuffix(".md"), requested.removesuffix(".md")
    if "/" in entry and "/" in requested:
        return entry == requested
    return entry.rsplit("/", 1)[-1] == requested.rsplit("/", 1)[-1]


def eligible_for_section(
    note: Note, section_name: str, *, now: datetime | date | None = None,
    task_bound: bool = False,
) -> bool:
    """Current index eligibility, independent of reported confidence or popularity."""
    if "v2_admission" in note.meta and not task_bound:
        return False
    if section_name in VALIDATED_ONLY_SECTIONS and note.status != "validated":
        return False
    if section_name == "Known failures" and note.status in ("stale", "resolved", "superseded", "rejected", "inactive"):
        return False
    if note.type in KNOWLEDGE_TYPES and section_name != "Recently changed":
        if note.status in ("stale", "resolved", "superseded", "rejected", "inactive"):
            return False
        if match_applicability(note.meta.get("applies_to"), now=now).state == "mismatch":
            return False
    return True


@dataclass
class Entry:
    ref: str
    gloss: str = ""

    def render(self) -> str:
        return f"- [[{self.ref}]] — {self.gloss}" if self.gloss else f"- [[{self.ref}]]"


@dataclass
class DomainIndex:
    domain: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, list[Entry]] = field(default_factory=dict)
    title: str = ""

    def all_entries(self) -> list[tuple[str, Entry]]:
        return [(s, e) for s in SECTIONS for e in self.sections.get(s, [])]

    def link_count(self) -> int:
        return sum(len(self.sections.get(s, [])) for s in LINK_SECTIONS)

    def find(self, ref: str) -> list[tuple[str, Entry]]:
        return [(s, e) for s, e in self.all_entries() if _same_reference(e.ref, ref)]

    def remove(self, ref: str) -> None:
        for s in SECTIONS:
            self.sections[s] = [e for e in self.sections.get(s, []) if not _same_reference(e.ref, ref)]

    def add(self, section_name: str, ref: str, gloss: str = "") -> None:
        entries = self.sections.setdefault(section_name, [])
        if not any(e.ref == ref for e in entries):
            entries.append(Entry(ref, gloss))


_ENTRY_RE = re.compile(r"^\s*-\s*(.+?)\s*$")


def _parse_entry(line: str) -> Entry | None:
    m = WIKILINK_RE.search(line)
    if not m:
        return None
    ref = m.group(1).strip()
    after = line[m.end():].strip()
    gloss = re.sub(r"^[—–\-:\s]+", "", after).strip()
    return Entry(ref, gloss)


def parse_index(path: Path, vault: Vault) -> DomainIndex:
    note = load_note(path, vault)
    di = DomainIndex(domain=str(note.meta.get("domain") or path.stem), path=Path(path), meta=note.meta)
    current: str | None = None
    for line in note.body.splitlines():
        if line.startswith("# "):
            di.title = line[2:].strip()
            continue
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            di.sections.setdefault(current, [])
            continue
        if current and _ENTRY_RE.match(line):
            e = _parse_entry(line)
            if e:
                di.sections[current].append(e)
    return di


def render_index(di: DomainIndex, updated: str) -> str:
    meta = {
        "type": "index",
        "domain": di.domain,
        "updated": updated,
        "links": di.link_count(),  # derived, never hand-counted (issues.md I-009)
    }
    lines = [f"# {di.title or di.domain}"]
    for s in SECTIONS:
        lines.append("")
        lines.append(f"## {s}")
        for e in di.sections.get(s, []):
            lines.append(e.render())
    return frontmatter.compose(meta, "\n".join(lines))


def write_index_if_changed(vault: Vault, di: DomainIndex, updated: str) -> bool:
    """Do not rewrite an index merely because the clock or curator run changed."""
    path = fsutil.checked_regular_path(vault, di.path)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    old_stamp = di.meta.get("updated")
    stable = render_index(di, old_stamp if isinstance(old_stamp, str) else updated)
    if stable == previous:
        return False
    rendered = render_index(di, updated)
    if rendered == previous:
        return False
    fsutil.curator_write(vault, path, rendered)
    di.meta.update(updated=updated, links=di.link_count())
    return True


def index_path(vault: Vault, domain: str) -> Path:
    return vault.path(config.INDEX_DIR) / f"{domain}.md"


def load_index(vault: Vault, domain: str) -> DomainIndex | None:
    p = index_path(vault, domain)
    return parse_index(p, vault) if p.exists() else None


def validate_index(di: DomainIndex, vault: Vault) -> list[Issue]:
    issues: list[Issue] = []
    rel = vault.rel(di.path)

    def err(msg: str) -> None:
        issues.append(Issue(rel, "error", msg))

    def warn(msg: str) -> None:
        issues.append(Issue(rel, "warning", msg))

    if di.link_count() > config.INDEX_MAX_LINKS:
        err(f"{di.link_count()} links in link sections (max {config.INDEX_MAX_LINKS}): one must leave")
    declared = di.meta.get("links")
    if isinstance(declared, int) and declared != di.link_count():
        warn(f"frontmatter `links: {declared}` drifted from actual {di.link_count()}")
    for s in SECTIONS:
        if s not in di.sections:
            err(f"missing fixed section `## {s}` (empty sections stay)")
    for s in di.sections:
        if s not in SECTIONS:
            warn(f"unknown section `## {s}`")
    for s, e in di.all_entries():
        target = resolve_ref(vault, e.ref)
        if target is None:
            err(f"[[{e.ref}]] does not resolve to a note")
            continue
        tnote = load_note(target, vault)
        if s in VALIDATED_ONLY_SECTIONS and tnote.status != "validated":
            err(f"[[{e.ref}]] under `{s}` has status `{tnote.status}` — only validated notes belong there")
        if s == "Known failures" and tnote.status in ("resolved", "superseded", "stale"):
            err(f"[[{e.ref}]] under `Known failures` is {tnote.status} — move to Recently changed")
        if (
            tnote.type in KNOWLEDGE_TYPES and "v2_admission" not in tnote.meta
            and s in (*LINK_SECTIONS, "Recently verified (30 days)")
            and match_applicability(tnote.meta.get("applies_to")).state == "mismatch"
        ):
            err(f"[[{e.ref}]] under `{s}` is outside its current applicability window")
        if len(e.gloss.split()) > 12 and s in LINK_SECTIONS:
            warn(f"gloss for [[{e.ref}]] exceeds twelve words")
    body_tokens = tokens.estimate(di.path.read_text(encoding="utf-8"))
    if body_tokens > config.TOKEN_BUDGET_INDEX:
        warn(f"index estimates {body_tokens} tokens (budget {config.TOKEN_BUDGET_INDEX})")
    return issues


def list_domain_indexes(vault: Vault) -> list[DomainIndex]:
    out = []
    base = vault.path(config.INDEX_DIR)
    if not base.is_dir():
        return out
    for p in sorted(base.glob("*.md")):
        if p.name.startswith("_domains"):
            continue
        out.append(parse_index(p, vault))
    return out
