"""Confidence, decay and contradiction rules as pure deterministic functions
(curator.md §5, §3, §6). Confidence is DERIVED — no code path lets an agent
assert it (P7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class FeedbackState:
    served: int = 0
    held: int = 0
    failed: int = 0
    unclear: int = 0


DECAY_DAYS = {"tool-behaviour": 90, "pattern": 180, "workaround": 180}


def _days_between(earlier: str | None, later: date) -> int | None:
    if not earlier:
        return None
    try:
        d = datetime.strptime(earlier[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (later - d).days


def derive_confidence(
    fb: FeedbackState,
    last_verified: str | None,
    trust: str,
    status: str,
    today: date,
) -> str:
    """curator.md §5 verbatim:
    high   — held ≥ 3; failed = 0 or held/(held+failed) ≥ 0.9; last held ≤ 60d;
             trust first-party or mixed
    medium — held ≥ 1 and ratio ≥ 0.6; OR would-be-high but last held 60–120d
    low    — everything else, incl. failed > held, third-party, every candidate
    """
    if status == "candidate":
        return "low"
    if trust in ("third-party", "unknown"):
        return "low"
    if fb.failed > fb.held:
        return "low"

    total = fb.held + fb.failed
    ratio = (fb.held / total) if total else 0.0
    age = _days_between(last_verified, today)

    high_shape = fb.held >= 3 and (fb.failed == 0 or ratio >= 0.9) and trust in ("first-party", "mixed")
    if high_shape and age is not None and age <= 60:
        return "high"
    if high_shape and age is not None and 60 < age <= 120:
        return "medium"
    if fb.held >= 1 and total and ratio >= 0.6:
        return "medium"
    return "low"


def drop_one_level(confidence: str) -> str:
    """A same-version failure drops confidence one level immediately (§5)."""
    return {"high": "medium", "medium": "low"}.get(confidence, "low")


def decay_due(note_type: str, status: str, last_verified: str | None, first_observed: str | None, today: date) -> bool:
    """§3 decay: tool-behaviour 90 days without a held, pattern/workaround
    180. Failures and references never auto-stale; only validated notes decay."""
    if status != "validated" or note_type not in DECAY_DAYS:
        return False
    anchor = last_verified or first_observed
    age = _days_between(anchor, today)
    return age is not None and age > DECAY_DAYS[note_type]


def never_exercised_flag(fb: FeedbackState, first_observed: str | None, today: date) -> bool:
    """served > 0 but no outcome for 90 days → review question:
    still true, or never relevant? (§5)"""
    if fb.served > 0 and fb.held + fb.failed == 0:
        age = _days_between(first_observed, today)
        return age is not None and age >= 90
    return False


def _norm_version(v) -> str:
    return str(v).strip().lower() if v is not None else ""


def same_version(applies_to_a: dict | None, applies_to_b: dict | None) -> bool:
    """Contradiction routing (§6): same tool set and same `from` window means
    the evidence collides on the SAME version; different windows suggest the
    behaviour changed between versions (supersession)."""
    a, b = applies_to_a or {}, applies_to_b or {}
    tools_a = {str(t).lower() for t in a.get("tools") or []}
    tools_b = {str(t).lower() for t in b.get("tools") or []}
    if tools_a and tools_b and tools_a.isdisjoint(tools_b):
        return False
    return _norm_version(a.get("from")) == _norm_version(b.get("from"))


def graduation_ready(fb: FeedbackState, status: str, has_procedure: bool) -> bool:
    """§3 Graduation: validated, held ≥ 5, failed = 0, repeatable procedure."""
    return status == "validated" and fb.held >= 5 and fb.failed == 0 and has_procedure
