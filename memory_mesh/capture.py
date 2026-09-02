"""/learn — deliberate capture into 00-inbox/ (session-lifecycle.md L5).

One call, no prompts, no network: insight → safely stored candidate in
well under 15 seconds (Q1). Redaction runs BEFORE anything is written (G1).
Never touches canonical knowledge (P4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config, frontmatter, fsutil, redact
from .config import Vault
from .notes import iter_notes


@dataclass
class CaptureResult:
    path: Path
    created: bool  # False when an identical candidate already existed
    redacted: bool
    findings: list[redact.Finding]


def _content_hash(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _now_iso(now: datetime | None) -> str:
    dt = now or datetime.now().astimezone()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def learn(
    vault: Vault,
    text: str,
    source_tool: str = "cli",
    domain: str | None = None,
    project: str | None = None,
    trust: str = "first-party",
    now: datetime | None = None,
) -> CaptureResult:
    if not text or not text.strip():
        raise ValueError("nothing to capture")

    # Redact before persistence — the raw text never touches disk (G1).
    clean, findings = redact.redact(text, vault)
    chash = _content_hash(clean)

    # Idempotence (issues.md I-011): identical content already in the inbox
    # (still unprocessed) → return the existing candidate.
    for note in iter_notes(vault, config.INBOX):
        if note.meta.get("content_hash") == chash and "processed" not in note.meta:
            return CaptureResult(note.path, created=False, redacted=bool(findings), findings=findings)

    dt = now or datetime.now().astimezone()
    date = dt.strftime("%Y-%m-%d")
    slug = fsutil.safe_slug(clean, 48)
    filename = f"{date}-{fsutil.safe_slug(source_tool, 20)}-{slug}.md"
    path = fsutil.unique_path(vault.path(config.INBOX) / filename)

    title = clean.strip().splitlines()[0][:120]
    meta: dict = {
        "type": "candidate",
        "title": title,
        "source": f"/learn via {source_tool}, {date}",
        "captured": _now_iso(now),
        "domains": [domain] if domain else [],
        "trust": trust if trust in ("first-party", "mixed", "third-party", "unknown") else "unknown",
        "sensitivity": "redacted" if findings else "checked",
        "content_hash": chash,
    }
    if project:
        meta["project"] = project

    body = "## Observations\n" + "\n".join(
        f"- [observation] {line.strip()}" for line in clean.strip().splitlines() if line.strip()
    )
    written = fsutil.agent_write(vault, path, frontmatter.compose(meta, body))
    return CaptureResult(written, created=True, redacted=bool(findings), findings=findings)
