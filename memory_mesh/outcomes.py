"""Immutable, reported feedback shared by capture, episodes and diagnostics.

Each event is a Markdown record named by the SHA-256 of its opaque ID. A
completed staging file is published with a no-replace hard link: retries can
read the winner, but cannot overwrite it. Unsupported filesystems fail closed.
These reports never establish that a tool ran or that a V2 check passed.
"""

from __future__ import annotations

import hashlib
import os
import re
import time as clock
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timezone
from pathlib import Path

from . import config, frontmatter, fsutil, redact
from .config import Vault, VaultError
from .experience_types import digest, require_id, require_text
from .feedback_config import FeedbackPolicy, load_settings
from .notes import Note, load_note, resolve_ref
from .outcome_types import (
    CONTEXT_FIELDS, FAILURE_REASONS, SUBJECT_OUTCOMES,
    OutcomeEvent, event_from_dict, parse_timestamp,
)

_MAX_EVENT_BYTES = 64 * 1024
_KNOWLEDGE_TYPES = {"pattern", "tool-behaviour", "workaround", "failure", "reference"}


class OutcomeError(VaultError):
    """Invalid, unresolved or conflicting feedback; messages omit payloads."""


class OutcomeIdentityConflict(OutcomeError):
    """An immutable event ID already belongs to a different intent."""


def _safe_path(vault: Vault, path: Path) -> Path:
    try:
        resolved = path.resolve()
        # Windows can retain the extended-path prefix when a concurrent create
        # changes the result of pathlib's non-strict resolution.
        if os.name == "nt":
            text = str(resolved)
            if text.startswith("\\\\?\\UNC\\"):
                resolved = Path("\\\\" + text[8:])
            elif text.startswith("\\\\?\\"):
                resolved = Path(text[4:])
        resolved.relative_to(vault.root)
        if resolved != path:
            raise OutcomeError("outcome paths must not redirect through links")
        for component in (path, *path.parents):
            if component == vault.root:
                break
            if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
                raise OutcomeError("outcome paths must not redirect through links")
        return resolved
    except (ValueError, OSError, RuntimeError):
        raise OutcomeError("outcome path is outside the vault or unsafe") from None


def _identity(vault: Vault, value: str, name: str) -> str:
    value = require_id(value, name)
    if redact.scan(value, vault):
        raise OutcomeError(f"{name} must not contain sensitive information")
    return value


def _text(vault: Vault, value: str, name: str, limit: int, *, empty: bool = False) -> str:
    if empty and value == "":
        return ""
    value = require_text(value, name, limit)
    return require_text(redact.redact(value, vault)[0], name, limit)


def _reference(vault: Vault | None, value: str) -> tuple[str, bool]:
    value = require_text(value, "subject_id", 300)
    if redact.scan(value, vault):
        raise OutcomeError("subject_id must not contain sensitive information")
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    value = value.replace("\\", "/")
    if (
        not value or value.startswith("/") or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
        or any(char in value for char in "[]#|")
    ):
        raise OutcomeError("subject reference must be a safe vault-relative path or slug")
    explicit_file = value.lower().endswith(".md")
    return (value[:-3] if explicit_file else value), explicit_file


class _SubjectResolver:
    """Cache only filenames and resolved references, never whole note bodies."""

    def __init__(self, vault: Vault):
        self.vault = vault
        self.indexes: dict[str, dict[str, list[Path]]] = {}
        self.resolved: dict[tuple[str, str], str] = {}
        self.context_references: dict[str, bool] = {}

    def is_context_reference(self, reference: str) -> bool:
        """Legacy project/index references are context, not knowledge votes."""
        if reference not in self.context_references:
            path = resolve_ref(self.vault, reference)
            context_only = False
            if path is not None:
                note = load_note(path, self.vault)
                if note.parse_error:
                    raise OutcomeError("legacy context reference has malformed metadata")
                relative = self.vault.rel(path)
                canonical_tier = relative.startswith(config.KNOWLEDGE + "/") and not relative.startswith(config.INDEX_DIR + "/")
                context_only = not canonical_tier and note.type not in _KNOWLEDGE_TYPES
            self.context_references[reference] = context_only
        return self.context_references[reference]

    def resolve(self, subject_type: str, reference: str) -> str:
        if subject_type not in ("knowledge", "skill"):
            raise OutcomeError("only knowledge and skill references resolve to notes")
        ref, explicit_file = _reference(self.vault, reference)
        key = (subject_type, reference)
        if key in self.resolved:
            return self.resolved[key]
        root = config.KNOWLEDGE if subject_type == "knowledge" else config.SKILLS
        base = _safe_path(self.vault, self.vault.path(root))
        if "/" in ref:
            if not ref.startswith(root + "/"):
                raise OutcomeError("subject reference points outside its canonical tier")
            direct = _safe_path(self.vault, self.vault.path(ref + ".md"))
            candidates = [direct]
            if subject_type == "skill" and not explicit_file and not direct.is_file():
                candidates.append(self.vault.path(ref) / "SKILL.md")
        else:
            if subject_type not in self.indexes:
                index: dict[str, list[Path]] = {}
                if base.is_dir():
                    for path in sorted(base.rglob("*.md")):
                        if subject_type == "knowledge" and "_index" in path.relative_to(base).parts:
                            continue
                        index.setdefault(path.stem.casefold(), []).append(path)
                        if subject_type == "skill" and path.name == "SKILL.md":
                            index.setdefault(path.parent.name.casefold(), []).append(path)
                self.indexes[subject_type] = index
            candidates = self.indexes[subject_type].get(ref.casefold(), [])
        matches: list[Path] = []
        for candidate in dict.fromkeys(candidates):
            path = _safe_path(self.vault, candidate)
            if not path.is_file():
                continue
            if not path.is_relative_to(base) or (
                subject_type == "knowledge" and "_index" in path.relative_to(base).parts
            ):
                raise OutcomeError("subject reference points outside its canonical tier")
            matches.append(path)
        if not matches:
            raise OutcomeError(f"unresolved {subject_type} reference")
        if len(matches) != 1:
            raise OutcomeError(f"ambiguous {subject_type} reference; use a full file reference")
        note = load_note(matches[0], self.vault)
        valid = note.type in _KNOWLEDGE_TYPES if subject_type == "knowledge" else (
            note.type == "skill" or note.path.name == "SKILL.md"
        )
        if note.parse_error or not valid:
            raise OutcomeError(f"subject is not a valid {subject_type} note")
        canonical = note.ref
        if redact.scan(canonical, self.vault):
            raise OutcomeError("canonical subject reference contains sensitive information")
        self.resolved[key] = canonical
        return canonical


def canonical_subject_ref(vault: Vault, subject_type: str, reference: str) -> str:
    """Resolve one unambiguous knowledge/skill reference, without mutation."""
    return _SubjectResolver(vault).resolve(subject_type, reference)


def _check_future(timestamp: str, tolerance: int) -> None:
    if (parse_timestamp(timestamp) - datetime.now(timezone.utc)).total_seconds() > tolerance:
        raise OutcomeError("outcome timestamp is too far in the future")


def _event_path(vault: Vault, event_id: str) -> Path:
    name = hashlib.sha256(event_id.encode("utf-8")).hexdigest() + ".md"
    return _safe_path(vault, vault.path(config.OUTCOME_EVENTS) / name)


def _unique_frontmatter(text: str) -> None:
    """The general YAML-subset reader tolerates duplicate keys; a journal cannot."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise OutcomeError("outcome record requires YAML frontmatter")
    seen: dict[int, set[str]] = {}
    for line in lines[1:]:
        if line == "---":
            return
        match = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_.-]*)\s*:(.*)$", line)
        if not match:
            continue
        indent, key, value = len(match[1]), match[2], match[3].strip()
        for depth in list(seen):
            if depth > indent:
                del seen[depth]
        if key in seen.setdefault(indent, set()):
            raise OutcomeError("outcome record contains duplicate frontmatter keys")
        seen[indent].add(key)
        if key == "context" and value.startswith("{") and value.endswith("}"):
            keys = [
                item.split(":", 1)[0].strip().strip("\"'")
                for item in frontmatter._split_inline(value[1:-1])
            ]
            if len(set(keys)) != len(keys):
                raise OutcomeError("outcome context contains duplicate keys")
    raise OutcomeError("outcome record has incomplete frontmatter")


def _parse_event_note(note: Note, tolerance: int) -> OutcomeEvent:
    if note.parse_error or not isinstance(note.meta, dict) or not isinstance(note.body, str):
        raise OutcomeError("outcome record is malformed")
    if note.type != "outcome":
        raise OutcomeError("outcome record requires type outcome")
    text = frontmatter.compose(note.meta, note.body)
    if len(text.encode("utf-8")) > _MAX_EVENT_BYTES:
        raise OutcomeError("outcome record exceeds 64 KiB")
    if redact.scan(text, note.vault):
        raise OutcomeError("outcome record contains unredacted sensitive information")
    event = event_from_dict({key: value for key, value in note.meta.items() if key != "type"})
    _check_future(event.timestamp, tolerance)
    expected_name = hashlib.sha256(event.event_id.encode("utf-8")).hexdigest() + ".md"
    if note.path.name != expected_name:
        raise OutcomeError("outcome filename does not match its event ID")
    if note.vault is not None:
        if _safe_path(note.vault, note.path) != _event_path(note.vault, event.event_id):
            raise OutcomeError("outcome filename does not match its event ID")
    if event.subject_type in ("knowledge", "skill"):
        ref, explicit_file = _reference(note.vault, event.subject_id)
        root = config.KNOWLEDGE if event.subject_type == "knowledge" else config.SKILLS
        if (
            explicit_file or ref != event.subject_id or not ref.startswith(root + "/")
            or (event.subject_type == "knowledge" and "_index" in ref.split("/"))
        ):
            raise OutcomeError("stored outcome subject must be a canonical reference")
    return event


def parse_event_note(note: Note) -> OutcomeEvent:
    """Validate the persisted envelope used by both schema and journal readers.

    Metadata is exactly ``{"type": "outcome", **event.as_dict()}``; only
    ``type`` is an envelope field, and additional envelope keys are rejected.
    Optional event fields retain ``event_from_dict`` defaults. This validates
    the parsed snapshot without opening its path, resolving subjects or scanning
    journals. Vault-bound snapshots use configured redaction and clock policy;
    unbound snapshots use built-in redaction and the default clock tolerance.
    Raw encoding and duplicate-key checks remain at the file-reading boundary.
    """
    tolerance = (
        load_settings(note.vault).feedback.future_tolerance_seconds
        if note.vault is not None else FeedbackPolicy().future_tolerance_seconds
    )
    return _parse_event_note(note, tolerance)


def _read_event(vault: Vault, path: Path, tolerance: int) -> OutcomeEvent:
    path = _safe_path(vault, path)
    try:
        deadline = clock.monotonic() + 1.0
        while True:
            try:
                raw = fsutil.read_regular_bytes(_safe_path(vault, path), max_bytes=_MAX_EVENT_BYTES)
                break
            except fsutil.PathTraversalError:
                if clock.monotonic() >= deadline:
                    raise OutcomeError("outcome record has persistent hard links; inspect publication state") from None
                clock.sleep(0.01)
        text = raw.decode("utf-8")
        _unique_frontmatter(text)
        meta, body = frontmatter.parse(text)
        if redact.scan(text, vault):
            raise OutcomeError("outcome record contains unredacted sensitive information")
        return _parse_event_note(Note(path, meta, body, vault), tolerance)
    except (OSError, UnicodeError, frontmatter.FrontmatterError, fsutil.WriteBoundaryError):
        raise OutcomeError("outcome record is unreadable or malformed") from None


def record_outcome(
    vault: Vault, *, session_id: str, subject_type: str, subject_id: str,
    outcome: str, reason: str | None = None, domain: str = "",
    context: Mapping[str, str] | None = None, source: str = "cli",
    detail: str = "", event_id: str | None = None, now: datetime | None = None,
) -> OutcomeEvent:
    """Capture one reported intent. Retries replay it; explicit IDs identify trials.

    IDs and canonical references containing sensitive data are rejected rather
    than redacted into colliding identities. Report text is redacted before
    intent hashing or writing. A different retry timestamp does not change an ID.
    """
    session_id = _identity(vault, session_id, "session_id")
    if not isinstance(subject_type, str) or subject_type not in SUBJECT_OUTCOMES:
        raise OutcomeError("unknown outcome subject_type")
    if outcome in ("#held", "#failed", "#unclear"):
        outcome = outcome[1:]
    if not isinstance(outcome, str) or outcome not in SUBJECT_OUTCOMES[subject_type]:
        raise OutcomeError("invalid outcome for subject_type")
    if reason is not None and (reason not in FAILURE_REASONS or outcome != "failed"):
        raise OutcomeError("invalid failure reason for outcome")
    if not isinstance(domain, str):
        raise OutcomeError("outcome domain must be text")
    if domain:
        domain = _identity(vault, domain, "domain")
    if subject_type in ("knowledge", "skill"):
        subject_id = canonical_subject_ref(vault, subject_type, subject_id)
    else:
        subject_id = _text(vault, subject_id, "subject_id", 300)
    if context is not None and not isinstance(context, Mapping):
        raise OutcomeError("outcome context must be a mapping")
    clean_context: dict[str, str] = {}
    for key, value in (context if context is not None else {}).items():
        if key not in CONTEXT_FIELDS:
            raise OutcomeError("unknown outcome context field")
        clean_context[key] = _text(vault, value, "context value", 250)
    if now is not None and not isinstance(now, datetime):
        raise OutcomeError("outcome timestamp must be a datetime with timezone")
    stamp = (now if now is not None else datetime.now(timezone.utc)).isoformat()
    event = OutcomeEvent(
        event_id=_identity(vault, event_id, "event_id") if event_id is not None else "pending",
        timestamp=stamp, session_id=session_id, subject_type=subject_type,
        subject_id=subject_id, outcome=outcome, reason=reason, domain=domain,
        context=clean_context, source=_text(vault, source, "source", 300),
        detail=_text(vault, detail, "detail", 1000, empty=True),
    )
    if event_id is None:
        event = event_from_dict({**event.as_dict(), "event_id": "outcome-" + digest(event.intent())})
    tolerance = load_settings(vault).feedback.future_tolerance_seconds
    _check_future(event.timestamp, tolerance)
    path = _event_path(vault, event.event_id)

    def replay() -> OutcomeEvent:
        existing = _read_event(vault, path, tolerance)
        if existing.intent() != event.intent():
            raise OutcomeIdentityConflict("outcome event ID conflicts with a different intent")
        return existing

    if path.exists():
        return replay()
    text = frontmatter.compose(
        {"type": "outcome", **event.as_dict()},
        "# Reported outcome\n\nReported feedback, not a verified execution receipt.\n",
    )
    if redact.scan(text, vault):
        raise OutcomeError("serialized outcome contains sensitive information")
    if len(text.encode("utf-8")) > _MAX_EVENT_BYTES:
        raise OutcomeError("outcome record exceeds 64 KiB")
    stage = _safe_path(vault, path.parent / f".outcome-{uuid.uuid4().hex}.pending")
    created_stage = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _safe_path(vault, path.parent)
        with stage.open("x", encoding="utf-8", newline="\n") as stream:
            created_stage = True
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(stage, _safe_path(vault, path))
        except FileExistsError:
            return replay()
        stage.unlink()
        created_stage = False
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return event
    except OSError:
        raise OutcomeError("could not atomically publish outcome; existing history was not replaced") from None
    finally:
        if created_stage:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                raise OutcomeError("outcome staging cleanup failed; the event may already be present") from None


def read_events(
    vault: Vault, *, session_id: str | None = None,
    subject_type: str | None = None, subject_id: str | None = None,
) -> list[OutcomeEvent]:
    """Read validated journal records in timestamp/ID order; never silently skip corruption."""
    if session_id is not None:
        session_id = _identity(vault, session_id, "session_id")
    if subject_type is not None and (
        not isinstance(subject_type, str) or subject_type not in SUBJECT_OUTCOMES
    ):
        raise OutcomeError("unknown outcome subject_type filter")
    subjects: set[str] | None = None
    if subject_id is not None:
        subjects = {require_text(subject_id, "subject_id", 300)}
        resolver = _SubjectResolver(vault)
        if subject_type in ("knowledge", "skill"):
            subjects = {resolver.resolve(subject_type, subject_id)}
        elif subject_type is None:
            for kind in ("knowledge", "skill"):
                try:
                    subjects.add(resolver.resolve(kind, subject_id))
                except OutcomeError as exc:
                    if "ambiguous" in str(exc):
                        raise
    base = _safe_path(vault, vault.path(config.OUTCOME_EVENTS))
    if not base.exists():
        return []
    if not base.is_dir():
        raise OutcomeError("outcome journal must be a directory")
    tolerance = load_settings(vault).feedback.future_tolerance_seconds
    events: dict[str, OutcomeEvent] = {}
    for path in sorted(base.glob("*.md")):
        event = _read_event(vault, path, tolerance)
        previous = events.get(event.event_id)
        if previous is not None and previous != event:
            raise OutcomeError("conflicting duplicate outcome event ID")
        events[event.event_id] = event
    return sorted(
        (
            event for event in events.values()
            if (session_id is None or event.session_id == session_id)
            and (subject_type is None or event.subject_type == subject_type)
            and (subjects is None or event.subject_id in subjects)
        ),
        key=lambda event: (event.timestamp, event.event_id),
    )


def _legacy_timestamp(note: Note, tolerance: int) -> str:
    captured = note.meta.get("captured")
    if captured is None:
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", note.path.name)
        captured = match[1] if match else None
    if isinstance(captured, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured):
        try:
            captured = datetime.combine(date.fromisoformat(captured), time(), timezone.utc).isoformat()
        except ValueError:
            raise OutcomeError("legacy episode has an invalid captured date") from None
    timestamp = parse_timestamp(captured).isoformat()
    _check_future(timestamp, tolerance)
    return timestamp


def _legacy_context(vault: Vault, note: Note) -> dict[str, str]:
    context = note.meta.get("context", {})
    if not isinstance(context, dict):
        raise OutcomeError("legacy episode context must be a mapping")
    result = {}
    for field in CONTEXT_FIELDS:
        value = context.get(field, note.meta.get(field))
        if value is not None and value != "":
            result[field] = _text(vault, value, "episode context", 250)
    return result


def _episode_events(
    vault: Vault, note: Note, journal: dict[str, OutcomeEvent],
    resolver: _SubjectResolver, tolerance: int, diagnostics: list[str] | None = None,
) -> list[OutcomeEvent]:
    from .episodes import parse_episode

    ep = parse_episode(note)
    if ep.parse_errors:
        if diagnostics is not None and not note.meta.get("outcome_events") and "outcome-event:" not in note.body:
            diagnostics.append(f"{note.ref}: unattributed legacy feedback excluded; original episode retained")
            return []
        raise OutcomeError("episode contains malformed outcome bullets")
    references = note.meta.get("outcome_events", [])
    if not isinstance(references, list) or any(not isinstance(ref, str) for ref in references):
        raise OutcomeError("episode outcome_events must be a list of event IDs")
    uses = [("knowledge", use) for use in ep.used] + [("skill", use) for use in ep.skill_outcomes]
    references = list(dict.fromkeys([*references, *(use.event_id for _, use in uses if use.event_id)]))
    projected: dict[str, OutcomeEvent] = {}
    for ref in references:
        _identity(vault, ref, "event_id")
        event = journal.get(ref)
        if event is None:
            raise OutcomeError("episode projection references a missing outcome event")
        if note.meta.get("session_id") not in (None, event.session_id):
            raise OutcomeError("episode projection references another session's outcome")
        projected[ref] = event
    pending: list[tuple[str, str, str, str | None, str]] = []
    for subject_type, use in uses:
        ref, _ = _reference(vault, use.ref)
        if use.outcome not in SUBJECT_OUTCOMES[subject_type]:
            raise OutcomeError("episode contains an invalid outcome")
        reason = (use.failure_reason or "unknown") if use.outcome == "failed" else None
        if use.failure_reason and use.outcome != "failed":
            raise OutcomeError("episode failure reasons require a failed outcome")
        if reason is not None and reason not in FAILURE_REASONS:
            raise OutcomeError("episode contains an unknown failure reason")
        known_subjects = {
            event.subject_id for event in projected.values() if event.subject_type == subject_type
        }
        # A projection already has a canonical identity. Its historical report
        # remains readable even if the referenced note has since disappeared.
        try:
            subject = ref if ref in known_subjects else resolver.resolve(subject_type, use.ref)
        except OutcomeError:
            if subject_type == "knowledge" and not use.event_id and resolver.is_context_reference(ref):
                continue
            raise
        if use.event_id:
            event = projected[use.event_id]
            if (event.subject_type, event.subject_id, event.outcome, event.reason) != (
                subject_type, subject, use.outcome, reason,
            ):
                raise OutcomeError("episode projection conflicts with its immutable outcome event")
            continue
        if any(
            (event.subject_type, event.subject_id, event.outcome) == (subject_type, subject, use.outcome)
            for event in projected.values()
        ):
            continue
        pending.append((subject_type, subject, use.outcome, reason, use.reason))
    quality = ep.recall_quality
    if quality is not None:
        if not isinstance(quality, str) or quality not in SUBJECT_OUTCOMES["recall"]:
            raise OutcomeError("episode contains invalid recall_quality")
        if not any(event.subject_type == "recall" and event.outcome == quality for event in projected.values()):
            pending.append(("recall", _text(vault, note.ref, "recall subject", 300), quality, None, ""))
    result = dict(projected)
    if not pending:
        return list(result.values())
    timestamp = _legacy_timestamp(note, tolerance)
    source = _text(vault, f"episode:{note.ref}", "source", 300)
    session_id = note.meta.get("session_id") or "legacy-" + digest(note.ref)
    session_id = _identity(vault, session_id, "session_id")
    domains = note.meta.get("domains") or []
    if not isinstance(domains, list) or any(not isinstance(domain, str) for domain in domains):
        raise OutcomeError("episode domains must be a list of identifiers")
    domain = _identity(vault, domains[0], "domain") if domains else ""
    context = _legacy_context(vault, note)
    for kind, subject, outcome, reason, detail in pending:
        detail = _text(vault, detail, "episode outcome detail", 1000, empty=True)
        identity = {"episode": note.ref, "subject_type": kind, "subject_id": subject,
                    "outcome": outcome, "reason": reason, "detail": detail}
        event = OutcomeEvent(
            event_id="legacy-" + digest(identity), timestamp=timestamp,
            session_id=session_id, subject_type=kind, subject_id=subject,
            outcome=outcome, reason=reason, domain=domain, context=context,
            source=source, detail=detail,
        )
        result[event.event_id] = event
    return list(result.values())


def episode_events(vault: Vault, note: Note) -> list[OutcomeEvent]:
    """Validate and interpret available episode evidence without writing it.

    Projections refer to immutable journal IDs. Date-only legacy captures use
    midnight UTC; absent dates may use the dated filename, never today's date.
    """
    return _episode_events(
        vault, note, {event.event_id: event for event in read_events(vault)},
        _SubjectResolver(vault), load_settings(vault).feedback.future_tolerance_seconds,
    )


def collect_evidence(
    vault: Vault, *, diagnostics: list[str] | None = None,
    episodes: Iterable[Note] | None = None,
) -> list[OutcomeEvent]:
    """Merge journal reports and dated, finished legacy episodes exactly once.

    Duplicate bullets within one episode collapse after canonical resolution.
    Independent episodes remain independent. Projections never create new trials.
    An explicit diagnostic sink permits quarantining malformed legacy feedback;
    journal/projection corruption still fails rather than supplying partial votes.
    """
    events = {event.event_id: event for event in read_events(vault)}
    journal = dict(events)
    resolver = _SubjectResolver(vault)
    tolerance = load_settings(vault).feedback.future_tolerance_seconds
    base = _safe_path(vault, vault.path(config.EPISODES))
    if not base.is_dir():
        return sorted(events.values(), key=lambda event: (event.timestamp, event.event_id))
    excluded = {"_outcomes", "_recalls", "_summaries", "_unreviewed"}
    if episodes is None:
        source = (
            load_note(_safe_path(vault, path), vault)
            for path in sorted(base.rglob("*.md"))
            if not any(part in excluded for part in path.relative_to(base).parts)
        )
    else:
        source = episodes
    for note in source:
        if not isinstance(note, Note) or note.vault is None or note.vault.root != vault.root:
            raise OutcomeError("preloaded episodes must belong to the current vault")
        path = _safe_path(vault, note.path)
        if not path.is_relative_to(base):
            raise OutcomeError("preloaded episode is outside the episode directory")
        if any(part in excluded for part in path.relative_to(base).parts):
            continue
        if note.type != "episode" or note.status not in ("summarised", "mined"):
            continue
        for event in _episode_events(vault, note, journal, resolver, tolerance, diagnostics):
            previous = events.get(event.event_id)
            if previous is not None and previous != event:
                raise OutcomeError("conflicting episode and journal outcome event IDs")
            events[event.event_id] = event
    return sorted(events.values(), key=lambda event: (event.timestamp, event.event_id))
