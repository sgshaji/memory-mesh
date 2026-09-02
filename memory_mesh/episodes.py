"""Episodes: append-only records of sessions (spec: episode.md).

Deterministic scaffolding is separate from summarisation (mandate §G): hooks
write a valid `status: raw` stub with *Knowledge retrieved* pre-filled; an
agent (or human) fills the body while context is warm; `finish` validates and
flips raw → summarised. Nothing here fakes a summary.

Retrieved vs used (mandate clarification 2): the stub knows what was
RETRIEVED. Only the summarisation step records what was USED and whether it
held/failed/unclear/not-applicable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, frontmatter, fsutil, redact
from .config import Vault
from .notes import Note, load_note, section

REQUIRED_SECTIONS = (
    "Goal",
    "What happened",
    "Decisions",
    "Problems",
    "Knowledge retrieved",
    "Knowledge used",
    "Candidate learnings",
)

_USED_RE = re.compile(
    r"^\s*-\s*\[\[([^\]]+)\]\]\s*(?:[—–-]{1,2}\s*)?(held|failed|unclear|not-applicable)?\s*(?:[—–-]{1,2}\s*(.*))?$"
)


class EpisodeError(Exception):
    pass


@dataclass
class KnowledgeUse:
    ref: str
    outcome: str
    reason: str = ""


@dataclass
class Episode:
    note: Note
    retrieved: list[str] = field(default_factory=list)
    used: list[KnowledgeUse] = field(default_factory=list)
    candidate_learnings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _bullets(text: str) -> list[str]:
    return [re.sub(r"^\s*-\s*", "", l).strip() for l in text.splitlines() if l.strip().startswith("-")]


def parse_episode(note: Note) -> Episode:
    ep = Episode(note)
    for line in section(note.body, "Knowledge retrieved").splitlines():
        m = re.search(r"\[\[([^\]]+)\]\]", line)
        if m:
            ep.retrieved.append(m.group(1).strip())
    for line in section(note.body, "Knowledge used").splitlines():
        m = _USED_RE.match(line)
        if m and m.group(1):
            outcome = m.group(2) or "unclear"
            ep.used.append(KnowledgeUse(m.group(1).strip(), outcome, (m.group(3) or "").strip()))
    ep.candidate_learnings = _bullets(section(note.body, "Candidate learnings"))
    ep.decisions = _bullets(section(note.body, "Decisions"))
    ep.problems = _bullets(section(note.body, "Problems"))
    return ep


def _now(now: datetime | None) -> datetime:
    dt = now or datetime.now().astimezone()
    return dt.astimezone() if dt.tzinfo is None else dt


def create_stub(
    vault: Vault,
    tool: str,
    slug: str,
    session_ref: str = "",
    retrieved: list[str] | None = None,
    domains: list[str] | None = None,
    project: str | None = None,
    duration_min: int | None = None,
    trust: str = "first-party",
    now: datetime | None = None,
) -> Path:
    """Deterministic SessionEnd scaffold: valid, `status: raw`, retrieved
    notes pre-filled. Content comes later (I-005)."""
    dt = _now(now)
    date = dt.strftime("%Y-%m-%d")
    filename = f"{date}-{fsutil.safe_slug(tool, 20)}-{fsutil.safe_slug(slug, 40)}.md"
    path = fsutil.unique_path(vault.path(config.EPISODES) / filename)

    clean_ref, findings = redact.redact(session_ref or "", vault)
    meta: dict = {
        "type": "episode",
        "tool": tool,
        "domains": domains or ["unclassified"],
        "captured": dt.isoformat(timespec="seconds"),
        "trust": trust,
        "sensitivity": "redacted" if findings else "checked",
        "status": "raw",
        "session_ref": clean_ref or "none",
    }
    if project:
        meta["project"] = project
    if duration_min is not None:
        meta["duration_min"] = duration_min

    retrieved_lines = "\n".join(f"- [[{r}]]" for r in (retrieved or [])) or ""
    body = "\n".join(
        [
            f"# Session: {slug}",
            "",
            "## Goal",
            "",
            "## What happened",
            "",
            "## Decisions",
            "",
            "## Problems",
            "",
            "## Knowledge retrieved",
            retrieved_lines,
            "",
            "## Knowledge used",
            "",
            "## Candidate learnings",
            "",
        ]
    )
    return fsutil.agent_write(vault, path, frontmatter.compose(meta, body))


def checkpoint(vault: Vault, path: Path, text: str, now: datetime | None = None) -> None:
    """PreCompact: append a checkpoint bullet so long sessions lose nothing.
    Only valid while the episode is still raw."""
    note = load_note(path, vault)
    if note.status != "raw":
        raise EpisodeError(f"cannot checkpoint a {note.status} episode")
    clean, _ = redact.redact(text, vault)
    stamp = _now(now).strftime("%H:%M")
    lines = note.body.splitlines()
    out, inserted, in_wh = [], False, False
    for line in lines:
        if line.startswith("## What happened"):
            in_wh = True
        elif in_wh and line.startswith("## "):
            while out and not out[-1].strip():
                out.pop()  # keep exactly one blank line before the next heading
            out.append(f"- [checkpoint {stamp}] {clean}")
            out.append("")
            inserted = True
            in_wh = False
        out.append(line)
    if not inserted:
        out.append(f"- [checkpoint {stamp}] {clean}")
    fsutil.agent_write(vault, path, frontmatter.compose(note.meta, "\n".join(out)))


def validate_summary(note: Note) -> list[str]:
    """What `finish` requires before flipping raw → summarised."""
    problems = []
    for sec in REQUIRED_SECTIONS:
        if not re.search(rf"^##\s+{re.escape(sec)}\s*$", note.body, re.M):
            problems.append(f"missing section `## {sec}`")
    if not section(note.body, "Goal").strip():
        problems.append("`## Goal` is empty")
    if not section(note.body, "What happened").strip():
        problems.append("`## What happened` is empty")
    ep = parse_episode(note)
    retrieved = {r.split("/")[-1] for r in ep.retrieved}
    for use in ep.used:
        if use.outcome not in ("held", "failed", "unclear", "not-applicable"):
            problems.append(f"invalid outcome `{use.outcome}` for [[{use.ref}]]")
        if retrieved and use.ref.split("/")[-1] not in retrieved:
            problems.append(
                f"[[{use.ref}]] appears under Knowledge used but not Knowledge retrieved — add it to both"
            )
    words = len(note.body.split())
    if words > config.EPISODE_WORD_BUDGET:
        problems.append(f"body is {words} words; target ≤ {config.EPISODE_WORD_BUDGET}")
    return problems


def finish(vault: Vault, path: Path, now: datetime | None = None) -> list[str]:
    """Validate the filled body and flip raw → summarised. Returns warnings.
    The agent/human wrote the content; this step only checks and flips."""
    note = load_note(path, vault)
    if note.status == "summarised":
        return []
    if note.status != "raw":
        raise EpisodeError(f"cannot finish a {note.status} episode")
    problems = validate_summary(note)
    hard = [p for p in problems if not p.startswith("body is")]
    if hard:
        raise EpisodeError("episode not ready: " + "; ".join(hard))
    clean_body, findings = redact.redact(note.body, vault)
    meta = dict(note.meta)
    meta["status"] = "summarised"
    if findings:
        meta["sensitivity"] = "redacted"
    fsutil.agent_write(vault, path, frontmatter.compose(meta, clean_body))
    return [p for p in problems if p.startswith("body is")]


def mark_mined(vault: Vault, path: Path, mined_refs: list[str]) -> None:
    """Curator-only transition summarised → mined. The single metadata change
    the curator may make to an episode (episode.md rule 5)."""
    note = load_note(path, vault)
    if note.status != "summarised":
        raise EpisodeError(f"cannot mine a {note.status} episode")
    meta = dict(note.meta)
    meta["status"] = "mined"
    if mined_refs:
        meta["mined"] = mined_refs
    fsutil.curator_write(vault, path, frontmatter.compose(meta, note.body))


def redact_episode(vault: Vault, path: Path) -> list[redact.Finding]:
    """The one exception to append-only: redaction of an already-mined
    episode (issues.md I-012)."""
    note = load_note(path, vault)
    clean, findings = redact.redact(note.body, vault)
    if findings:
        meta = dict(note.meta)
        meta["sensitivity"] = "redacted"
        fsutil.curator_write(vault, path, frontmatter.compose(meta, clean))
    return findings
