"""Human review blocks with source/target snapshots for destructive decisions.

New legacy proposals bind their inputs with expected_hashes. Unbound older
approvals require a fresh proposal and approval, never an automatic rebase.
Archiving uses the enclosing curator transaction so failed runs retain intent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import config, fsutil
from ..config import Vault
from ..notes import resolve_ref
from .decisions import Decision
from .transaction import current_transaction

__all__ = [
    "ReviewItem", "review_path", "write_review_file", "parse_review_file",
    "pending_review_files", "archive_review_file", "is_fully_decided",
    "load_suppressions", "record_suppression", "suppression_key", "SUPPRESSIONS",
    "review_input_paths",
    "retire_review_items",
]

_PAYLOAD_RE = re.compile(r"<!--\s*mm:payload\s+(\{.*?\})\s*-->", re.S)
_HEADER_RE = re.compile(r"^##\s+(CREATE|UPDATE|MERGE|SUPERSEDE|REJECT|ADMIT|HOLD|FLAG)\s+(.*)$")
_ACTION_LINE_RE = re.compile(
    r"^[ \t]*(?:-[ \t]+)?(?:\[[ xX]\][ \t]*"
    r"(?:approve|keep both|keep as candidate|edit|hold|acknowledged)[ \t]*)+$",
    re.I,
)
# Every alternative the spec offers is a decision too: ticking one must retire
# the item, not leave it to be re-proposed on the next run (curator.md §7).
_SELECTED_RE = re.compile(r"\[[xX]\]\s*(approve|keep both|keep as candidate|edit|hold|acknowledged)", re.I)
_CHOICES = {
    "ADMIT": {"approve", "hold"},
    "MERGE": {"approve", "keep both", "edit"},
    "SUPERSEDE": {"approve", "hold"},
    "REJECT": {"approve", "keep as candidate"},
}


@dataclass
class ReviewItem:
    kind: str
    header: str
    approved: bool
    payload: dict = field(default_factory=dict)
    choice: str = ""  # the alternative ticked, when not approved
    error: str = ""

    @property
    def decided(self) -> bool:
        """Any ticked box counts as a human decision on this item."""
        return self.approved or bool(self.choice)


def review_path(vault: Vault, run_date: date) -> Path:
    return vault.path(config.REVIEW_DIR) / f"{run_date.isoformat()}.md"


def review_input_paths(vault: Vault, payload: dict) -> dict[str, Path]:
    """Resolve reviewed inputs, including a not-yet-created replacement note."""
    paths = {}
    for field_name in ("source_ref", "target", "other", "new_ref"):
        value = payload.get(field_name)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError(f"review {field_name} must be a note reference")
        path = resolve_ref(vault, value)
        if path is None:
            relative = value.strip().replace("\\", "/")
            if "/" not in relative:
                raise ValueError(f"review {field_name} needs a full vault-relative reference")
            if not relative.lower().endswith(".md"):
                relative += ".md"
            path = fsutil.checked_regular_path(vault, vault.path(relative))
        paths[field_name] = path
    return paths


def _bind_review_hashes(vault: Vault, decision: Decision) -> None:
    if decision.kind not in ("MERGE", "SUPERSEDE", "REJECT"):
        return  # V2 ADMIT retains its stronger request-digest/attestation checks.
    payload = dict(decision.payload)
    if decision.source_ref:
        payload["source_ref"] = decision.source_ref
    if not payload.get("target") and (decision.target_ref or decision.source_ref):
        payload["target"] = decision.target_ref or decision.source_ref
    if not payload.get("other") and decision.other_ref:
        payload["other"] = decision.other_ref
    if "expected_hashes" not in payload:
        tx = current_transaction(vault)
        hashes = {}
        for path in review_input_paths(vault, payload).values():
            if tx is not None:
                data = tx.read_bytes(path, missing_ok=True)
                digest = fsutil.content_hash(data) if data is not None else None
            else:
                digest = fsutil.file_hash(path)
            hashes[vault.rel(path)] = digest
        payload["expected_hashes"] = hashes
    decision.payload = payload


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
        lines.append("Claim:")
        lines.extend("> " + line for line in d.claim.splitlines())
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
    elif d.kind == "ADMIT":
        lines.append("[ ] approve   [ ] hold")
    else:
        lines.append("[ ] acknowledged")
    if d.gated or d.payload:
        lines.append(f"<!-- mm:payload {d.payload_json()} -->")
    return "\n".join(lines)


def write_review_file(vault: Vault, run_id: str, run_date: date, decisions: list[Decision]) -> Path | None:
    """Append gated decisions (and HOLD/FLAG notices) to today's review file.
    Existing manual ticks in the file are preserved."""
    items = [d for d in decisions if d.gated or d.kind in ("HOLD", "FLAG")]
    if not items:
        return None
    queued = {
        item.payload["review_key"]
        for pending in pending_review_files(vault) for item in parse_review_file(pending)
        if item.payload.get("review_only") is True and isinstance(item.payload.get("review_key"), str)
    }
    suppressed = load_suppressions(vault)
    path = review_path(vault, run_date)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# Review {run_date.isoformat()} — run {run_id}\n"
    blocks = [existing.rstrip("\n")]
    for d in items:
        key = d.payload.get("review_key") if d.payload.get("review_only") is True else None
        if isinstance(key, str) and (key in queued or "ATTENTION\t" + key in suppressed):
            continue
        _bind_review_hashes(vault, d)
        block = _render_block(d)
        # idempotent re-run: don't append a block that is already present
        if isinstance(key, str) or block.splitlines()[0] not in existing:
            blocks.append(block)
            if isinstance(key, str):
                queued.add(key)
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
        actions = "\n".join(line for line in block_lines if _ACTION_LINE_RE.fullmatch(line))
        selected = [choice.lower() for choice in _SELECTED_RE.findall(actions)]
        allowed = _CHOICES.get(current.kind, {"acknowledged"})
        if len(selected) > 1 or any(choice not in allowed for choice in selected):
            current.error = "select exactly one of the generated review actions"
        elif selected:
            current.approved = selected[0] == "approve"
            current.choice = "" if current.approved else selected[0]
        m = _PAYLOAD_RE.search(block)
        if m:
            try:
                payload = json.loads(m.group(1))
                if not isinstance(payload, dict):
                    current.error = "review payload must be a JSON object"
                else:
                    current.payload = payload
            except json.JSONDecodeError:
                current.error = "malformed review payload"
        elif current.kind in _CHOICES:
            current.error = "missing review payload"
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
    gated = [i for i in items if i.kind in ("MERGE", "SUPERSEDE", "REJECT", "ADMIT")]
    notices = [i for i in items if i.kind in ("HOLD", "FLAG")]
    if not gated and not notices:
        return False
    return all(i.decided and not i.error for i in gated + notices)


def archive_review_file(vault: Vault, path: Path) -> Path:
    """Archiving happens only after approved items were applied."""
    dest = vault.path(config.REVIEW_ARCHIVE) / path.name
    dest = fsutil.unique_path(dest)
    return fsutil.curator_rename(vault, path, dest)


def retire_review_items(vault: Vault, path: Path, retired: set[int]) -> Path | None:
    """Archive completed blocks without replaying them while other items wait.

    Both writes belong to the enclosing transaction, so publication/application
    failure restores the original approved file and removes the partial archive.
    """
    if not retired:
        return None
    path = fsutil.checked_regular_path(vault, path)
    prefix: list[str] = []
    blocks: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if _HEADER_RE.match(line.rstrip("\r\n")):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
        else:
            prefix.append(line)
    if any(index < 0 or index >= len(blocks) for index in retired):
        raise ValueError("review item positions changed before retirement")
    if len(retired) == len(blocks):
        return archive_review_file(vault, path)
    header = "".join(prefix)
    archived = header + "".join("".join(block) for index, block in enumerate(blocks) if index in retired)
    pending = header + "".join("".join(block) for index, block in enumerate(blocks) if index not in retired)
    destination = fsutil.unique_path(vault.path(config.REVIEW_ARCHIVE) / path.name)
    fsutil.curator_write(vault, destination, archived)
    fsutil.curator_write(vault, path, pending)
    return destination
