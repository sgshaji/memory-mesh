"""Context packs: a domain index compiled with note bodies inlined, for
cloud/Lane B consumers (domain-index.md §Context pack). Disposable and
reproducible; the 2,000-token ceiling is hard (Q6)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import config, frontmatter, fsutil, gitutil, tokens
from .config import Vault
from .indexes import SECTIONS, load_index
from .notes import load_note, resolve_ref

_PRIORITY = (
    "Read first",
    "Known failures",
    "Current workarounds",
    "Active project",
    "Recently verified (30 days)",
    "Recently changed",
)


class PackError(Exception):
    pass


def _note_block(vault: Vault, ref: str) -> str | None:
    path = resolve_ref(vault, ref)
    if path is None:
        return None
    note = load_note(path, vault)
    ap = note.meta.get("applies_to")
    lines = [f"### {note.title}"]
    detail = []
    if ap:
        detail.append(f"applies_to: {frontmatter._dump_value(ap)}")
    if note.meta.get("confidence"):
        detail.append(f"confidence: {note.meta['confidence']}")
    if note.meta.get("last_verified"):
        detail.append(f"last_verified: {note.meta['last_verified']}")
    if detail:
        lines.append("· ".join(detail))
    obs = note.observations_block()
    if obs:
        lines.append(obs)
    return "\n".join(lines)


def compile_pack(vault: Vault, domain: str, now: datetime | None = None) -> Path:
    """Deterministic compile of `outputs/context/<domain>-current.md`.

    Body: the index sections, each link replaced by title, applies_to,
    confidence, last_verified and the Observations block. Nothing else.
    If the ceiling would be exceeded, lowest-priority entries are dropped
    and the drop is recorded in the pack itself (no silent caps).
    """
    di = load_index(vault, domain)
    if di is None:
        raise PackError(f"no domain index for `{domain}`")
    dt = (now or datetime.now().astimezone())
    generated = dt.isoformat(timespec="seconds")
    valid_until = (dt + timedelta(days=config.PACK_VALID_DAYS)).isoformat(timespec="seconds")

    blocks: list[tuple[str, str, str]] = []  # (section, ref, text)
    for sec in _PRIORITY:
        for entry in di.sections.get(sec, []):
            block = _note_block(vault, entry.ref)
            if block is not None:
                blocks.append((sec, entry.ref, block))

    meta = {
        "type": "context-pack",
        "domain": domain,
        "generated_at": generated,
        "valid_until": valid_until,
        "source_commit": gitutil.head_commit(vault) or "uncommitted",
        "source_index": vault.rel(di.path),
        "token_estimate": 0,
        "status": "current",
    }

    def render(selected: list[tuple[str, str, str]], dropped: list[str]) -> str:
        lines = [f"# Context pack: {di.title or domain}"]
        for sec in _PRIORITY:
            sec_blocks = [b for s, _, b in selected if s == sec]
            lines.append("")
            lines.append(f"## {sec}")
            lines.extend(sec_blocks if sec_blocks else [])
        if dropped:
            lines.append("")
            lines.append("## Omitted for budget")
            lines.extend(f"- [[{r}]]" for r in dropped)
        return "\n".join(lines)

    dropped: list[str] = []
    selected = list(blocks)
    while True:
        body = render(selected, dropped)
        meta["token_estimate"] = tokens.estimate(frontmatter.compose(meta, body))
        if meta["token_estimate"] <= config.TOKEN_BUDGET_PACK or not selected:
            break
        sec, ref, _ = selected.pop()  # drop the lowest-priority entry
        dropped.append(ref)

    out = vault.path(config.CONTEXT_PACKS) / f"{domain}-current.md"
    fsutil.curator_write(vault, out, frontmatter.compose(meta, render(selected, dropped)))
    return out


def compile_all(vault: Vault, now: datetime | None = None) -> list[Path]:
    out = []
    base = vault.path(config.INDEX_DIR)
    if not base.is_dir():
        return out
    for p in sorted(base.glob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append(compile_pack(vault, p.stem, now))
    return out


def freshness(meta: dict, now: datetime | None = None) -> str:
    """Consumer rule (domain-index.md): current | stale | not-authoritative.
    Unparseable metadata is treated as not-authoritative — fail safe."""
    dt = now or datetime.now().astimezone()
    try:
        gen = datetime.fromisoformat(str(meta["generated_at"]))
        until = datetime.fromisoformat(str(meta["valid_until"]))
    except (KeyError, ValueError):
        return "not-authoritative"
    if dt.tzinfo is None:
        dt = dt.astimezone()
    if gen.tzinfo is None or until.tzinfo is None:
        return "not-authoritative"
    if dt <= until:
        return "current"
    window = until - gen
    return "stale" if dt <= until + window else "not-authoritative"
