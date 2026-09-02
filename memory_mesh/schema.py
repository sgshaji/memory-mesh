"""Schema vocabulary and deterministic validation (spec: schema.md).

`memory lint` is built on this: pure filesystem checks, no model, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import config
from .config import Vault
from .notes import Note

# type -> (folder, writer)
NOTE_TYPES: dict[str, tuple[str, str]] = {
    "candidate": ("00-inbox", "agent"),
    "episode": ("episodes", "agent"),
    "pattern": ("knowledge/patterns", "curator"),
    "tool-behaviour": ("knowledge/tools", "curator"),
    "workaround": ("knowledge/workarounds", "curator"),
    "failure": ("knowledge/failures", "curator"),
    "reference": ("knowledge/references", "curator"),
    "index": ("knowledge/_index", "curator"),
    "project": ("projects", "user"),
    "context-pack": ("outputs/context", "generated"),
    "skill": ("skills", "human-gated"),
}

KNOWLEDGE_TYPES = ("pattern", "tool-behaviour", "workaround", "failure", "reference")

STATUSES = ("candidate", "validated", "stale", "resolved", "superseded", "rejected")
STATUS_FLOW: dict[str, tuple[str, ...]] = {
    "candidate": ("validated", "rejected", "superseded", "stale"),
    "validated": ("stale", "superseded", "rejected", "resolved"),
    "stale": ("validated", "superseded", "rejected", "resolved"),
    "resolved": (),
    "superseded": (),
    "rejected": (),
}
EPISODE_STATUSES = ("raw", "summarised", "mined")
TRUST = ("first-party", "mixed", "third-party", "unknown")
OUTCOMES = ("held", "failed", "unclear", "not-applicable")
CONFIDENCE = ("high", "medium", "low")
RELATION_TYPES = (
    "derived_from", "supports", "contradicts", "supersedes",
    "mitigated_by", "implemented_as", "graduates_to", "observed_in", "relates_to",
)
SENSITIVITY = ("checked", "redacted")

# Fields only the curator may set/edit on knowledge notes (schema.md rules).
CURATOR_ONLY_FIELDS = ("status", "confidence", "last_verified", "feedback", "superseded_by")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?([+-]\d{2}:\d{2}|Z)$")


@dataclass
class Issue:
    path: str
    severity: str  # error | warning
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():7s} {self.path}: {self.message}"


def _is_date(v: Any) -> bool:
    return isinstance(v, str) and bool(DATE_RE.match(v))


def _is_version_or_date(v: Any) -> bool:
    return isinstance(v, (int, float)) or (
        isinstance(v, str) and bool(DATE_RE.match(v) or MONTH_RE.match(v) or re.match(r"^v?\d[\w.-]*$", v))
    )


def domain_names(vault: Vault) -> list[str]:
    """Domain names declared in the router table."""
    from .router import load_domains  # local import to avoid a cycle

    try:
        return [d.name for d in load_domains(vault)]
    except Exception:
        return []


def validate_note(note: Note, vault: Vault, domains: list[str] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    rel = note.rel

    def err(msg: str) -> None:
        issues.append(Issue(rel, "error", msg))

    def warn(msg: str) -> None:
        issues.append(Issue(rel, "warning", msg))

    if note.parse_error:
        err(f"malformed frontmatter: {note.parse_error}")
        return issues

    ntype = note.type
    if ntype is None:
        err("missing `type`")
        return issues
    if ntype == "meta" or rel.startswith("_meta/"):
        return issues
    if ntype not in NOTE_TYPES:
        err(f"unknown type `{ntype}`")
        return issues

    folder, _writer = NOTE_TYPES[ntype]
    in_unreviewed = rel.startswith(config.EPISODE_UNREVIEWED + "/")
    if not rel.startswith(folder + "/") and not (ntype == "candidate" and in_unreviewed):
        err(f"type `{ntype}` belongs under {folder}/, found at {rel}")

    if domains is None:
        domains = domain_names(vault)

    meta = note.meta

    # --- domain validation (episodes may carry `unclassified` as a signal) ---
    doms = meta.get("domains")
    if doms is not None:
        if not isinstance(doms, list):
            err("`domains` must be a list")
        else:
            allowed_extra = {"unclassified"} if ntype in ("episode", "candidate") else set()
            for d in doms:
                if d not in domains and d not in allowed_extra:
                    err(f"domain `{d}` not declared in {config.ROUTER}")
            if ntype in KNOWLEDGE_TYPES and not (1 <= len(doms) <= 3):
                err("`domains` must carry 1-3 values")

    # --- per-type checks ---
    if ntype in KNOWLEDGE_TYPES:
        _validate_knowledge(note, err, warn)
    elif ntype == "episode":
        _validate_episode(note, err, warn, in_unreviewed)
    elif ntype == "candidate":
        _validate_candidate(note, err, warn, in_unreviewed)
    elif ntype == "context-pack":
        for f in ("domain", "generated_at", "valid_until", "source_commit", "source_index", "token_estimate", "status"):
            if f not in meta:
                err(f"context-pack missing `{f}`")
    elif ntype == "index":
        if "domain" not in meta:
            err("index missing `domain`")

    return issues


def _validate_knowledge(note: Note, err, warn) -> None:
    meta = note.meta
    for f in ("title", "domains", "status", "trust"):
        if f not in meta:
            err(f"knowledge note missing `{f}`")
    status = meta.get("status")
    if status is not None and status not in STATUSES:
        err(f"invalid status `{status}`")
    trust = meta.get("trust")
    if trust is not None and trust not in TRUST:
        err(f"invalid trust `{trust}`")
    conf = meta.get("confidence")
    if conf is not None and conf not in CONFIDENCE:
        err(f"invalid confidence `{conf}`")
    for f in ("first_observed", "last_verified"):
        v = meta.get(f)
        if v is not None and not _is_date(v):
            err(f"`{f}` must be ISO YYYY-MM-DD, got {v!r}")
    fb = meta.get("feedback")
    if fb is not None:
        if not isinstance(fb, dict) or not all(k in ("served", "held", "failed", "unclear") and isinstance(v, int) for k, v in fb.items()):
            err("`feedback` must be {served, held, failed, unclear} with integer values")
    ev = meta.get("evidence")
    if ev is not None and not isinstance(ev, list):
        err("`evidence` must be a list of episode refs")
    elif isinstance(ev, list):
        for e in ev:
            if isinstance(e, str) and e.endswith(".md"):
                warn(f"evidence ref `{e}` should omit .md")
    if status == "validated" and not (isinstance(ev, list) and len(ev) >= 1):
        err("a validated note needs at least one evidence episode")
    if status == "superseded" and not meta.get("superseded_by"):
        err("superseded note missing `superseded_by`")
    ap = meta.get("applies_to")
    if ap is not None:
        if not isinstance(ap, dict):
            err("`applies_to` must be a mapping")
        else:
            if "tools" in ap and not isinstance(ap["tools"], list):
                err("`applies_to.tools` must be a list")
            for k in ("from", "to"):
                if k in ap and ap[k] is not None and not _is_version_or_date(ap[k]):
                    err(f"`applies_to.{k}` must be a version or date, got {ap[k]!r}")
    if note.type != "reference" and not note.observations():
        warn("no `- [category] fact` observations in body")


def _validate_episode(note: Note, err, warn, in_unreviewed: bool) -> None:
    meta = note.meta
    for f in ("tool", "captured", "trust", "sensitivity", "status"):
        if f not in meta:
            err(f"episode missing `{f}`")
    status = meta.get("status")
    ok_statuses = EPISODE_STATUSES + (("unreviewed",) if in_unreviewed else ())
    if status is not None and status not in ok_statuses:
        err(f"invalid episode status `{status}`")
    if meta.get("sensitivity") not in (None, *SENSITIVITY):
        err(f"`sensitivity` must be one of {SENSITIVITY}")
    cap = meta.get("captured")
    if cap is not None and not (isinstance(cap, str) and TIMESTAMP_RE.match(cap)):
        err(f"`captured` must be an ISO timestamp with UTC offset, got {cap!r}")
    if meta.get("trust") not in (None, *TRUST):
        err(f"invalid trust `{meta.get('trust')}`")
    if status in ("summarised", "mined"):
        from .episodes import REQUIRED_SECTIONS  # local import to avoid a cycle
        from .notes import section

        for sec in REQUIRED_SECTIONS:
            if section(note.body, sec) == "" and sec not in ("Decisions", "Problems", "Candidate learnings", "Knowledge used", "Knowledge retrieved"):
                err(f"summarised episode missing `## {sec}` content")
    if "processed" in meta:
        err("episodes never carry `processed:` (curator.md §2); lifecycle is raw→summarised→mined")
    words = len(note.body.split())
    if words > config.EPISODE_WORD_BUDGET:
        warn(f"episode body is {words} words (target ≤ {config.EPISODE_WORD_BUDGET})")


def _validate_candidate(note: Note, err, warn, in_unreviewed: bool) -> None:
    meta = note.meta
    for f in ("title", "source", "captured", "trust", "sensitivity"):
        if f not in meta:
            err(f"candidate missing `{f}`")
    if meta.get("trust") not in (None, *TRUST):
        err(f"invalid trust `{meta.get('trust')}`")
    if meta.get("sensitivity") not in (None, *SENSITIVITY):
        err(f"`sensitivity` must be one of {SENSITIVITY}")
    if in_unreviewed and meta.get("status") != "unreviewed":
        err("candidates parked under episodes/_unreviewed/ must carry status: unreviewed")
    if not in_unreviewed and meta.get("status") not in (None, "candidate"):
        err("inbox items are `status: candidate` (or omit status) until curated")
