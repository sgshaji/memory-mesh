"""Read-only inbox attention, separate from confidence and admission.

Ranking is lexicographic: high > normal > low, resolved episode linkage,
additional distinct episodes, newest contextual activity, then full reference.
Repeated links (including a source_episode plus a reverse link) count once per
episode. Recurrence measures documented context, not independent verification.
Missing signals mean normal. Unknown dates remain unknown; naive legacy dates
are interpreted as UTC with a diagnostic, and future activity is capped at now.
Gap candidates participate in attention/aging only, never as factual claims.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

from .. import confidence, config, fsutil, indexes, outcomes
from ..applicability import ApplicabilityResult, match_applicability
from ..config import Vault, VaultError
from ..episodes import parse_episode
from ..experience import get_mode
from ..feedback_config import FeedbackPolicy, load_settings
from ..notes import WIKILINK_RE, Note, load_note, section
from ..outcome_types import OutcomeEvent, parse_timestamp
from ..routing_diagnostics import RecallAttempt, read_attempts
from ..schema import CONFIDENCE, KNOWLEDGE_TYPES

_SIGNALS = {"high": 2, "normal": 1, "low": 0}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class CandidatePriority:
    path: Path
    ref: str
    title: str
    kind: str
    signal: str
    source_episode: str | None
    episode_refs: tuple[str, ...]
    recurrence: int
    captured_at: datetime | None
    age_days: float | None
    last_seen_at: datetime | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def linked(self) -> bool:
        return bool(self.episode_refs)

    @property
    def is_gap(self) -> bool:
        return self.kind == "gap"

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["path"] = self.ref + ".md"
        for name in ("captured_at", "last_seen_at"):
            value = getattr(self, name)
            data[name] = value.isoformat() if value is not None else None
        for name in ("episode_refs", "reasons", "warnings"):
            data[name] = list(getattr(self, name))
        data["linked"] = self.linked
        data["is_gap"] = self.is_gap
        return data


@dataclass(frozen=True)
class InboxHealth:
    pending_count: int
    candidate_count: int
    gap_count: int
    high_signal_count: int
    linked_count: int
    oldest_age_days: float | None
    oldest_ref: str | None
    review_days: int
    overdue_count: int
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


def _now(now: datetime | date | None) -> datetime:
    dt = now if now is not None else datetime.now(timezone.utc)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime.combine(dt, time(), tzinfo=timezone.utc)
    if not isinstance(dt, datetime):
        raise VaultError("analytics now must be a date or datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _timestamp(value: object, ref: str, now: datetime) -> tuple[datetime | None, tuple[str, ...]]:
    if not isinstance(value, str) or not value.strip():
        return None, (f"{ref}: missing or invalid captured timestamp; age/recency unknown",)
    warnings = []
    try:
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:[Tt ]|$)", value.strip()):
            raise ValueError("expected an ISO calendar date or timestamp")
        dt = datetime.fromisoformat(value.strip())
        if dt.tzinfo is None:
            warnings.append(f"{ref}: captured timestamp has no timezone; interpreted as UTC")
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None, (f"{ref}: invalid captured timestamp; age/recency unknown",)
    if dt > now:
        warnings.append(f"{ref}: captured timestamp is in the future; age is clamped to zero and recency to now")
    return dt, tuple(warnings)


def _note_directory(vault: Vault, folder: str, diagnostics: list[str]) -> Path | None:
    base = vault.path(folder)
    try:
        if not base.exists():
            return None
        if not base.is_dir() or base.resolve() != base:
            diagnostics.append(f"{folder}: expected a regular directory inside the vault")
            return None
    except (OSError, RuntimeError):
        diagnostics.append(f"{folder}: cannot resolve note directory")
        return None
    return base


def _read_notes(vault: Vault, folder: str, diagnostics: list[str]) -> list[Note]:
    """Inventory once, isolating unreadable files and rejecting redirected paths."""
    base = _note_directory(vault, folder, diagnostics)
    if base is None:
        return []
    result = []
    try:
        paths = sorted(base.rglob("*.md"))
    except OSError:
        diagnostics.append(f"{folder}: cannot enumerate notes")
        return []
    for path in paths:
        relative = path.relative_to(vault.root).as_posix()
        try:
            if path.is_symlink() or path.resolve() != path or not path.is_file():
                diagnostics.append(f"{relative}: redirected or non-regular note ignored")
                continue
            note = load_note(path, vault)
        except (OSError, UnicodeError, ValueError, RuntimeError):
            diagnostics.append(f"{relative}: cannot read note")
            continue
        if note.parse_error:
            diagnostics.append(f"{relative}: malformed frontmatter; note ignored")
        else:
            result.append(note)
    return result


def _inventory_notes(
    vault: Vault, folder: str, supplied: Iterable[Note] | None, diagnostics: list[str],
) -> list[Note]:
    """Reuse this operation's parsed notes, retaining containment and diagnostics."""
    if supplied is None:
        return _read_notes(vault, folder, diagnostics)
    base = _note_directory(vault, folder, diagnostics)
    if base is None:
        return []
    notes = list(supplied)
    if any(
        not isinstance(note, Note) or not isinstance(note.path, Path)
        or not isinstance(note.vault, Vault) or note.vault.root != vault.root
        or not isinstance(note.meta, dict) or not isinstance(note.body, str)
        for note in notes
    ):
        raise VaultError("preloaded inventories must contain parsed notes from the current vault")
    result: dict[Path, Note] = {}
    for note in sorted(notes, key=lambda item: item.path):
        path = note.path
        if not path.is_absolute() or not path.is_relative_to(base) or path.suffix != ".md":
            raise VaultError(f"preloaded note is outside the {folder} Markdown inventory")
        relative = path.relative_to(vault.root).as_posix()
        try:
            if path.is_symlink() or path.resolve() != path or not path.is_file():
                diagnostics.append(f"{relative}: redirected or non-regular note ignored")
                continue
        except (OSError, ValueError, RuntimeError):
            diagnostics.append(f"{relative}: cannot read note")
            continue
        if note.parse_error:
            diagnostics.append(f"{relative}: malformed frontmatter; note ignored")
            continue
        previous = result.get(path)
        if previous is not None and (previous.meta, previous.body) != (note.meta, note.body):
            raise VaultError("conflicting preloaded snapshots of the same note")
        result[path] = note
    return list(result.values())


class _References:
    def __init__(self, notes: list[Note], folder: str):
        self.folder = folder
        self.by_ref = {note.ref: note for note in notes}
        self.by_slug: dict[str, list[str]] = {}
        for ref in self.by_ref:
            self.by_slug.setdefault(ref.rsplit("/", 1)[-1], []).append(ref)

    def resolve(self, value: object) -> tuple[str | None, str | None]:
        if (
            not isinstance(value, str) or not value.strip()
            or len(value.splitlines()) != 1 or any(ord(char) < 32 for char in value)
        ):
            return None, "invalid reference"
        ref = value.strip()
        if match := WIKILINK_RE.fullmatch(ref):
            ref = match.group(1).strip()
        elif ref.startswith("[["):
            return None, "malformed wikilink"
        ref = ref.replace("\\", "/")
        if ref.endswith(".md"):
            ref = ref[:-3]
        if ":" in ref or any(part in ("", ".", "..") for part in ref.split("/")):
            return None, "invalid local reference"
        if "/" in ref:
            if not ref.startswith(self.folder + "/"):
                return None, f"reference outside {self.folder}/"
            return (ref, None) if ref in self.by_ref else (None, "unresolved reference")
        matches = self.by_slug.get(ref, [])
        if len(matches) > 1:
            return None, "ambiguous bare reference; use a full vault-relative reference"
        return (matches[0], None) if matches else (None, "unresolved reference")


def _episode_links(
    candidates: list[Note], episodes: list[Note], diagnostics: list[str],
) -> dict[str, set[str]]:
    candidates_by_ref = _References(candidates, config.INBOX)
    links: dict[str, set[str]] = {}
    for episode in episodes:
        for match in WIKILINK_RE.finditer(section(episode.body, "Candidate learnings")):
            ref = match.group(1).strip()
            candidate_ref, error = candidates_by_ref.resolve(ref)
            if candidate_ref is not None:
                links.setdefault(candidate_ref, set()).add(episode.ref)
            elif ref.replace("\\", "/").startswith(config.INBOX + "/") or (error and "ambiguous" in error):
                diagnostics.append(f"{episode.ref}: Candidate learnings: {error}")
    return links


def _sort_key(item: CandidatePriority) -> tuple[int, int, int, float, str, str]:
    recency = -(item.last_seen_at - _EPOCH).total_seconds() if item.last_seen_at is not None else float("inf")
    return (
        -_SIGNALS[item.signal], -int(item.linked), -item.recurrence,
        recency, item.ref.casefold(), item.ref,
    )


def _snapshot(
    vault: Vault, now: datetime, *, inbox: Iterable[Note] | None = None,
    episodes: Iterable[Note] | None = None,
) -> tuple[list[CandidatePriority], list[str]]:
    diagnostics: list[str] = []
    candidates = []
    for note in _inventory_notes(vault, config.INBOX, inbox, diagnostics):
        if note.type in ("candidate", "gap"):
            candidates.append(note)
        elif note.type is None:
            diagnostics.append(f"{note.rel}: missing or invalid note type; not counted as a candidate")
    episode_notes = [
        note for note in _inventory_notes(vault, config.EPISODES, episodes, diagnostics)
        if note.type == "episode"
    ]
    episodes_by_ref = _References(episode_notes, config.EPISODES)
    links = _episode_links(candidates, episode_notes, diagnostics)
    episode_times: dict[str, tuple[datetime | None, tuple[str, ...]]] = {}
    result = []
    for note in candidates:
        if "processed" in note.meta:
            continue
        captured, time_warnings = _timestamp(note.meta.get("captured"), note.ref, now)
        warnings = list(time_warnings)
        signal = note.meta.get("signal", "normal")
        if not isinstance(signal, str) or signal not in _SIGNALS:
            warnings.append(f"{note.ref}: invalid signal; normal attention used, metadata left unchanged")
            signal = "normal"
        source = note.meta.get("source_episode")
        episode_refs = set(links.get(note.ref, ()))
        if "source_episode" in note.meta:
            source_ref, error = episodes_by_ref.resolve(source)
            if source_ref is not None:
                episode_refs.add(source_ref)
            else:
                warnings.append(f"{note.ref}: source_episode: {error}; no contextual evidence added")
        activity = [captured] if captured is not None else []
        for ref in sorted(episode_refs):
            if ref not in episode_times:
                episode_times[ref] = _timestamp(episodes_by_ref.by_ref[ref].meta.get("captured"), ref, now)
            timestamp, episode_warnings = episode_times[ref]
            warnings.extend(episode_warnings)
            if timestamp is not None:
                activity.append(timestamp)
        last_seen = min(max(activity), now) if activity else None
        age = max(0.0, (now - captured).total_seconds() / 86400) if captured is not None else None
        recurrence = max(0, len(episode_refs) - 1)
        reasons = [
            f"signal={signal}: attention only, not approval or confidence",
            f"episode linkage: {len(episode_refs)} distinct resolved episode(s)",
            f"recurrence: {recurrence} additional distinct episode(s), not verified successes",
            f"recency: {last_seen.isoformat() if last_seen is not None else 'unknown'}",
        ]
        if note.type == "gap":
            reasons.append("knowledge gap: a need for investigation, not a factual claim")
        priority = CandidatePriority(
            path=note.path, ref=note.ref, title=note.title, kind=note.type or "candidate",
            signal=signal, source_episode=source if isinstance(source, str) else None,
            episode_refs=tuple(sorted(episode_refs)), recurrence=recurrence,
            captured_at=captured, age_days=age, last_seen_at=last_seen,
            reasons=tuple(reasons), warnings=tuple(dict.fromkeys(warnings)),
        )
        result.append(priority)
        diagnostics.extend(priority.warnings)
    return sorted(result, key=_sort_key), list(dict.fromkeys(diagnostics))


def rank_candidates(
    vault: Vault, *, now: datetime | None = None, diagnostics: list[str] | None = None,
    inbox: Iterable[Note] | None = None, episodes: Iterable[Note] | None = None,
) -> list[CandidatePriority]:
    """Rank pending candidates and gaps; no files or truth fields are changed.

    Reads each inbox/episode file once unless supplied by this read operation.
    Cached inventories retain path/type/parse checks without reopening bodies.
    Full references resolve exactly; bare
    slugs resolve only when unique. Unresolved source links diagnose but add
    no context. Pass diagnostics to receive inventory/link errors as well as
    the per-candidate warnings. Naive caller-provided now is interpreted as UTC.
    """
    ranked, warnings = _snapshot(vault, _now(now), inbox=inbox, episodes=episodes)
    if diagnostics is not None:
        seen = set(diagnostics)
        diagnostics.extend(warning for warning in warnings if warning not in seen)
    return ranked


def inbox_health(
    vault: Vault, *, now: datetime | None = None,
    inbox: Iterable[Note] | None = None, episodes: Iterable[Note] | None = None,
) -> InboxHealth:
    """Return attention counts/aging using feedback.inbox_review_days.

    pending_count includes gaps; candidate_count and gap_count partition it.
    Oldest/overdue use original capture age, never last episode activity.
    Unknown ages are excluded from oldest/overdue and explicitly diagnosed.
    inbox/episodes may reuse inventories from this read operation; [] is empty,
    while None retains disk discovery. No cross-operation cache is maintained.
    """
    policy = load_settings(vault).feedback
    ranked, warnings = _snapshot(vault, _now(now), inbox=inbox, episodes=episodes)
    dated = [item for item in ranked if item.age_days is not None]
    oldest = min(dated, key=lambda item: (-(item.age_days or 0), item.ref.casefold(), item.ref)) if dated else None
    overdue = sum(item.age_days is not None and item.age_days > policy.inbox_review_days for item in ranked)
    if oldest is not None and overdue:
        warnings.append(
            f"oldest pending inbox item exceeds review threshold of {policy.inbox_review_days} days "
            f"({oldest.ref}: {oldest.age_days:g} days); aging requests attention, not failure"
        )
    return InboxHealth(
        pending_count=len(ranked),
        candidate_count=sum(item.kind == "candidate" for item in ranked),
        gap_count=sum(item.is_gap for item in ranked),
        high_signal_count=sum(item.signal == "high" for item in ranked),
        linked_count=sum(item.linked for item in ranked),
        oldest_age_days=oldest.age_days if oldest is not None else None,
        oldest_ref=oldest.ref if oldest is not None else None,
        review_days=policy.inbox_review_days, overdue_count=overdue,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class KnowledgeAssessment:
    subject_id: str
    status: str | None
    confidence: str | None
    confidence_source: str
    needs_review: bool
    possible_behaviour_change: bool
    aging_due: bool
    never_exercised: bool
    maintenance_allowed: bool
    last_verified: str | None
    feedback: Mapping[str, int]
    reasons: tuple[str, ...]
    evidence: confidence.EvidenceEvaluation
    applicability: ApplicabilityResult

    @property
    def reference(self) -> str:
        return self.subject_id

    def as_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id, "reference": self.reference, "status": self.status,
            "confidence": self.confidence, "confidence_source": self.confidence_source,
            "needs_review": self.needs_review, "possible_behaviour_change": self.possible_behaviour_change,
            "aging_due": self.aging_due, "never_exercised": self.never_exercised,
            "maintenance_allowed": self.maintenance_allowed, "last_verified": self.last_verified,
            "feedback": dict(self.feedback), "reasons": list(self.reasons),
            "evidence": self.evidence.as_dict(), "applicability": self.applicability.as_dict(),
        }


def _knowledge_events(events: Iterable[OutcomeEvent]) -> dict[str, list[OutcomeEvent]]:
    unique: dict[str, OutcomeEvent] = {}
    grouped: dict[str, list[OutcomeEvent]] = defaultdict(list)
    for event in events:
        if not isinstance(event, OutcomeEvent):
            raise VaultError("knowledge assessment requires canonical OutcomeEvent values")
        previous = unique.get(event.event_id)
        if previous is not None and previous != event:
            raise VaultError("conflicting outcome IDs in knowledge assessment")
        unique[event.event_id] = event
    for event in unique.values():
        if event.subject_type == "knowledge":
            if not event.subject_id.startswith(config.KNOWLEDGE + "/") or event.subject_id.endswith(".md"):
                raise VaultError("knowledge outcomes require full canonical references without .md")
            grouped[event.subject_id].append(event)
    return grouped


def _served_counts(notes: list[Note], episodes: Iterable[Note], diagnostics: list[str]) -> dict[str, int]:
    """Compatibility exposure counts, not confidence evidence or inferred TSV votes."""
    references = _References(notes, config.KNOWLEDGE)
    served: dict[str, set[str]] = defaultdict(set)
    for note in episodes:
        if note.type != "episode" or note.status not in ("summarised", "mined") or note.meta.get("v2_evidence"):
            continue
        if config.EPISODE_UNREVIEWED + "/" in note.rel:
            continue
        episode = parse_episode(note)
        session = note.meta.get("session_id")
        identity = f"session:{session}" if isinstance(session, str) and session else f"episode:{note.ref}"
        for raw in [*episode.retrieved, *(use.ref for use in episode.used)]:
            ref, error = references.resolve(raw)
            if ref is not None:
                served[ref].add(identity)
            elif error and "ambiguous" in error:
                diagnostics.append(f"{note.ref}: ambiguous knowledge exposure excluded")
    return {ref: len(sessions) for ref, sessions in served.items()}


def _recorded_date(value: object, field: str, now: datetime, reasons: list[str]) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed > now.date():
        reasons.append(f"Invalid or future recorded {field}; not used for aging or verification")
        return None
    return parsed.isoformat()


def _assess_note(
    note: Note, events: list[OutcomeEvent], served: int | None, policy: FeedbackPolicy,
    now: datetime, mode: str,
) -> KnowledgeAssessment:
    reasons: list[str] = []
    prior = note.meta.get("confidence")
    prior = prior if isinstance(prior, str) and prior in CONFIDENCE else None
    evaluation = confidence.evaluate_evidence(
        events, note.meta.get("applies_to"), now=now, policy=policy, prior_confidence=prior,
    )
    applicable = match_applicability(note.meta.get("applies_to"), now=now)
    allowed = mode == "legacy" and "v2_admission" not in note.meta
    recorded = note.meta.get("feedback", {})
    if not isinstance(recorded, dict):
        reasons.append("Invalid recorded feedback; only explicit report counts can be used")
        recorded = {}
    raw = {}
    for key in ("served", "held", "failed", "unclear"):
        value = recorded.get(key, 0)
        if type(value) is not int or value < 0:
            reasons.append(f"Invalid recorded feedback.{key}; excluded")
            value = 0
        raw[key] = value
    if events:
        for key in ("held", "failed", "unclear"):
            raw[key] = evaluation.counts.get(key, 0)
    if served is not None:
        raw["served"] = served
    recorded_last = _recorded_date(note.meta.get("last_verified"), "last_verified", now, reasons)
    first = _recorded_date(note.meta.get("first_observed"), "first_observed", now, reasons)
    dates = [value for value in (recorded_last, evaluation.last_verified) if value is not None]
    last = max(dates) if dates else None
    level = evaluation.confidence if events else prior
    source = "reported_evidence" if events else "recorded_metadata" if prior is not None else "unknown"
    reasons.append(
        "Confidence recomputed from deduplicated reported outcomes; metadata and retrievals add no votes"
        if events else "No available outcome reports; historical metadata is retained, not converted into evidence"
    )
    if allowed and (note.status == "candidate" or note.meta.get("trust") not in ("first-party", "mixed")):
        level = "low"
        reasons.append("Low confidence cap: candidate admission or first-party/mixed trust is required")
    changes = allowed and evaluation.recent_behaviour_changes >= policy.behaviour_change_failures
    aging = allowed and confidence.decay_due(str(note.type), str(note.status), last, first, now.date())
    never_used = allowed and confidence.never_exercised_flag(confidence.FeedbackState(**raw), first, now.date())
    recent_failure = bool(evaluation.recent_failed_sessions)
    needs_review = allowed and (
        evaluation.needs_review or recent_failure or note.status == "stale"
        or aging or never_used or applicable.state == "mismatch"
    )
    if changes:
        reasons.append(
            f"{evaluation.recent_behaviour_changes} independent matched behaviour_changed sessions "
            f"in {policy.recent_days} days meet quarantine threshold {policy.behaviour_change_failures}"
        )
    elif recent_failure and allowed:
        reasons.append(
            f"{len(evaluation.recent_failed_sessions)} recent matched failure session(s) need investigation, "
            "not automatic invalidation"
        )
    if note.status == "stale" and allowed:
        reasons.append("Quarantined knowledge requires explicit review; later successes never auto-reactivate it")
    if aging:
        reasons.append("Legacy verification aging window exceeded; review separately from confidence decay")
    if never_used:
        reasons.append("Recorded episode exposures but no held/failed use for 90 days: review relevance")
    if applicable.state == "mismatch":
        reasons.append("Current applicability window does not match; exclude from trusted index sections")
    reasons.extend(applicable.reasons)
    if not allowed:
        level, source, last = prior, "execution_gated", recorded_last
        reasons.append("Reported feedback cannot change this profile or V2 admission authority")
    return KnowledgeAssessment(
        subject_id=note.ref, status=note.status, confidence=level, confidence_source=source,
        needs_review=bool(needs_review), possible_behaviour_change=bool(changes),
        aging_due=bool(aging), never_exercised=bool(never_used), maintenance_allowed=allowed,
        last_verified=last, feedback=MappingProxyType(raw), reasons=tuple(dict.fromkeys(reasons)),
        evidence=evaluation, applicability=applicable,
    )


def assess_all_knowledge(
    vault: Vault, *, now: datetime | date | None = None, events: Iterable[OutcomeEvent] | None = None,
    notes: Iterable[Note] | None = None, episodes: Iterable[Note] | None = None,
    diagnostics: list[str] | None = None,
) -> list[KnowledgeAssessment]:
    """Batch the same read-only policy used by maintenance and single-note explain.

    Precollected events include legacy episodes, not only journal records.
    Raw counters preserve unique reports; served counts distinct recorded
    episode sessions. Operational recall telemetry never affects confidence.
    """
    warnings: list[str] = []
    inventory = list(notes) if notes is not None else _read_notes(vault, config.KNOWLEDGE, warnings)
    inventory = [note for note in inventory if note.type in KNOWLEDGE_TYPES and not note.parse_error]
    episode_notes = list(episodes) if episodes is not None else None
    records = outcomes.collect_evidence(
        vault, diagnostics=warnings, episodes=episode_notes,
    ) if events is None else list(events)
    grouped = _knowledge_events(records)
    if episode_notes is None:
        episode_notes = _read_notes(vault, config.EPISODES, warnings)
    served = _served_counts(inventory, episode_notes, warnings)
    policy, mode, stamp = load_settings(vault).feedback, get_mode(vault), _now(now)
    result = [
        _assess_note(note, grouped.get(note.ref, []), served.get(note.ref), policy, stamp, mode)
        for note in sorted(inventory, key=lambda item: item.ref)
    ]
    if warnings:
        from dataclasses import replace

        result = [
            replace(item, reasons=(*item.reasons, *dict.fromkeys(warnings)))
            for item in result
        ]
    if diagnostics is not None:
        diagnostics.extend(warning for warning in dict.fromkeys(warnings) if warning not in diagnostics)
    return result


def assess_knowledge(
    vault: Vault, reference: str | Note, *, now: datetime | date | None = None,
    events: Iterable[OutcomeEvent] | None = None,
) -> KnowledgeAssessment:
    """Assess canonical knowledge without writes, using maintenance's exact policy."""
    warnings: list[str] = []
    notes = [note for note in _read_notes(vault, config.KNOWLEDGE, warnings) if note.type in KNOWLEDGE_TYPES]
    raw = vault.rel(fsutil.checked_regular_path(vault, reference.path)) if isinstance(reference, Note) else reference
    ref, error = _References(notes, config.KNOWLEDGE).resolve(raw)
    if ref is None:
        raise VaultError(f"cannot assess knowledge: {error}")
    for result in assess_all_knowledge(vault, now=now, events=events, notes=notes, diagnostics=warnings):
        if result.subject_id == ref:
            return result
    raise VaultError("cannot assess malformed knowledge")


@dataclass(frozen=True)
class NoteUsage:
    subject_id: str
    total: int
    last_30_days: int
    last_90_days: int
    last_recalled: str | None
    attempt_count: int
    legacy_count: int
    attempt_ids: tuple[str, ...]
    task_fingerprints: tuple[str | None, ...]

    @property
    def unknown_task_count(self) -> int:
        return sum(value is None for value in self.task_fingerprints)

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["attempt_ids"] = list(self.attempt_ids)
        result["task_fingerprints"] = list(self.task_fingerprints)
        result["unknown_task_count"] = self.unknown_task_count
        return result


@dataclass(frozen=True)
class UsageAnalytics:
    notes: tuple[NoteUsage, ...]
    mirrored_rows: int
    ignored_rows: int
    warnings: tuple[str, ...]

    @property
    def by_ref(self) -> dict[str, NoteUsage]:
        return {item.subject_id: item for item in self.notes}

    def as_dict(self) -> dict[str, object]:
        return {
            "notes": [item.as_dict() for item in self.notes], "mirrored_rows": self.mirrored_rows,
            "ignored_rows": self.ignored_rows, "warnings": list(self.warnings),
        }


def recall_usage(
    vault: Vault, *, now: datetime | date | None = None,
    attempts: Iterable[RecallAttempt] | None = None,
    notes: Iterable[Note] | None = None,
) -> UsageAnalytics:
    """30/90-day operational usage, subtracting exact TSV mirrors once per row.

    Unmatched old TSV rows remain independent observations. Ambiguous historical
    basenames are diagnosed, not guessed. Missing early task fingerprints stay
    None. Future clocks beyond configured tolerance contribute no usage.
    notes supplies an already-loaded knowledge inventory; an empty inventory
    disables its disk scan. Project/skill context references are still loaded.
    """
    stamp, policy = _now(now), load_settings(vault).feedback
    warnings: list[str] = []
    records: dict[str, RecallAttempt] = {}
    for attempt in read_attempts(vault, diagnostics=warnings) if attempts is None else attempts:
        old = records.get(attempt.attempt_id)
        if old is not None and old != attempt:
            raise VaultError("conflicting precollected recall attempt IDs")
        records[attempt.attempt_id] = attempt
    mirrors: Counter[tuple[str, str, str, str]] = Counter()
    observations: dict[str, list[tuple[datetime, RecallAttempt | None]]] = defaultdict(list)
    known: dict[str, set[str]] = defaultdict(set)
    domains: dict[str, set[str]] = defaultdict(set)
    inventory = list(notes) if notes is not None else None
    for folder in (config.KNOWLEDGE, config.PROJECTS, config.SKILLS):
        selected = inventory if folder == config.KNOWLEDGE and inventory is not None else _read_notes(vault, folder, warnings)
        for note in selected:
            if note.parse_error:
                warnings.append(f"{note.rel}: malformed frontmatter excluded from usage inventory")
                continue
            known[note.path.stem].add(note.ref)
            declared = note.meta.get("domains", [])
            if not isinstance(declared, list):
                warnings.append(f"{note.ref}: malformed domains excluded from legacy usage disambiguation")
            else:
                domains[note.ref].update(d for d in declared if isinstance(d, str))
    ignored = 0
    for attempt in sorted(records.values(), key=lambda item: (item.timestamp, item.attempt_id)):
        when = parse_timestamp(attempt.timestamp)
        for ref, domain in zip(attempt.note_refs, attempt.note_domains):
            mirrors[(when.isoformat(), attempt.tool, domain, ref.rsplit("/", 1)[-1])] += 1
            known[ref.rsplit("/", 1)[-1]].add(ref)
            domains[ref].add(domain)
            if when > stamp + timedelta(seconds=policy.future_tolerance_seconds):
                warnings.append(f"{attempt.attempt_id}: future recall excluded from usage")
                ignored += 1
            else:
                observations[ref].append((min(when, stamp), attempt))
    log_path = fsutil.checked_regular_path(vault, vault.path(config.RECALL_LOG))
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    except (OSError, UnicodeError):
        warnings.append(f"{config.RECALL_LOG}: telemetry could not be read; legacy usage is unavailable")
        lines = []
    mirrored = 0
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != 4:
            warnings.append(f"{config.RECALL_LOG}:{number}: expected four TSV columns")
            ignored += 1
            continue
        timestamp, tool, domain, name = (cell.strip() for cell in cells)
        try:
            when = parse_timestamp(timestamp)
        except VaultError:
            warnings.append(f"{config.RECALL_LOG}:{number}: invalid timestamp")
            ignored += 1
            continue
        key = (when.isoformat(), tool, domain, name)
        if mirrors[key]:
            mirrors[key] -= 1
            mirrored += 1
            continue
        if when > stamp + timedelta(seconds=policy.future_tolerance_seconds):
            warnings.append(f"{config.RECALL_LOG}:{number}: future recall excluded from usage")
            ignored += 1
            continue
        candidates = known.get(name.removesuffix(".md"), set())
        if len(candidates) > 1 and domain not in ("_general", "unclassified"):
            candidates = {ref for ref in candidates if domain in domains[ref]}
        if len(candidates) != 1:
            warnings.append(f"{config.RECALL_LOG}:{number}: ambiguous or unresolved legacy note reference")
            ignored += 1
            continue
        observations[next(iter(candidates))].append((min(when, stamp), None))
    result = []
    for ref, values in sorted(observations.items()):
        attempts_for_note = [item for _, item in values if item is not None]
        result.append(NoteUsage(
            subject_id=ref, total=len(values),
            last_30_days=sum(when >= stamp - timedelta(days=30) for when, _ in values),
            last_90_days=sum(when >= stamp - timedelta(days=90) for when, _ in values),
            last_recalled=max(when for when, _ in values).isoformat(),
            attempt_count=len(attempts_for_note), legacy_count=len(values) - len(attempts_for_note),
            attempt_ids=tuple(item.attempt_id for item in attempts_for_note),
            task_fingerprints=tuple(item.task_fingerprint for item in attempts_for_note),
        ))
    return UsageAnalytics(tuple(result), mirrored, ignored, tuple(dict.fromkeys(warnings)))


@dataclass(frozen=True)
class IndexSuggestion:
    subject_id: str
    domain: str
    action: str
    section: str
    reasons: tuple[str, ...]
    usage: NoteUsage

    def as_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id, "domain": self.domain, "action": self.action,
            "section": self.section, "reasons": list(self.reasons), "usage": self.usage.as_dict(),
        }


def index_suggestions(
    vault: Vault, *, now: datetime | date | None = None, usage: UsageAnalytics | None = None,
    assessments: Iterable[KnowledgeAssessment] | None = None,
    notes: Iterable[Note] | None = None,
) -> list[IndexSuggestion]:
    """Review-only recommendations; telemetry never changes trust or confidence.

    notes reuses a loaded knowledge inventory, including for any uncached usage
    or assessment work. Supply assessments as well to reuse its evidence pass.
    """
    stamp, policy = _now(now), load_settings(vault).feedback
    inventory = list(notes) if notes is not None else None
    usage = recall_usage(vault, now=stamp, notes=inventory) if usage is None else usage
    health = {
        item.subject_id: item for item in (
            assess_all_knowledge(vault, now=stamp, notes=inventory) if assessments is None else assessments
        )
    }
    by_ref = usage.by_ref
    domain_indexes = {index.domain: index for index in indexes.list_domain_indexes(vault)}
    result = []
    for note in inventory if inventory is not None else _read_notes(vault, config.KNOWLEDGE, []):
        assessment, counted = health.get(note.ref), by_ref.get(note.ref)
        if (
            assessment is None or counted is None or not assessment.maintenance_allowed
            or assessment.needs_review or note.status != "validated"
            or note.meta.get("trust") not in ("first-party", "mixed")
        ):
            continue
        for domain in note.meta.get("domains", []):
            index = domain_indexes.get(domain)
            if index is None:
                continue
            section_name = {"failure": "Known failures", "workaround": "Current workarounds"}.get(note.type, "Read first")
            if not indexes.eligible_for_section(note, section_name, now=stamp):
                continue
            linked = any(section in indexes.LINK_SECTIONS for section, _ in index.find(note.ref))
            if not linked and assessment.confidence in ("medium", "high") and counted.last_30_days >= policy.usage_promote_count:
                result.append(IndexSuggestion(note.ref, domain, "promote", section_name, (
                    f"{counted.last_30_days} recorded recalls in 30 days meet promotion threshold {policy.usage_promote_count}",
                    "Validated, trusted, currently applicable knowledge; placement still requires human review",
                    "Usage is operational attention, never evidence of correctness",
                ), counted))
            elif linked and counted.last_recalled is not None:
                age = (stamp - parse_timestamp(counted.last_recalled)).total_seconds() / 86400
                if age >= policy.usage_demote_days:
                    result.append(IndexSuggestion(note.ref, domain, "demote", "Recently changed", (
                        f"Last recorded recall is at least the {policy.usage_demote_days}-day demotion threshold",
                        "Review index space; low usage does not invalidate knowledge or reduce confidence",
                    ), counted))
    return sorted(result, key=lambda item: (item.domain, item.action, item.subject_id))
