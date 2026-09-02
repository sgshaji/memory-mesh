"""Review-file mechanics (curator.md §7): gated decisions are written as
checkbox blocks; ticking `[x] approve` and committing is the approval; the
next run applies approved items and archives the file."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import config, fsutil
from ..config import Vault
from .decisions import Decision

__all__ = [
    "ReviewItem", "review_path", "write_review_file", "parse_review_file",
    "pending_review_files", "archive_review_file", "is_fully_decided",
    "load_suppressions", "record_suppression", "suppression_key", "SUPPRESSIONS",
]

_PAYLOAD_RE = re.compile(r"<!--\s*mm:payload\s+(\{.*?\})\s*-->", re.S)
_HEADER_RE = re.compile(r"^##\s+(CREATE|UPDATE|MERGE|SUPERSEDE|REJECT|HOLD|FLAG)\s+(.*)$")
_APPROVE_RE = re.compile(r"\[[xX]\]\s*approve")
# Every alternative the spec offers is a decision too: ticking one must retire
# the item, not leave it to be re-proposed on the next run (curator.md §7).
_ALTERNATIVE_RE = re.compile(r"\[[xX]\]\s*(keep both|keep as candidate|edit|hold|acknowledged)", re.I)


@dataclass
class ReviewItem:
    kind: str
    header: str
    approved: bool
    payload: dict = field(default_factory=dict)
    choice: str = ""  # the alternative ticked, when not approved

    @property
    def decided(self) -> bool:
        """Any ticked box counts as a human decision on this item."""
        return self.approved or bool(self.choice)


def review_path(vault: Vault, run_date: date) -> Path:
    return vault.path(config.REVIEW_DIR) / f"{run_date.isoformat()}.md"


def _render_block(d: Decision) -> str:
    lines = []
    if d.kind == "MERGE":
        lines.append(f"## MERGE  {d.target_ref}  ←  {d.other_ref}")
    elif d.kind == "SUPERSEDE":
        lines.append(f"## SUPERSEDE  {d.target_ref}  →  {d.payload.get('new_ref', '<new note>')}")
    elif d.kind == "REJECT":
        lines.append(f"## REJECT  {d.target_ref or d.source_ref}")
    else:
        lines.append(f"## {d.kind}  {d.target_ref or d.source_ref}")
    lines.append(f"Why: {d.rationale}")
    if d.claim:
        lines.append(f"Claim: {d.claim}")
    if d.kind == "MERGE":
        draft = d.payload.get("draft", "")
        if draft:
            lines.append("Result note (draft):")
            lines.extend("> " + l for l in draft.splitlines())
        lines.append("[ ] approve   [ ] keep both   [ ] edit")
    elif d.kind == "SUPERSEDE":
        if d.payload.get("diff"):
            lines.append("Diff:")
            lines.extend("> " + l for l in str(d.payload["diff"]).splitlines())
        lines.append("[ ] approve   [ ] hold")
    elif d.kind == "REJECT":
        lines.append("[ ] approve   [ ] keep as candidate")
    else:
        lines.append("[ ] acknowledged")
    if d.gated:
        lines.append(f"<!-- mm:payload {d.payload_json()} -->")
    return "\n".join(lines)


def write_review_file(vault: Vault, run_id: str, run_date: date, decisions: list[Decision]) -> Path | None:
    """Append gated decisions (and HOLD/FLAG notices) to today's review file.
    Existing manual ticks in the file are preserved."""
    items = [d for d in decisions if d.gated or d.kind in ("HOLD", "FLAG")]
    if not items:
        return None
    path = review_path(vault, run_date)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# Review {run_date.isoformat()} — run {run_id}\n"
    blocks = [existing.rstrip("\n")]
    for d in items:
        block = _render_block(d)
        # idempotent re-run: don't append a block that is already present
        if block.splitlines()[0] not in existing:
            blocks.append(block)
    if len(blocks) == 1:
        return path if path.exists() else None
    fsutil.curator_write(vault, path, "\n\n".join(blocks) + "\n")
    return path


def parse_review_file(path: Path) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    text = path.read_text(encoding="utf-8")
    current: ReviewItem | None = None
    block_lines: list[str] = []

    def close() -> None:
        nonlocal current
        if current is None:
            return
        block = "\n".join(block_lines)
        current.approved = bool(_APPROVE_RE.search(block))
        alt = _ALTERNATIVE_RE.search(block)
        current.choice = alt.group(1).lower() if alt and not current.approved else ""
        m = _PAYLOAD_RE.search(block)
        if m:
            try:
                current.payload = json.loads(m.group(1))
            except json.JSONDecodeError:
                current.payload = {}
        items.append(current)
        current = None

    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            close()
            current = ReviewItem(m.group(1), m.group(2).strip(), approved=False)
            block_lines = []
        elif current is not None:
            block_lines.append(line)
    close()
    return items


SUPPRESSIONS = "_meta/review/decided.tsv"


def suppression_key(kind: str, *refs: str) -> str:
    return kind + "\t" + "|".join(sorted(r.split("/")[-1] for r in refs if r))


def load_suppressions(vault: Vault) -> dict[str, str]:
    """Decisions the human already made ("keep both", "hold", …) so the same
    proposal is not regenerated on every subsequent run."""
    path = vault.path(SUPPRESSIONS)
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            out[parts[0] + "\t" + parts[1]] = parts[2]
    return out


def record_suppression(vault: Vault, key: str, choice: str, when: str) -> None:
    fsutil.append_line(vault.path(SUPPRESSIONS), f"{key}\t{choice}\t{when}")


def pending_review_files(vault: Vault) -> list[Path]:
    base = vault.path(config.REVIEW_DIR)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*.md") if p.is_file())


def is_fully_decided(items: list[ReviewItem]) -> bool:
    """A file is done when every gated item has a ticked box. HOLD/FLAG
    notices need an explicit `[x] acknowledged` before the file retires."""
    gated = [i for i in items if i.kind in ("MERGE", "SUPERSEDE", "REJECT")]
    notices = [i for i in items if i.kind in ("HOLD", "FLAG")]
    if not gated and not notices:
        return False
    return all(i.decided for i in gated) and all(i.decided for i in notices)


def archive_review_file(vault: Vault, path: Path) -> Path:
    """Archiving happens only after approved items were applied."""
    dest = vault.path(config.REVIEW_ARCHIVE) / path.name
    dest = fsutil.unique_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.replace(dest)
    return dest
