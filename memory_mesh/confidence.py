"""Confidence, decay and contradiction rules as pure deterministic functions
(curator.md §5, §3, §6). Confidence is DERIVED — no code path lets an agent
assert it (P7)."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .applicability import ApplicabilityResult, match_applicability
from .config import VaultError
from .feedback_config import FeedbackPolicy
from .outcome_types import OutcomeEvent, parse_timestamp


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


ConfidenceLevel = Literal["low", "medium", "high"]
EvidenceBucket = Literal["held", "failed", "unclear"]
_FAILURE_WEIGHTS = {
    "behaviour_changed": 1.0,
    "unknown": 0.5,
    "insufficient_information": 0.25,
    "misapplied": 0.1,
    "context_mismatch": 0.1,
}
_OUTCOME_BUCKETS: dict[str, EvidenceBucket | None] = {
    "held": "held", "succeeded": "held", "failed": "failed",
    "unclear": "unclear", "partial": "unclear", "not-applicable": None,
}


@dataclass(frozen=True)
class EvidenceContribution:
    """A preserved report plus its inspectable, possibly excluded contribution.

    ``included`` means this report contributes weighted evidence after the
    session cap. ``future_excluded`` separately identifies clock quarantine;
    a capped or numerically decayed report need not be a future report.
    """

    event: OutcomeEvent
    applicability: ApplicabilityResult
    age_days: float
    time_weight: float
    context_weight: float
    reason_weight: float
    bucket: EvidenceBucket | None
    weight: float
    included: bool
    reasons: tuple[str, ...]
    future_excluded: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "event": self.event.as_dict(),
            "applicability": self.applicability.as_dict(),
            "age_days": self.age_days,
            "time_weight": self.time_weight,
            "context_weight": self.context_weight,
            "reason_weight": self.reason_weight,
            "bucket": self.bucket,
            "weight": self.weight,
            "included": self.included,
            "reasons": list(self.reasons),
            "future_excluded": self.future_excluded,
        }


@dataclass(frozen=True)
class EvidenceEvaluation:
    """Derived reported-evidence health, never admission or execution authority.

    ``counts`` retains raw outcomes of unique event IDs, including excluded
    reports. ``effective_evidence`` is weighted held + failed; uncertainty is
    shown separately, neither success nor a negative vote. ``last_verified``
    is the compatibility name for the ISO date of the latest matched reported
    held/succeeded, not a verified runtime attestation. Full timestamps remain
    in ``contributions``. Review and confidence are independent outputs.
    ``recent_failed_sessions`` supplies an attention-only quorum for consumers
    such as skill health, not another confidence or verification score.
    """

    confidence: ConfidenceLevel
    weighted_held: float
    weighted_failed: float
    weighted_unclear: float
    effective_evidence: float
    recent_behaviour_changes: int
    needs_review: bool
    reasons: tuple[str, ...]
    last_verified: str | None
    counts: Mapping[str, int]
    event_ids: tuple[str, ...]
    contributions: tuple[EvidenceContribution, ...]
    recent_behaviour_change_sessions: tuple[str, ...]
    recent_failed_sessions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "weighted_held": self.weighted_held,
            "weighted_failed": self.weighted_failed,
            "weighted_unclear": self.weighted_unclear,
            "effective_evidence": self.effective_evidence,
            "recent_behaviour_changes": self.recent_behaviour_changes,
            "needs_review": self.needs_review,
            "reasons": list(self.reasons),
            "last_verified": self.last_verified,
            "counts": dict(self.counts),
            "event_ids": list(self.event_ids),
            "contributions": [item.as_dict() for item in self.contributions],
            "recent_behaviour_change_sessions": list(self.recent_behaviour_change_sessions),
            "recent_failed_sessions": list(self.recent_failed_sessions),
        }


def _evaluation_time(now: datetime | date | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.utcoffset() is None:
            raise VaultError("evidence evaluation now requires a timezone")
        try:
            return now.astimezone(timezone.utc)
        except (OverflowError, ValueError) as exc:
            raise VaultError("evidence evaluation now is outside the supported UTC range") from exc
    if isinstance(now, date):
        return datetime.combine(now, time(), tzinfo=timezone.utc)
    raise VaultError("evidence evaluation now must be an aware datetime or a date")


def _validate_policy(policy: FeedbackPolicy) -> None:
    if not isinstance(policy, FeedbackPolicy):
        raise VaultError("evidence policy must be a FeedbackPolicy")
    for key, minimum, maximum, integer in (
        ("half_life_days", 1, 36500, False),
        ("recent_days", 1, 36500, True),
        ("behaviour_change_failures", 1, 36500, True),
        ("unknown_context_weight", 0, 1, False),
        ("out_of_context_weight", 0, 1, False),
        ("future_tolerance_seconds", 0, 3600, True),
    ):
        value = getattr(policy, key)
        valid_type = type(value) is int if integer else type(value) in (int, float)
        if not valid_type or not minimum <= value <= maximum or not math.isfinite(value):
            raise VaultError(f"evidence policy {key} must be a finite {'integer' if integer else 'number'} between {minimum} and {maximum}")


def evaluate_evidence(
    events: Iterable[OutcomeEvent],
    applies_to: object = None,
    *,
    now: datetime | date | None = None,
    policy: FeedbackPolicy | None = None,
    prior_confidence: str | None = None,
) -> EvidenceEvaluation:
    """Evaluate one knowledge/skill subject without writes or model reasoning.

    Each contribution is ``2**(-age_days / half_life_days) * context * reason``.
    Context multipliers are match=1, unknown=policy.unknown_context_weight
    (default .5), mismatch=policy.out_of_context_weight (default .1). A success
    outside its declared context contributes zero and cannot verify a claim.
    Failure multipliers are behaviour_changed=1, unknown=.5,
    insufficient_information=.25, misapplied=.1, context_mismatch=.1.
    ``succeeded`` is reported held; ``partial`` is unclear, never half-success.
    Not-applicable contributes nothing. None of these reports is an execution
    receipt, trust assertion or permission to admit/promote canonical content.

    Unique IDs preserve history; identical duplicates count once and conflicting
    IDs raise VaultError. Only the strongest contribution per session and bucket
    counts, so repeated reports/projections within one session are not
    independent evidence. Ties select the latest timestamp, then event ID.
    All raw unique counts, original timestamps and excluded reports remain
    inspectable. Mixed subjects and recall/routing outcomes are rejected.

    Let H/F/U be the resulting weighted held/failed/unclear totals. Effective
    evidence is H+F; U is neutral. High requires H>=3, H/(H+F)>=.9 and support
    from at least three matched sessions. Medium requires H>=.5 and ratio>=.6;
    otherwise low. Thus one supported report remains medium for one half-life;
    unknown-context evidence alone cannot yield high. Prior confidence is only
    an explanation/comparison, never a synthetic vote or a per-run decrement.
    Re-evaluation cannot compound a previous projection.

    Independently, >=policy.behaviour_change_failures (default 2) distinct
    sessions with matched behaviour_changed failures in the inclusive
    policy.recent_days window (default 30) recommend review, regardless of old
    successes. A single failure does not trigger this review by default.
    ``recent_failed_sessions`` also includes matched reported failures with
    unknown/insufficient_information reasons, but excludes misapplied and
    context_mismatch. It uses the same recent window and clock policy, counts
    each session once before the weight cap, and does not itself alter
    confidence or needs_review. Consumers may compare its length against a
    separate attention threshold without reimplementing time/version math.
    Legacy calendar applicability is matched at each historical event's time,
    preserving evidence that matched then even if today's window has expired.
    Explicit version constraints still require that event's observed version.
    Future timestamps within policy.future_tolerance_seconds (default 300)
    clamp to age zero and applicability/verification time <=now; more distant future reports
    have zero weight, cannot trigger behaviour-change evidence, and recommend
    clock/evidence review. Invalid or timezone-naive timestamps raise VaultError.
    """
    current = _evaluation_time(now)
    policy = FeedbackPolicy() if policy is None else policy
    _validate_policy(policy)
    if prior_confidence is not None and prior_confidence not in ("low", "medium", "high"):
        raise VaultError("prior_confidence must be low, medium, high or None")
    unique: dict[str, OutcomeEvent] = {}
    for event in events:
        if not isinstance(event, OutcomeEvent):
            raise VaultError("evidence must contain OutcomeEvent values")
        previous = unique.get(event.event_id)
        if previous is not None and previous.as_dict() != event.as_dict():
            raise VaultError(f"conflicting duplicate outcome event_id: {event.event_id}")
        unique[event.event_id] = event
    if any(event.subject_type not in ("knowledge", "skill") for event in unique.values()):
        raise VaultError("confidence accepts only knowledge or skill outcomes")
    if len({(event.subject_type, event.subject_id) for event in unique.values()}) > 1:
        raise VaultError("confidence events must refer to one subject")
    ordered = sorted(
        ((parse_timestamp(event.timestamp), event) for event in unique.values()),
        key=lambda item: (item[0], item[1].event_id),
    )
    counts = dict.fromkeys(_OUTCOME_BUCKETS, 0)
    context_counts = dict.fromkeys(("match", "mismatch", "unknown"), 0)
    contributions: list[EvidenceContribution] = []
    changed_sessions: set[str] = set()
    failed_sessions: set[str] = set()
    last_held: datetime | None = None
    future_excluded = future_clamped = 0
    for timestamp, event in ordered:
        counts[event.outcome] += 1
        lag_seconds = (current - timestamp).total_seconds()
        excluded = lag_seconds < -policy.future_tolerance_seconds
        age_days = max(lag_seconds, 0.0) / 86400
        time_weight = 0.0 if excluded else 2.0 ** (-age_days / policy.half_life_days)
        applicability = match_applicability(applies_to, event.context, now=min(timestamp, current))
        context_counts[applicability.state] += 1
        context_weight = {
            "match": 1.0,
            "unknown": policy.unknown_context_weight,
            "mismatch": policy.out_of_context_weight,
        }[applicability.state]
        bucket = _OUTCOME_BUCKETS[event.outcome]
        reason_weight = _FAILURE_WEIGHTS[event.reason or "unknown"] if bucket == "failed" else 1.0
        reasons = []
        if excluded:
            future_excluded += 1
            reasons.append("future timestamp exceeds clock tolerance; excluded from evidence and verification")
        elif lag_seconds < 0:
            future_clamped += 1
            reasons.append("future timestamp within clock tolerance; age and verification time clamped to now")
        if bucket == "held" and applicability.state == "mismatch":
            context_weight = 0.0
            reasons.append("out-of-context success cannot support or verify this claim")
        if bucket is None:
            reason_weight = 0.0
            reasons.append("not-applicable is neither positive nor negative evidence")
        if bucket == "failed":
            reasons.append(f"failure reason {event.reason or 'unknown'} multiplier={reason_weight:g}")
        if event.outcome == "partial":
            reasons.append("reported partial skill outcome is unclear, not successful execution")
        weight = time_weight * context_weight * reason_weight
        contributions.append(EvidenceContribution(
            event, applicability, age_days, time_weight, context_weight,
            reason_weight, bucket, weight, weight > 0, tuple(reasons),
            future_excluded=excluded,
        ))
        if not excluded and applicability.state == "match":
            if bucket == "held":
                verified = min(timestamp, current)
                last_held = verified if last_held is None else max(last_held, verified)
            if bucket == "failed" and age_days <= policy.recent_days:
                if event.reason == "behaviour_changed":
                    changed_sessions.add(event.session_id)
                if event.reason not in ("misapplied", "context_mismatch"):
                    failed_sessions.add(event.session_id)
    best: dict[tuple[str, EvidenceBucket], int] = {}
    for index, contribution in enumerate(contributions):
        if contribution.weight <= 0 or contribution.bucket is None:
            continue
        key = (contribution.event.session_id, contribution.bucket)
        previous_index = best.get(key)
        if previous_index is None or contribution.weight >= contributions[previous_index].weight:
            best[key] = index
    selected = set(best.values())
    capped = 0
    for index, contribution in enumerate(contributions):
        if contribution.weight > 0 and index not in selected:
            capped += 1
            contributions[index] = replace(
                contribution, weight=0.0, included=False,
                reasons=contribution.reasons + (
                    "same session/bucket already represented by its strongest report; not independent evidence",
                ),
            )
    held, failed, unclear = (
        math.fsum(item.weight for item in contributions if item.bucket == bucket)
        for bucket in ("held", "failed", "unclear")
    )
    effective = held + failed
    ratio = held / effective if effective else 0.0
    matched_support_sessions = {
        item.event.session_id for item in contributions
        if item.bucket == "held" and item.included and item.applicability.state == "match"
    }
    confidence: ConfidenceLevel = "low"
    if held >= 3 and ratio >= 0.9 and len(matched_support_sessions) >= 3:
        confidence = "high"
    elif held >= 0.5 and ratio >= 0.6:
        confidence = "medium"
    needs_review = len(changed_sessions) >= policy.behaviour_change_failures or future_excluded > 0
    reasons = [
        "self-reported outcomes only; not verified execution evidence or authority for admission",
        f"decay=2**(-age_days/{policy.half_life_days:g}); context multipliers match=1, unknown={policy.unknown_context_weight:g}, mismatch={policy.out_of_context_weight:g} (mismatched successes=0)",
        f"weighted held={held:.6g}, failed={failed:.6g}, unclear={unclear:.6g}; effective evidence={effective:.6g}; held ratio={ratio:.6g}",
        f"context reports: match={context_counts['match']}, mismatch={context_counts['mismatch']}, unknown={context_counts['unknown']}",
        f"confidence={confidence}: high needs held>=3, ratio>=0.9 and >=3 matched sessions; medium needs held>=0.5 and ratio>=0.6",
        f"recent matched behaviour_changed failures: {len(changed_sessions)} independent sessions within {policy.recent_days} days; review threshold={policy.behaviour_change_failures}",
        f"recent eligible failed sessions={len(failed_sessions)}: matched reports excluding misapplied/context_mismatch; attention-only, not an additional confidence vote",
    ]
    if not effective:
        reasons.append("no effective positive or negative evidence; confidence remains low")
    if capped:
        reasons.append(f"{capped} same-session/bucket reports retained but not counted as independent evidence")
    if future_excluded:
        reasons.append(f"{future_excluded} future reports excluded; review clock/evidence timestamps")
    if future_clamped:
        reasons.append(f"{future_clamped} future reports clamped within {policy.future_tolerance_seconds}s clock tolerance")
    if prior_confidence is not None:
        reasons.append(f"previous confidence={prior_confidence} is comparison-only, not an additional vote or repeated decrement")
    return EvidenceEvaluation(
        confidence=confidence,
        weighted_held=held, weighted_failed=failed, weighted_unclear=unclear,
        effective_evidence=effective, recent_behaviour_changes=len(changed_sessions),
        needs_review=needs_review, reasons=tuple(reasons),
        last_verified=last_held.date().isoformat() if last_held is not None else None,
        counts=MappingProxyType(counts),
        event_ids=tuple(event.event_id for _, event in ordered),
        contributions=tuple(contributions),
        recent_behaviour_change_sessions=tuple(sorted(changed_sessions)),
        recent_failed_sessions=tuple(sorted(failed_sessions)),
    )
