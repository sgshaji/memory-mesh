"""Read-only skill diagnostics; reported outcomes are not execution receipts.

Skill descriptors live under ``skills/``. Both vault ``type: skill`` notes
and named ``SKILL.md`` descriptors are supported without rewriting either.
Dependency problems recommend human review, never edits or deactivation.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

from . import applicability, confidence, config, notes, outcomes
from .config import Vault, VaultError
from .feedback_config import load_settings
from .outcome_types import OutcomeEvent
from .schema import CONFIDENCE, KNOWLEDGE_TYPES, STATUSES


@dataclass(frozen=True)
class DependencyHealth:
    """Canonical dependency diagnostics; unresolved references have no subject ID."""

    reference: str
    subject_id: str | None = None
    status: str | None = None
    confidence: str | None = None
    potentially_stale: bool = False
    needs_review: bool = False
    reasons: tuple[str, ...] = ()
    last_verified: str | None = None
    applicability: dict[str, object] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    confidence_source: str = "unknown"

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "subject_id": self.subject_id,
            "status": self.status,
            "confidence": self.confidence,
            "confidence_source": self.confidence_source,
            "potentially_stale": self.potentially_stale,
            "needs_review": self.needs_review,
            "reasons": list(self.reasons),
            "last_verified": self.last_verified,
            "applicability": deepcopy(self.applicability),
            "evidence": deepcopy(self.evidence),
        }


@dataclass(frozen=True)
class SkillHealth:
    """Confidence and review are independent diagnostics, never admission authority.

    ``failed_recently`` includes any clock-valid failure in the recent window;
    the review quorum uses the shared matched-session evidence instead.
    """

    subject_id: str
    confidence: str | None
    potentially_stale: bool
    needs_review: bool
    reasons: tuple[str, ...]
    dependencies: tuple[DependencyHealth, ...]
    last_verified: str | None
    failed_recently: bool
    applicability: dict[str, object]
    evidence: dict[str, object]
    confidence_source: str = "unknown"

    @property
    def reference(self) -> str:
        return self.subject_id

    def as_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "reference": self.reference,
            "confidence": self.confidence,
            "confidence_source": self.confidence_source,
            "potentially_stale": self.potentially_stale,
            "needs_review": self.needs_review,
            "reasons": list(self.reasons),
            "dependencies": [item.as_dict() for item in self.dependencies],
            "last_verified": self.last_verified,
            "failed_recently": self.failed_recently,
            "applicability": deepcopy(self.applicability),
            "evidence": deepcopy(self.evidence),
        }


@dataclass(frozen=True)
class _Descriptor:
    note: notes.Note
    dependencies: tuple[str, ...]
    reasons: tuple[str, ...]


def _reference(value: str) -> str:
    value = value.strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
    value = value.replace("\\", "/")
    return value[:-3] if value.endswith(".md") else value


def _descriptor(note: notes.Note) -> _Descriptor | None:
    named_skill = (
        note.path.name == "SKILL.md"
        and note.type is None
        and isinstance(note.meta.get("name"), str)
        and bool(note.meta["name"].strip())
    )
    broken_skill = note.path.name == "SKILL.md" and note.parse_error is not None
    if note.type != "skill" and not named_skill and not broken_skill:
        return None
    reasons: list[str] = []
    if note.parse_error:
        reasons.append(f"Malformed skill descriptor: {note.parse_error}")
    dependencies: list[str] = []
    raw = note.meta.get("depends_on", [])
    if not isinstance(raw, list):
        reasons.append("depends_on must be a list of knowledge references")
    else:
        for value in raw:
            if not isinstance(value, str) or not value.strip():
                reasons.append("depends_on contains an invalid knowledge reference")
                continue
            ref = _reference(value)
            if not ref:
                reasons.append("depends_on contains an empty knowledge reference")
            elif ref in dependencies:
                reasons.append(f"Duplicate dependency declaration: {ref}")
            else:
                dependencies.append(ref)
    confidence = note.meta.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE:
        reasons.append("Skill confidence must be high, medium or low")
    return _Descriptor(note, tuple(dependencies), tuple(dict.fromkeys(reasons)))


def _markdown_paths(vault: Vault, folder: str) -> Iterator[Path]:
    base = vault.path(folder)
    if (
        not base.is_dir()
        or base.is_symlink()
        or base.resolve() != base
        or not base.resolve().is_relative_to(vault.root)
    ):
        return
    for directory, dirs, files in os.walk(base, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(
            name for name in dirs
            if not (parent / name).is_symlink()
            and (parent / name).resolve() == parent / name
            and (parent / name).resolve().is_relative_to(base)
        )
        for name in sorted(files):
            path = parent / name
            if (
                not name.endswith(".md")
                or path.is_symlink()
                or not path.resolve().is_relative_to(base)
                or not path.is_file()
            ):
                continue
            yield path


def _descriptors(vault: Vault) -> list[_Descriptor]:
    found: list[_Descriptor] = []
    for path in _markdown_paths(vault, config.SKILLS):
        try:
            if notes.resolve_ref(vault, path.relative_to(vault.root).as_posix()) is None:
                continue
        except notes.NoteReferenceError:
            continue
        try:
            note = notes.load_note(path, vault)
        except (OSError, UnicodeError) as exc:
            note = notes.Note(path, {}, "", vault, parse_error=str(exc))
        descriptor = _descriptor(note)
        if descriptor is not None:
            found.append(descriptor)
    return sorted(found, key=lambda item: item.note.ref)


def _select_skill(
    vault: Vault, reference: str, descriptors: list[_Descriptor],
) -> _Descriptor:
    if not isinstance(reference, str) or not reference.strip():
        raise VaultError("skill reference must be nonempty text")
    ref = _reference(reference)
    exact = [item for item in descriptors if item.note.ref == ref]
    matches = exact or [
        item for item in descriptors
        if ref in _aliases(item.note)
    ]
    if not matches:
        raise VaultError(f"unknown skill reference: {reference}")
    if len(matches) > 1:
        choices = ", ".join(item.note.ref for item in matches)
        raise VaultError(f"ambiguous skill reference: {reference}; use one of: {choices}")
    selected = matches[0]
    if notes.resolve_ref(vault, selected.note.ref) is None:
        raise VaultError(f"skill descriptor no longer resolves safely: {selected.note.ref}")
    return selected


def _aliases(note: notes.Note) -> set[str]:
    if note.path.name == "SKILL.md":
        aliases = {note.path.parent.name, note.ref.removesuffix("/SKILL")}
    else:
        aliases = {note.path.stem}
    name = note.meta.get("name")
    if (
        isinstance(name, str)
        and name.strip()
        and all(char.isalnum() or char in "-_" for char in name.strip())
    ):
        aliases.add(name.strip())
    return aliases


def _status_reasons(note: notes.Note) -> list[str]:
    reasons: list[str] = []
    if note.status in ("candidate", "stale", "resolved", "superseded", "rejected"):
        reasons.append(f"Recorded status is {note.status}")
    replacement = note.meta.get("superseded_by")
    if replacement:
        reasons.append(f"Supersession is recorded: {replacement}")
    return reasons


class _DependencyLookup:
    def __init__(self, vault: Vault):
        self.vault = vault
        self._references: dict[str, tuple[notes.Note | None, str | None]] = {}
        self._notes: dict[Path, notes.Note] = {}
        self._filenames: dict[str, list[Path]] | None = None

    def get(self, reference: str) -> tuple[notes.Note | None, str | None]:
        if reference not in self._references:
            self._references[reference] = self._load(reference)
        return self._references[reference]

    def _load(self, reference: str) -> tuple[notes.Note | None, str | None]:
        try:
            target = reference
            if "/" not in reference:
                if self._filenames is None:
                    self._filenames = defaultdict(list)
                    for candidate in _markdown_paths(self.vault, config.KNOWLEDGE):
                        name = candidate.stem.casefold() if os.name == "nt" else candidate.stem
                        self._filenames[name].append(candidate)
                name = _reference(reference)
                candidates = self._filenames.get(name.casefold() if os.name == "nt" else name, [])
                if not candidates:
                    return None, "Missing knowledge dependency"
                if len(candidates) != 1:
                    return None, "Ambiguous knowledge dependency; use a full canonical reference"
                target = candidates[0].relative_to(self.vault.root).as_posix()
            path = notes.resolve_ref(self.vault, target)
            if path is None:
                return None, "Missing knowledge dependency"
            if not path.is_relative_to(self.vault.path(config.KNOWLEDGE)):
                return None, "Dependency must reference a canonical knowledge note"
            if path not in self._notes:
                self._notes[path] = notes.load_note(path, self.vault)
            note = self._notes[path]
            if note.parse_error:
                return note, f"Malformed dependency frontmatter: {note.parse_error}"
            if note.type not in KNOWLEDGE_TYPES:
                return note, "Dependency must reference a knowledge note, not an index or descriptor"
            return note, None
        except (VaultError, OSError, UnicodeError) as exc:
            return None, f"Cannot resolve dependency: {exc}"


def _now(value: datetime | date | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise VaultError("skill health now requires a timezone")
        try:
            return value.astimezone(timezone.utc)
        except (OverflowError, ValueError) as exc:
            raise VaultError("skill health now is outside the supported UTC range") from exc
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), timezone.utc)
    raise VaultError("skill health now must be a date or datetime")


@dataclass(frozen=True)
class _Freshness:
    last_verified: str | None
    potentially_stale: bool
    needs_review: bool
    reasons: tuple[str, ...]


def _freshness(
    declared: object, observed: str | None, today: date, review_days: int,
) -> _Freshness:
    dates: list[date] = []
    reasons: list[str] = []
    for label, value in (("Declared last_verified", declared), ("Evidence last_verified", observed)):
        if value is None:
            continue
        try:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
        except ValueError:
            reasons.append(f"{label} is invalid; expected YYYY-MM-DD")
            continue
        if parsed > today:
            reasons.append(f"{label} is in the future: {value}")
        else:
            dates.append(parsed)
    needs_review = bool(reasons)
    if not dates:
        reasons.append("Verification age is unknown (no usable last_verified date)")
        return _Freshness(None, False, needs_review, tuple(reasons))
    latest = max(dates)
    age = (today - latest).days
    stale = age > review_days
    if stale:
        reasons.append(f"Last verified {age} days ago; skill review interval is {review_days} days")
    return _Freshness(latest.isoformat(), stale, needs_review or stale, tuple(reasons))


def _prior_confidence(note: notes.Note) -> str | None:
    value = note.meta.get("confidence")
    return value if isinstance(value, str) and value in CONFIDENCE else None


def _display_confidence(
    note: notes.Note, evaluation: confidence.EvidenceEvaluation,
) -> tuple[str | None, str]:
    if evaluation.event_ids:
        return evaluation.confidence, "reported_evidence"
    recorded = _prior_confidence(note)
    return recorded, "recorded_metadata" if recorded is not None else "unknown"


class _Assessment:
    def __init__(
        self, vault: Vault, context: Mapping[str, str] | None,
        now: datetime | date | None, events: Iterable[OutcomeEvent] | None,
    ):
        self.vault = vault
        self.context = context
        self.now = _now(now)
        self.policy = load_settings(vault).feedback
        self.lookup = _DependencyLookup(vault)
        self.dependencies: dict[str, DependencyHealth] = {}
        self.events: dict[tuple[str, str], list[OutcomeEvent]] = defaultdict(list)
        seen: dict[str, OutcomeEvent] = {}
        for event in outcomes.collect_evidence(vault) if events is None else events:
            if not isinstance(event, OutcomeEvent):
                raise VaultError("skill health evidence must contain OutcomeEvent values")
            previous = seen.get(event.event_id)
            if previous is not None and previous != event:
                raise VaultError(f"conflicting duplicate outcome event_id: {event.event_id}")
            seen[event.event_id] = event
            if event.subject_type in ("skill", "knowledge"):
                self.events[event.subject_type, event.subject_id].append(event)

    def dependency(self, reference: str) -> DependencyHealth:
        note, problem = self.lookup.get(reference)
        key = note.ref if note is not None else reference
        if key in self.dependencies:
            return self.dependencies[key]
        if problem is not None or note is None:
            result = DependencyHealth(
                reference=key, subject_id=note.ref if note is not None else None,
                status=note.status if note is not None else None,
                potentially_stale=True, needs_review=True,
                reasons=(problem or "Missing knowledge dependency",),
            )
        else:
            evaluation = confidence.evaluate_evidence(
                self.events["knowledge", note.ref], note.meta.get("applies_to"),
                now=self.now, policy=self.policy, prior_confidence=_prior_confidence(note),
            )
            applicable = applicability.match_applicability(
                note.meta.get("applies_to"), self.context, now=self.now,
            )
            freshness = _freshness(
                note.meta.get("last_verified"), evaluation.last_verified,
                self.now.date(), self.policy.skill_review_days,
            )
            level, source = _display_confidence(note, evaluation)
            reasons = _status_reasons(note)
            stale = bool(reasons) or freshness.potentially_stale
            reasons.extend(freshness.reasons)
            invalid_metadata = False
            for name, allowed in (("status", STATUSES), ("confidence", CONFIDENCE)):
                value = note.meta.get(name)
                if value is not None and value not in allowed:
                    reasons.append(f"Dependency {name} is invalid")
                    invalid_metadata = True
            low = level == "low" and (
                source == "recorded_metadata" or any(
                    item.included and item.applicability.state == "match"
                    and item.bucket in ("held", "failed")
                    and item.event.reason not in ("misapplied", "context_mismatch")
                    for item in evaluation.contributions
                )
            )
            if low:
                reasons.append("Dependency has low confidence")
                stale = True
            if applicable.state != "match":
                reasons.extend(
                    f"Dependency applicability {applicable.state}: {reason}"
                    for reason in applicable.reasons
                )
            if evaluation.needs_review:
                reasons.extend(evaluation.reasons)
            stale = (
                stale or applicable.state == "mismatch"
                or evaluation.recent_behaviour_changes >= self.policy.behaviour_change_failures
            )
            result = DependencyHealth(
                reference=note.ref, subject_id=note.ref, status=note.status,
                confidence=level, confidence_source=source,
                potentially_stale=stale,
                needs_review=stale or freshness.needs_review or invalid_metadata
                or applicable.state != "match" or evaluation.needs_review,
                reasons=tuple(dict.fromkeys(reasons)), last_verified=freshness.last_verified,
                applicability=applicable.as_dict(), evidence=evaluation.as_dict(),
            )
        self.dependencies[key] = result
        return result

    def skill(self, descriptor: _Descriptor) -> SkillHealth:
        note = descriptor.note
        skill_policy = replace(
            self.policy, behaviour_change_failures=self.policy.skill_failure_threshold,
        )
        evaluation = confidence.evaluate_evidence(
            self.events["skill", note.ref], note.meta.get("applies_to"),
            now=self.now, policy=skill_policy, prior_confidence=_prior_confidence(note),
        )
        applicable = applicability.match_applicability(
            note.meta.get("applies_to"), self.context, now=self.now,
        )
        freshness = _freshness(
            note.meta.get("last_verified"), evaluation.last_verified,
            self.now.date(), self.policy.skill_review_days,
        )
        level, source = _display_confidence(note, evaluation)
        status_reasons = _status_reasons(note)
        reasons = [*descriptor.reasons, *status_reasons, *freshness.reasons]
        if applicable.state != "match":
            reasons.extend(
                f"Skill applicability {applicable.state}: {reason}"
                for reason in applicable.reasons
            )
        if not evaluation.event_ids:
            reasons.append(
                "No reported skill outcomes; recorded confidence is not new execution evidence"
                if source == "recorded_metadata"
                else "No reported skill outcomes; confidence is unknown"
            )
        if evaluation.needs_review:
            reasons.extend(evaluation.reasons)
        failed_recently = any(
            not item.future_excluded and item.bucket == "failed"
            and item.age_days <= self.policy.recent_days
            for item in evaluation.contributions
        )
        failed_sessions = evaluation.recent_failed_sessions
        repeated_failures = len(failed_sessions) >= self.policy.skill_failure_threshold
        if repeated_failures:
            reasons.append(
                f"Recent failed skill outcomes from {len(failed_sessions)} independent sessions "
                f"within {self.policy.recent_days} days; "
                f"review threshold is {self.policy.skill_failure_threshold}"
            )
        dependencies: list[DependencyHealth] = []
        seen: set[str] = set()
        duplicate = False
        for reference in descriptor.dependencies:
            dependency = self.dependency(reference)
            key = dependency.subject_id or dependency.reference
            if key in seen:
                reasons.append(f"Duplicate dependency declaration resolves to: {key}")
                duplicate = True
                continue
            seen.add(key)
            dependencies.append(dependency)
            if dependency.needs_review:
                reasons.extend(
                    f"Dependency {dependency.reference}: {reason}" for reason in dependency.reasons
                )
        stale = (
            bool(status_reasons) or freshness.potentially_stale or repeated_failures
            or applicable.state == "mismatch"
            or any(item.potentially_stale for item in dependencies)
        )
        return SkillHealth(
            subject_id=note.ref, confidence=level, confidence_source=source,
            potentially_stale=stale,
            needs_review=stale or bool(descriptor.reasons) or duplicate
            or freshness.needs_review or applicable.state != "match" or evaluation.needs_review
            or any(item.needs_review for item in dependencies),
            reasons=tuple(dict.fromkeys(reasons)), dependencies=tuple(dependencies),
            last_verified=freshness.last_verified, failed_recently=failed_recently,
            applicability=applicable.as_dict(), evidence=evaluation.as_dict(),
        )


def assess_skill(
    vault: Vault, reference: str, *, context: Mapping[str, str] | None = None,
    now: datetime | date | None = None, events: Iterable[OutcomeEvent] | None = None,
) -> SkillHealth:
    """Assess one skill, raising VaultError for unknown or ambiguous requests.

    ``events`` accepts canonical OutcomeEvents; an explicit empty iterable
    disables journal reads. Absent events are collected from the shared journal
    and legacy episode projection. No event or descriptor is modified.
    """
    descriptor = _select_skill(vault, reference, _descriptors(vault))
    return _Assessment(vault, context, now, events).skill(descriptor)


def assess_skills(
    vault: Vault, *, context: Mapping[str, str] | None = None,
    now: datetime | date | None = None, events: Iterable[OutcomeEvent] | None = None,
) -> list[SkillHealth]:
    """Assess descriptors in canonical-reference order with one evidence pass.

    Notes, reference resolutions and dependency evaluations are reused across
    the batch. Missing optional metadata stays unknown or unrestricted. A
    recorded legacy confidence is displayed only when there are no reported
    outcomes; ``confidence_source`` distinguishes that from shared evaluation.
    """
    descriptors = _descriptors(vault)
    if not descriptors:
        return []
    assessment = _Assessment(vault, context, now, events)
    return [assessment.skill(descriptor) for descriptor in descriptors]
