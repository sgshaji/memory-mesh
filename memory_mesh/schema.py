"""Schema vocabulary and deterministic validation (spec: schema.md).

`memory lint` is built on this: pure filesystem checks, no model, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from . import config
from .config import Vault, VaultError
from .notes import Note

# type -> (folder, writer)
NOTE_TYPES: dict[str, tuple[str, str]] = {
    "candidate": ("00-inbox", "agent"),
    "gap": ("00-inbox", "agent"),
    "episode": ("episodes", "agent"),
    "outcome": (config.OUTCOME_EVENTS, "agent"),
    "recall-attempt": (config.RECALL_ATTEMPTS, "agent"),
    "episode-summary": ("episodes/_summaries", "curator"),
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
    if not isinstance(v, str) or not DATE_RE.fullmatch(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def _is_version_or_date(v: Any) -> bool:
    return isinstance(v, (int, float)) or (
        isinstance(v, str) and bool(DATE_RE.match(v) or MONTH_RE.match(v) or re.match(r"^v?\d[\w.-]*$", v))
    )


def domain_names(vault: Vault) -> list[str]:
    """Domain names declared in the router table."""
    from .router import load_domains  # local import to avoid a cycle

    return [d.name for d in load_domains(vault)]


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
    if (
        ntype is None and rel.startswith(config.SKILLS + "/")
        and note.path.name == "SKILL.md"
        and isinstance(note.meta.get("name"), str) and note.meta["name"].strip()
    ):
        ntype = "skill"
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
            allowed_extra = {"unclassified"} if ntype in ("episode", "candidate", "gap", "recall-attempt") else set()
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
    elif ntype == "gap":
        _validate_candidate(note, err, warn, in_unreviewed)
        if not isinstance(meta.get("need"), str) or not meta["need"].strip():
            err("gap candidate requires a nonempty `need`")
        for field_name in ("status", "confidence", "feedback", "last_verified"):
            if field_name in meta:
                err(f"gap candidates cannot carry factual knowledge field `{field_name}`")
    elif ntype == "skill":
        _validate_skill(note, err, warn)
    elif ntype == "outcome":
        from .outcomes import parse_event_note

        try:
            parse_event_note(note)
        except VaultError as exc:
            err(str(exc))
    elif ntype == "recall-attempt":
        from .routing_diagnostics import parse_attempt_note

        try:
            parse_attempt_note(note)
        except VaultError as exc:
            err(str(exc))
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
        if not isinstance(fb, dict) or not all(k in ("served", "held", "failed", "unclear") and type(v) is int and v >= 0 for k, v in fb.items()):
            err("`feedback` must be {served, held, failed, unclear} with nonnegative integer values")
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
    _validate_applicability(meta.get("applies_to"), err)
    if note.type != "reference" and not note.observations():
        warn("no `- [category] fact` observations in body")


def _validate_applicability(ap: Any, err) -> None:
    if ap is not None:
        if not isinstance(ap, dict):
            err("`applies_to` must be a mapping")
        else:
            if "tools" in ap and (
                not isinstance(ap["tools"], list)
                or any(not isinstance(tool, str) or not tool.strip() for tool in ap["tools"])
            ):
                err("`applies_to.tools` must be a list of nonempty tool names")
            for key in ("tool", "product", "version"):
                if key in ap and (not isinstance(ap[key], str) or not ap[key].strip()):
                    err(f"`applies_to.{key}` must be nonempty text (quote version constraints)")
            for k in ("from", "to"):
                if k in ap and ap[k] is not None and not _is_version_or_date(ap[k]):
                    err(f"`applies_to.{k}` must be a version or date, got {ap[k]!r}")


def _validate_skill(note: Note, err, warn) -> None:
    meta = note.meta
    dependencies = meta.get("depends_on", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(ref, str) or not ref.strip() for ref in dependencies
    ):
        err("`depends_on` must be a list of knowledge references")
    elif len(dependencies) != len(set(dependencies)):
        warn("skill repeats a knowledge dependency")
    _validate_applicability(meta.get("applies_to"), err)
    if meta.get("last_verified") is not None and not _is_date(meta["last_verified"]):
        err("skill `last_verified` must be ISO YYYY-MM-DD")
    if meta.get("confidence") is not None and meta["confidence"] not in CONFIDENCE:
        err("skill has an invalid confidence value")


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
    if cap is not None and not _is_timestamp(cap):
        err(f"`captured` must be an ISO timestamp with UTC offset, got {cap!r}")
    if meta.get("trust") not in (None, *TRUST):
        err(f"invalid trust `{meta.get('trust')}`")
    if meta.get("recall_quality") not in (None, "useful", "partial", "missed", "off-target"):
        err("invalid `recall_quality`")
    if meta.get("completeness") not in (None, "partial", "complete"):
        err("`completeness` must be partial or complete")
    if "outcome_events" in meta and (
        not isinstance(meta["outcome_events"], list)
        or any(not isinstance(ref, str) or not ref for ref in meta["outcome_events"])
    ):
        err("`outcome_events` must be a list of event IDs")
    if status in ("summarised", "mined"):
        from .notes import section

        meaningful = ("What happened", "Decisions", "Problems", "Candidate learnings", "Knowledge used", "Knowledge retrieved")
        if not any(
            section(note.body, name).strip().lower() not in ("", "(none)", "none", "-")
            for name in meaningful
        ) and not meta.get("recall_quality") and not meta.get("outcome_events"):
            err("summarised episode has no available observations or feedback")
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
    if meta.get("captured") is not None and not _is_timestamp(meta["captured"]):
        err("candidate `captured` must be an ISO timestamp with UTC offset")
    if meta.get("signal", "normal") not in ("high", "normal", "low"):
        err("candidate `signal` must be high, normal or low")
    if "source_episode" in meta and not isinstance(meta["source_episode"], str):
        err("candidate `source_episode` must be an episode reference")
    if in_unreviewed and meta.get("status") != "unreviewed":
        err("candidates parked under episodes/_unreviewed/ must carry status: unreviewed")
    if not in_unreviewed and meta.get("status") not in (None, "candidate"):
        err("inbox items are `status: candidate` (or omit status) until curated")
