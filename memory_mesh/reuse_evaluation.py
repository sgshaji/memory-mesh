"""Pure, observational summaries of caller-supplied offline pilot runs.

Accept JSON-native lists/dicts/scalars only. Identifiers match
``[A-Za-z0-9][A-Za-z0-9_.-]{0,99}``; declared currencies must agree globally.
Supplied cost provenance must be nonblank text, but is not verified or echoed.
Numbers and their aggregates must fit finite, nonnegative floats (differences
may be negative). No task, billing lookup, or benchmark is executed here.

Reports always contain ``arms`` (native/v1/v2), ``comparisons`` (native_vs_v2
and v1_vs_v2), ``samples``, and warnings. Coverage gives measured_count,
total_count, and fraction; empty denominators and unknown measurements are
null, not zero. Spending includes unsuccessful runs and both cost components.
Partial component subtotals are explicitly labeled; total spending and cost
per accepted task require complete billing, and the latter requires successes.
Human review seconds are separate from currency.

Arm medians describe measured runs with coverage. Comparative costs and times
require measurements on *every* matched case/trial pair, never independently
filtered sides. Differences are candidate minus baseline; time differences
are medians of within-pair differences, not differences of marginal medians.
Sample counts distinguish repeated trials, cases, and declared families;
comparison samples count one row per pair. Labels do not prove independence
or transfer, and aggregation supports neither causality nor lesson credit.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal, TypedDict

from .config import VaultError


class EvaluationError(VaultError):
    """Invalid or unrepresentable offline evaluation data."""


_ARMS = ("native", "v1", "v2")
_IDENTIFIER_FIELDS = ("case_id", "family", "trial_id")
_NUMBER_FIELDS = ("active_ms", "model_cost", "memory_cost", "review_seconds")
_BASE_FIELDS = frozenset((
    *_IDENTIFIER_FIELDS, "arm", "accepted", *_NUMBER_FIELDS,
    "currency", "cost_source",
))
_ALLOWED_FIELDS = _BASE_FIELDS | {"critical_failure"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_CURRENCY = re.compile(r"[A-Z]{3}")
_WARNINGS = (
    "Observational aggregation does not establish causality or a controlled experiment.",
    "Caller-reported outcomes, measurements, and cost provenance are not independently verified.",
    "Null measurements mean unknown, not zero; coverage must accompany every measured statistic.",
    "Spending includes all submitted attempts, including failed and no-match runs.",
    "Acceptance rates weight runs, including repeated trials; case and family labels "
    "do not establish independent samples or broad transfer.",
    "Each pairwise comparison has its own matched cohort; do not compare deltas across cohorts.",
    "Aggregate data cannot assign individual lesson credit or support 10x claims.",
    "Human review time is separate from monetary spending and is not converted to currency.",
)


class _Run(TypedDict):
    case_id: str
    family: str
    trial_id: str
    arm: str
    accepted: bool
    active_ms: float | None
    model_cost: float | None
    memory_cost: float | None
    review_seconds: float | None
    currency: str | None
    critical_failure: bool | None


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise EvaluationError("Identifiers must be safe ASCII identifiers of 1 to 100 characters.")
    return value


def _number(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise EvaluationError("Measurements must be numbers or null; booleans are not numbers.")
    try:
        number = float(value)
    except OverflowError:
        raise EvaluationError("Measurements must fit the supported finite numeric range.") from None
    if not math.isfinite(number) or number < 0:
        raise EvaluationError("Measurements must be finite and nonnegative.")
    return number


def _validate(data: object) -> list[_Run]:
    if type(data) is not list:
        raise EvaluationError("Evaluation input must be a list of run dictionaries.")
    if len(data) > 10000:
        raise EvaluationError("Evaluation input must contain at most 10000 runs.")

    runs: list[_Run] = []
    seen: set[tuple[str, str, str]] = set()
    families: dict[str, str] = {}
    currencies: set[str] = set()
    for raw in data:
        if type(raw) is not dict:
            raise EvaluationError("Each evaluation run must be a dictionary.")
        if (
            any(type(key) is not str for key in raw)
            or not _BASE_FIELDS <= raw.keys()
            or raw.keys() - _ALLOWED_FIELDS
        ):
            raise EvaluationError("Each run requires every base field and no unexpected fields.")
        identifiers = {field: _identifier(raw[field]) for field in _IDENTIFIER_FIELDS}
        arm = raw["arm"]
        if type(arm) is not str or arm not in _ARMS:
            raise EvaluationError("Run arm must be native, v1, or v2.")
        accepted = raw["accepted"]
        if type(accepted) is not bool:
            raise EvaluationError("Run acceptance must be an explicit boolean.")
        critical_failure = raw.get("critical_failure")
        if critical_failure is not None and type(critical_failure) is not bool:
            raise EvaluationError("Critical failure must be a boolean or null.")
        numbers = {field: _number(raw[field]) for field in _NUMBER_FIELDS}

        currency = raw["currency"]
        if currency is not None:
            if type(currency) is not str or _CURRENCY.fullmatch(currency) is None:
                raise EvaluationError("Currency must be three uppercase ASCII letters or null.")
            currencies.add(currency)
            if len(currencies) > 1:
                raise EvaluationError("All declared currencies must agree; conversion is not supported.")
        source = raw["cost_source"]
        if source is not None and (type(source) is not str or not source.strip()):
            raise EvaluationError("Cost provenance must be a nonblank string or null.")
        if (
            numbers["model_cost"] is not None or numbers["memory_cost"] is not None
        ) and (currency is None or source is None):
            raise EvaluationError("Every measured monetary component requires currency and cost provenance.")

        case_id = identifiers["case_id"]
        trial_id = identifiers["trial_id"]
        family = identifiers["family"]
        key = (case_id, trial_id, arm)
        if key in seen:
            raise EvaluationError("Duplicate case/trial/arm runs are not allowed.")
        seen.add(key)
        if families.setdefault(case_id, family) != family:
            raise EvaluationError("A case must belong to exactly one family.")
        runs.append({
            "case_id": case_id,
            "family": family,
            "trial_id": trial_id,
            "arm": arm,
            "accepted": accepted,
            "active_ms": numbers["active_ms"],
            "model_cost": numbers["model_cost"],
            "memory_cost": numbers["memory_cost"],
            "review_seconds": numbers["review_seconds"],
            "currency": currency,
            "critical_failure": critical_failure,
        })
    return runs


def _coverage(measured: int, total: int) -> dict[str, Any]:
    return {
        "measured_count": measured,
        "total_count": total,
        "fraction": measured / total if total else None,
    }


def _sum(values: list[float]) -> float | None:
    if not values:
        return None
    try:
        total = math.fsum(values)
    except OverflowError:
        raise EvaluationError("Numeric aggregates exceed the supported finite range.") from None
    if not math.isfinite(total):
        raise EvaluationError("Numeric aggregates exceed the supported finite range.")
    return total


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    left, right = ordered[middle - 1:middle + 1]
    total = left + right
    # Avoid overflowing an otherwise representable midpoint.
    return total / 2 if math.isfinite(total) else left / 2 + right / 2


def _currency(runs: list[_Run]) -> str | None:
    return next((run["currency"] for run in runs if run["currency"] is not None), None)


def _samples(runs: list[_Run]) -> dict[str, Any]:
    cases = {run["case_id"] for run in runs}
    trials = {(run["case_id"], run["trial_id"]) for run in runs}
    families: dict[str, list[_Run]] = {}
    for run in runs:
        families.setdefault(run["family"], []).append(run)
    return {
        "case_count": len(cases),
        "case_trial_count": len(trials),
        "repeated_trial_count": len(trials) - len(cases),
        "family_count": len(families),
        "families": {
            name: {
                "run_count": len(rows),
                "case_count": len({row["case_id"] for row in rows}),
                "case_trial_count": len({(row["case_id"], row["trial_id"]) for row in rows}),
            }
            for name, rows in sorted(families.items())
        },
    }


def _has_billing(run: _Run) -> bool:
    return run["model_cost"] is not None and run["memory_cost"] is not None


def _per_accepted(total: float | None, accepted: int) -> float | None:
    return total / accepted if total is not None and accepted else None


def _cost_summary(runs: list[_Run], accepted: int) -> dict[str, Any]:
    model = [value for run in runs if (value := run["model_cost"]) is not None]
    memory = [value for run in runs if (value := run["memory_cost"]) is not None]
    measured = sum(_has_billing(run) for run in runs)
    complete = bool(runs) and measured == len(runs)
    subtotal = _sum(model + memory)
    total = subtotal if complete else None
    return {
        "currency": _currency(runs),
        "complete_run_coverage": _coverage(measured, len(runs)),
        "model_cost_coverage": _coverage(len(model), len(runs)),
        "memory_cost_coverage": _coverage(len(memory), len(runs)),
        "measured_component_subtotal": subtotal,
        "measured_component_subtotal_is_partial": not complete,
        "total_spending": total,
        "cost_per_accepted_task": _per_accepted(total, accepted),
    }


def _arm_summary(runs: list[_Run]) -> dict[str, Any]:
    count = len(runs)
    accepted = sum(run["accepted"] for run in runs)
    critical = [value for run in runs if (value := run["critical_failure"]) is not None]
    active = [value for run in runs if (value := run["active_ms"]) is not None]
    review = [value for run in runs if (value := run["review_seconds"]) is not None]
    review_subtotal = _sum(review)
    cost = _cost_summary(runs, accepted)
    warnings = []
    if not runs:
        warnings.append("No runs were supplied for this arm; measurements and rates are unknown.")
    if cost["complete_run_coverage"]["measured_count"] < count:
        warnings.append("Incomplete billing: total spending and cost per accepted task are unknown.")
    if count and not accepted:
        warnings.append("No accepted tasks: cost per accepted task is undefined.")
    if len(critical) < count:
        warnings.append("Critical-failure checks are incomplete; a measured zero does not mean no failures.")
    if len(active) < count:
        warnings.append("Active-time median describes measured runs only, not all runs.")
    if len(review) < count:
        warnings.append("Review-time statistics describe measured runs only; total review time is unknown.")
    return {
        "run_count": count,
        "accepted_count": accepted,
        "accepted_rate": accepted / count if count else None,
        "critical_failures": {
            "measured_failure_count": sum(critical) if critical else None,
            "coverage": _coverage(len(critical), count),
        },
        "cost": cost,
        "active_ms": {"median": _median(active), "coverage": _coverage(len(active), count)},
        "review_seconds": {
            "median": _median(review),
            "measured_subtotal": review_subtotal,
            "total": review_subtotal if count and len(review) == count else None,
            "coverage": _coverage(len(review), count),
        },
        "samples": _samples(runs),
        "warnings": warnings,
    }


def _paired_time(
    baseline: list[_Run],
    candidate: list[_Run],
    field: Literal["active_ms", "review_seconds"],
) -> dict[str, Any]:
    measured = [
        (left_value, right_value)
        for left, right in zip(baseline, candidate)
        if (left_value := left[field]) is not None
        and (right_value := right[field]) is not None
    ]
    complete = bool(baseline) and len(measured) == len(baseline)
    return {
        "complete_pair_coverage": _coverage(len(measured), len(baseline)),
        "baseline_median": _median([left for left, _ in measured]) if complete else None,
        "candidate_median": _median([right for _, right in measured]) if complete else None,
        "median_candidate_minus_baseline": (
            _median([right - left for left, right in measured]) if complete else None
        ),
    }


def _comparison(
    baseline_arm: str, candidate_arm: str, arms: dict[str, list[_Run]],
) -> dict[str, Any]:
    baseline_by_key = {
        (run["case_id"], run["trial_id"]): run for run in arms[baseline_arm]
    }
    candidate_by_key = {
        (run["case_id"], run["trial_id"]): run for run in arms[candidate_arm]
    }
    keys = sorted(baseline_by_key.keys() & candidate_by_key.keys())
    baseline = [baseline_by_key[key] for key in keys]
    candidate = [candidate_by_key[key] for key in keys]
    count = len(keys)
    unmatched = {
        "baseline": len(baseline_by_key) - count,
        "candidate": len(candidate_by_key) - count,
    }
    baseline_accepted = sum(run["accepted"] for run in baseline)
    candidate_accepted = sum(run["accepted"] for run in candidate)
    both = sum(left["accepted"] and right["accepted"] for left, right in zip(baseline, candidate))
    complete_billing = sum(
        _has_billing(left) and _has_billing(right) for left, right in zip(baseline, candidate)
    )
    baseline_total = candidate_total = None
    if count and complete_billing == count:
        baseline_total = _cost_summary(baseline, baseline_accepted)["total_spending"]
        candidate_total = _cost_summary(candidate, candidate_accepted)["total_spending"]
    baseline_per_accepted = _per_accepted(baseline_total, baseline_accepted)
    candidate_per_accepted = _per_accepted(candidate_total, candidate_accepted)
    active = _paired_time(baseline, candidate, "active_ms")
    review = _paired_time(baseline, candidate, "review_seconds")
    warnings = []
    if not count:
        warnings.append("No matching case/trial pairs; comparison metrics are unknown.")
    if any(unmatched.values()):
        warnings.append("Unmatched runs are excluded from this comparison, not from arm spending.")
    if complete_billing < count:
        warnings.append("Incomplete paired billing; comparative monetary metrics are unknown.")
    if count and (not baseline_accepted or not candidate_accepted):
        warnings.append("A matched arm has no accepted tasks; cost-per-accepted differences are undefined.")
    if active["complete_pair_coverage"]["measured_count"] < count:
        warnings.append("Incomplete paired active time; no active-time comparison is reported.")
    if review["complete_pair_coverage"]["measured_count"] < count:
        warnings.append("Incomplete paired review time; no review-time comparison is reported.")
    return {
        "baseline_arm": baseline_arm,
        "candidate_arm": candidate_arm,
        "pair_count": count,
        "unmatched_counts": unmatched,
        "samples": _samples(baseline),
        "acceptance": {
            "both_accepted": both,
            "baseline_only": baseline_accepted - both,
            "candidate_only": candidate_accepted - both,
            "neither_accepted": count - baseline_accepted - candidate_accepted + both,
            "baseline_accepted_count": baseline_accepted,
            "candidate_accepted_count": candidate_accepted,
            "baseline_accepted_rate": baseline_accepted / count if count else None,
            "candidate_accepted_rate": candidate_accepted / count if count else None,
            "candidate_minus_baseline_rate": (
                (candidate_accepted - baseline_accepted) / count if count else None
            ),
        },
        "cost": {
            "currency": _currency(baseline + candidate),
            "complete_pair_coverage": _coverage(complete_billing, count),
            "baseline_total_spending": baseline_total,
            "candidate_total_spending": candidate_total,
            "baseline_cost_per_accepted_task": baseline_per_accepted,
            "candidate_cost_per_accepted_task": candidate_per_accepted,
            "candidate_minus_baseline_cost_per_accepted_task": (
                candidate_per_accepted - baseline_per_accepted
                if candidate_per_accepted is not None and baseline_per_accepted is not None
                else None
            ),
        },
        "active_ms": active,
        "review_seconds": review,
        "warnings": warnings,
    }


def evaluate_runs(data: object) -> dict[str, Any]:
    """Validate and summarize submitted runs without I/O or causal attribution.

    Raise EvaluationError with payload-free messages for invalid input or
    unrepresentable numeric aggregates. The input is never mutated.
    """
    runs = _validate(data)
    arms: dict[str, list[_Run]] = {arm: [] for arm in _ARMS}
    for run in runs:
        arms[run["arm"]].append(run)
    return {
        "schema_version": 1,
        "design": "observational",
        "causal_claims_supported": False,
        "run_count": len(runs),
        "currency": _currency(runs),
        "samples": _samples(runs),
        "arms": {arm: _arm_summary(arms[arm]) for arm in _ARMS},
        "comparisons": {
            f"{baseline}_vs_v2": _comparison(baseline, "v2", arms)
            for baseline in ("native", "v1")
        },
        "warnings": list(_WARNINGS),
    }
