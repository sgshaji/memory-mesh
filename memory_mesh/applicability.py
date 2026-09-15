"""Small, conservative applicability checks; not a generic semver resolver."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal, Mapping

ApplicabilityState = Literal["match", "mismatch", "unknown"]


@dataclass(frozen=True)
class ApplicabilityResult:
    state: ApplicabilityState
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class _Version:
    kind: str
    low: tuple[int, ...]
    high: tuple[int, ...]


@dataclass(frozen=True)
class _VersionRange:
    kind: str
    low: tuple[int, ...] | None
    low_inclusive: bool
    high: tuple[int, ...] | None
    high_inclusive: bool


_DATE_VERSION = re.compile(r"([0-9]{4})-([0-9]{2})(?:-([0-9]{2}))?")
_NUMERIC_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_CLAUSE = re.compile(r"(?:(>=|<=|==|>|<|=)\s*)?([^\s,]+)")
_FIELDS = frozenset(("product", "tool", "tools", "version", "from", "to"))


def _version(value: object, *, allow_prefix: bool = False) -> _Version:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError("version must be nonempty text of at most 128 characters")
    value = value.strip()
    match = _DATE_VERSION.fullmatch(value)
    if match:
        year, month = int(match[1]), int(match[2])
        day = int(match[3]) if match[3] else None
        try:
            low = date(year, month, day or 1)
            high = date(year, month, day or calendar.monthrange(year, month)[1])
        except ValueError as exc:
            raise ValueError(f"invalid date-style version {value!r}") from exc
        return _Version("date", (low.toordinal(),), (high.toordinal(),))
    numeric = value[1:] if allow_prefix and value[:1] in ("v", "V") else value
    if _NUMERIC_VERSION.fullmatch(numeric):
        parts = tuple(int(part) for part in numeric.split("."))
        while len(parts) > 1 and parts[-1] == 0:
            parts = parts[:-1]
        return _Version("numeric", parts, parts)
    raise ValueError(f"unsupported version {value!r}; expected numeric components or YYYY-MM[-DD]")


def _make_range(clauses: list[tuple[str, _Version]]) -> _VersionRange | None:
    if not clauses:
        return None
    kind = clauses[0][1].kind
    low = high = None
    low_inclusive = high_inclusive = True
    for operator, version in clauses:
        if version.kind != kind:
            raise ValueError("date and numeric version constraints cannot be mixed")
        if operator in (">", ">=", "=", "=="):
            bound = version.high if operator == ">" else version.low
            inclusive = operator != ">"
            if low is None or bound > low:
                low, low_inclusive = bound, inclusive
            elif bound == low:
                low_inclusive = low_inclusive and inclusive
        if operator in ("<", "<=", "=", "=="):
            bound = version.low if operator == "<" else version.high
            inclusive = operator != "<"
            if high is None or bound < high:
                high, high_inclusive = bound, inclusive
            elif bound == high:
                high_inclusive = high_inclusive and inclusive
    if low is not None and high is not None and (
        low > high or (low == high and not (low_inclusive and high_inclusive))
    ):
        raise ValueError("inconsistent version bounds describe an empty range")
    return _VersionRange(kind, low, low_inclusive, high, high_inclusive)


def _legacy_ranges(
    metadata: Mapping[str, object],
) -> tuple[_VersionRange | None, list[tuple[str, _Version]]]:
    clauses = [
        (operator, _version(metadata[key], allow_prefix=True))
        for key, operator in (("from", ">="), ("to", "<="))
        if metadata.get(key) is not None
    ]
    if len({version.kind for _, version in clauses}) > 1:
        raise ValueError("legacy from/to cannot mix calendar dates and numeric versions")
    bounds = _make_range(clauses)
    if bounds is not None and bounds.kind == "date":
        return bounds, []
    return None, clauses


def _version_range(
    metadata: Mapping[str, object], legacy: list[tuple[str, _Version]],
) -> _VersionRange | None:
    clauses = list(legacy)
    if "version" in metadata:
        expression = metadata["version"]
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 1024:
            raise ValueError("applies_to.version must be nonempty text of at most 1024 characters")
        for raw in expression.split(","):
            match = _CLAUSE.fullmatch(raw.strip())
            if not match:
                raise ValueError(f"malformed version constraint {raw!r}")
            clauses.append((match[1] or "==", _version(match[2])))
    return _make_range(clauses)


def _match_range(bounds: _VersionRange, version: _Version, label: str) -> ApplicabilityResult:
    if version.kind != bounds.kind:
        return ApplicabilityResult("unknown", (f"{label} and applicability use different version families",))
    if bounds.low is not None and (
        version.high < bounds.low
        or (version.high == bounds.low and not bounds.low_inclusive)
    ):
        return ApplicabilityResult("mismatch", (f"{label} is below the applicability range",))
    if bounds.high is not None and (
        version.low > bounds.high
        or (version.low == bounds.high and not bounds.high_inclusive)
    ):
        return ApplicabilityResult("mismatch", (f"{label} is above the applicability range",))
    if (
        bounds.low is not None and (
            version.low < bounds.low or (version.low == bounds.low and not bounds.low_inclusive)
        )
    ) or (
        bounds.high is not None and (
            version.high > bounds.high or (version.high == bounds.high and not bounds.high_inclusive)
        )
    ):
        return ApplicabilityResult("unknown", (f"{label} has insufficient date precision for these bounds",))
    return ApplicabilityResult("match", (f"{label} is within the applicability range",))


def _match_calendar(bounds: _VersionRange, now: datetime | date | None) -> ApplicabilityResult:
    if now is None:
        now = datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.utcoffset() is None:
            return ApplicabilityResult("unknown", ("calendar evaluation now requires a timezone",))
        try:
            day = now.astimezone(timezone.utc).date()
        except (OverflowError, ValueError):
            return ApplicabilityResult("unknown", ("calendar evaluation now is outside the supported UTC range",))
    elif isinstance(now, date):
        day = now
    else:
        return ApplicabilityResult("unknown", ("calendar evaluation now must be a date or aware datetime",))
    version = _Version("date", (day.toordinal(),), (day.toordinal(),))
    return _match_range(bounds, version, f"UTC calendar date {day.isoformat()!r}")


def _match_version(
    metadata: Mapping[str, object], context: Mapping[str, str],
    legacy: list[tuple[str, _Version]],
) -> ApplicabilityResult | None:
    try:
        bounds = _version_range(metadata, legacy)
    except ValueError as exc:
        return ApplicabilityResult("unknown", (str(exc),))
    if bounds is None:
        return None
    actual = context.get("version")
    if not actual or not actual.strip():
        return ApplicabilityResult("unknown", ("context.version is missing; version applicability is unknown",))
    try:
        version = _version(actual, allow_prefix=True)
    except ValueError as exc:
        return ApplicabilityResult("unknown", (f"context.version: {exc}",))
    return _match_range(bounds, version, f"context.version {actual!r}")


def _match_name(key: str, expected: object, context: Mapping[str, str]) -> ApplicabilityResult:
    if not isinstance(expected, str) or not expected.strip():
        return ApplicabilityResult("unknown", (f"applies_to.{key} must be nonempty text",))
    actual = context.get(key, "").strip()
    if not actual:
        return ApplicabilityResult("unknown", (f"context.{key} is missing",))
    matches = actual.casefold() == expected.strip().casefold()
    return ApplicabilityResult(
        "match" if matches else "mismatch",
        (f"context.{key} {actual!r} {'matches' if matches else 'does not match'} {expected!r}",),
    )


def _match_tools(expected: object, context: Mapping[str, str]) -> ApplicabilityResult:
    if not isinstance(expected, (list, tuple)) or any(
        not isinstance(tool, str) or not tool.strip() for tool in expected
    ):
        return ApplicabilityResult("unknown", ("applies_to.tools must be a list of nonempty tool names",))
    if not expected:
        return ApplicabilityResult("match", ("empty applies_to.tools is unrestricted",))
    actual = context.get("tool", "").strip()
    if not actual:
        return ApplicabilityResult("unknown", ("context.tool (host) is missing for legacy applies_to.tools",))
    allowed = {tool.strip().casefold() for tool in expected}
    matches = actual.casefold() in allowed
    return ApplicabilityResult(
        "match" if matches else "mismatch",
        (f"context.tool (host) {actual!r} {'matches' if matches else 'does not match'} legacy tools: {', '.join(sorted(allowed))}",),
    )


def match_applicability(
    applies_to: object,
    context: Mapping[str, str] | None = None,
    *,
    now: datetime | date | None = None,
) -> ApplicabilityResult:
    """Match all declared constraints, distinguishing ignorance from mismatch.

    None/empty metadata is explicitly unrestricted. ``product`` and ``tool``
    compare names case-insensitively; legacy ``tools`` checks the host in
    ``context.tool``, never ``context.product``. Product is optional unless
    declared in applicability. Legacy ``from``/``to`` are inclusive CALENDAR
    bounds when ISO YYYY-MM or YYYY-MM-DD, evaluated at the UTC date of ``now``
    (default: current UTC clock). A month starts on its first day and ends after
    its entire last day, including leap days. Numeric/dotted legacy bounds,
    optionally v-prefixed, instead require observed ``context.version``.
    Mixing calendar and numeric legacy bounds is unknown with a diagnostic.

    Explicit ``version`` ALWAYS requires observed ``context.version``; never
    substitute the clock, even for date-style releases. It supports comma-AND
    ``>=``, ``>``, ``<=``, ``<``, ``==``/``=`` or a bare exact version. Numeric
    components compare numerically (1.2 == 1.2.0); structured release dates use
    YYYY-MM[-DD]. A month-valued release overlapping a day bound is unknown,
    not a match. Calendar windows and explicit version constraints both apply.
    Historical evidence callers supply event time, not today's read time.

    Missing context, malformed constraints, unsupported fields, mixed version
    families and arbitrary release labels yield unknown with diagnostics.
    A definite mismatch on another dimension still wins. No generic semver,
    prerelease, wildcard, lexical-label ordering or product-version guessing is
    attempted. No input is mutated.
    """
    if applies_to is None or (isinstance(applies_to, Mapping) and not applies_to):
        return ApplicabilityResult("match", ("no applicability constraints; unrestricted",))
    if not isinstance(applies_to, Mapping) or any(not isinstance(key, str) for key in applies_to):
        return ApplicabilityResult("unknown", ("applies_to must be a mapping with text keys",))
    if context is None:
        context = {}
    if not isinstance(context, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in context.items()
    ):
        return ApplicabilityResult("unknown", ("context must be a mapping of text names to text values",))
    results = []
    unsupported = applies_to.keys() - _FIELDS
    if unsupported:
        results.append(ApplicabilityResult(
            "unknown", (f"unsupported applicability fields: {', '.join(sorted(unsupported))}",),
        ))
    for key in ("product", "tool"):
        if key in applies_to:
            results.append(_match_name(key, applies_to[key], context))
    if "tools" in applies_to:
        results.append(_match_tools(applies_to["tools"], context))
    try:
        calendar_bounds, legacy_versions = _legacy_ranges(applies_to)
    except ValueError as exc:
        results.append(ApplicabilityResult("unknown", (str(exc),)))
        calendar_bounds, legacy_versions = None, []
    if calendar_bounds is not None:
        results.append(_match_calendar(calendar_bounds, now))
    version = _match_version(applies_to, context, legacy_versions)
    if version is not None:
        results.append(version)
    if not results:
        return ApplicabilityResult("match", ("no applicability constraints; unrestricted",))
    state: ApplicabilityState = "match"
    if any(result.state == "mismatch" for result in results):
        state = "mismatch"
    elif any(result.state == "unknown" for result in results):
        state = "unknown"
    return ApplicabilityResult(state, tuple(reason for result in results for reason in result.reasons))
