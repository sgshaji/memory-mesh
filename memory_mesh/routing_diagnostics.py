"""Reported recall telemetry and research needs, never factual admission.

Same session/task/result intent is recorded once, even across hook retries.
An explicit attempt ID identifies an independent trial; reuse it on retries.
Without a session or explicit ID, each invocation is an independent attempt.
Readers scan only telemetry/episodes, never canonical knowledge or indexes.

``total_count`` counts distinct links in the bounded selected index sections;
``usable_count`` counts the notes actually served after admission and budgets.
The full redacted task is fingerprinted before its display text is truncated.
The four-column TSV remains a disposable mirror: if a crash loses some rows,
the immutable attempt still supplies their identity and counts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

from . import config, frontmatter, fsutil, redact, router
from .config import Vault, VaultError
from .experience_types import require_id
from .feedback_config import load_settings
from .notes import Note, load_note, section
from .outcome_types import OutcomeEvent, parse_timestamp

if TYPE_CHECKING:
    from .recall import RecallResult

ATTEMPT_VERSION = 1
MAX_RECORD_BYTES = 32_768
MAX_TASK_TEXT = 500
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")
_QUALITIES = ("useful", "partial", "missed", "off-target")
_EPISODE_SECTIONS = ("What happened", "Candidate learnings", "Knowledge used")


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _clean(vault: Vault, text: str, limit: int | None) -> tuple[str, bool]:
    if not isinstance(text, str):
        raise VaultError("capture text must be a string")
    clean, findings = redact.redact(text, vault)
    return " ".join(clean.split())[:limit], bool(findings)


def _text(value: object, label: str, limit: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str) or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(char) < 32 for char in value)
    ):
        raise VaultError(f"recall attempt {label} requires bounded single-line text")
    return value


def _ref(value: object) -> str:
    text = _text(value, "note reference", 300)
    parts = text.split("/")
    if (
        not text.startswith(("knowledge/", "projects/", "skills/", "episodes/"))
        or any(part in ("", ".", "..") for part in parts)
        or any(char in text for char in "\\:[]#|")
        or text.endswith(".md")
    ):
        raise VaultError("recall note reference must be a full vault-relative reference without .md")
    return text


@dataclass(frozen=True)
class RecallAttempt:
    attempt_id: str
    timestamp: str
    session_id: str
    task_text: str
    task_fingerprint: str | None
    route: str
    domains: tuple[str, ...]
    note_refs: tuple[str, ...]
    total_count: int
    usable_count: int
    target_minimum: int
    potential_gap: bool
    tool: str = "cli"
    mode: str = "legacy"
    task_id: str | None = None
    task_revision: int | None = None
    abstention: str | None = None
    note_domains: tuple[str, ...] = ()
    note_revisions: tuple[str, ...] = ()
    sensitivity: str = "checked"
    schema_version: int = ATTEMPT_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != ATTEMPT_VERSION:
            raise VaultError("unsupported recall attempt schema_version")
        require_id(self.attempt_id, "attempt_id")
        require_id(self.session_id, "session_id")
        if self.task_id is not None:
            require_id(self.task_id, "task_id")
        if self.task_revision is not None and (
            self.task_id is None or type(self.task_revision) is not int or self.task_revision < 1
        ):
            raise VaultError("recall attempt task_revision requires an identified task and positive revision")
        object.__setattr__(self, "timestamp", parse_timestamp(self.timestamp).isoformat())
        _text(self.task_text, "task_text", MAX_TASK_TEXT, empty=True)
        if self.task_fingerprint is not None and (
            not isinstance(self.task_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.task_fingerprint)
        ):
            raise VaultError("recall attempt task_fingerprint requires a SHA-256 digest")
        _text(self.tool, "tool", 100)
        for key in ("domains", "note_refs", "note_domains", "note_revisions"):
            value = getattr(self, key)
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
                raise VaultError(f"recall attempt {key} must be a list of strings")
            object.__setattr__(self, key, tuple(value))
        if (
            not 1 <= len(self.domains) <= 2 or len(set(self.domains)) != len(self.domains)
            or any(not _DOMAIN.fullmatch(domain) for domain in self.domains)
            or ("unclassified" in self.domains and len(self.domains) != 1)
        ):
            raise VaultError("recall attempt requires one or two unique routing domains")
        if self.route != "+".join(self.domains):
            raise VaultError("recall attempt route must match its ordered domains")
        for key in ("total_count", "usable_count", "target_minimum"):
            if type(getattr(self, key)) is not int:
                raise VaultError(f"recall attempt {key} must be an integer")
        if not 0 <= self.usable_count <= min(self.total_count, config.RECALL_MAX_NOTES):
            raise VaultError("recall attempt has inconsistent note counts")
        if not 0 <= self.total_count <= 10_000 or not 1 <= self.target_minimum <= config.RECALL_MAX_NOTES:
            raise VaultError("recall attempt note counts are outside supported bounds")
        if (
            len(self.note_refs) != self.usable_count
            or len(set(self.note_refs)) != len(self.note_refs)
            or len(self.note_domains) != self.usable_count
            or len(self.note_revisions) != self.usable_count
        ):
            raise VaultError("recall attempt note metadata must match its usable count")
        for ref in self.note_refs:
            _ref(ref)
        if any(domain != "_general" and not _DOMAIN.fullmatch(domain) for domain in self.note_domains):
            raise VaultError("recall attempt has an invalid note domain")
        if any(not re.fullmatch(r"[0-9a-f]{64}", revision) for revision in self.note_revisions):
            raise VaultError("recall attempt has an invalid note revision")
        if self.mode not in ("legacy", "strict", "shadow", "off"):
            raise VaultError("recall attempt has an invalid mode")
        if self.abstention is not None:
            _text(self.abstention, "abstention", 100)
        expected_gap = (
            self.usable_count < self.target_minimum
            and self.mode not in ("off", "shadow")
            and self.abstention != "missing_task_context"
        )
        if type(self.potential_gap) is not bool or self.potential_gap != expected_gap:
            raise VaultError("recall attempt potential_gap disagrees with its result")
        if self.sensitivity not in ("checked", "redacted"):
            raise VaultError("recall attempt sensitivity must be checked or redacted")

    def as_dict(self) -> dict:
        data = {item.name: getattr(self, item.name) for item in fields(self)}
        for name in ("domains", "note_refs", "note_domains", "note_revisions"):
            data[name] = list(data[name])
        return data

    def intent(self) -> dict:
        return {
            key: value for key, value in self.as_dict().items()
            if key not in ("attempt_id", "timestamp", "sensitivity")
        }


def parse_attempt_note(note: Note) -> RecallAttempt:
    """Shared persisted-envelope validator for telemetry readers and schema lint."""
    if note.parse_error or note.type != "recall-attempt":
        raise VaultError("invalid recall-attempt Markdown envelope")
    data = {key: value for key, value in note.meta.items() if key != "type"}
    allowed = {item.name for item in fields(RecallAttempt)}
    required = {
        "schema_version", "attempt_id", "timestamp", "session_id", "task_text",
        "route", "domains", "note_refs", "total_count", "usable_count",
        "target_minimum", "potential_gap", "note_domains", "note_revisions",
    }
    if required - data.keys() or data.keys() - allowed:
        raise VaultError("recall attempt has missing or unknown metadata fields")
    # Early v1 records retained only bounded display text, not the full-task hash.
    data.setdefault("task_fingerprint", None)
    return RecallAttempt(**data)


def _write_once(vault: Vault, path: Path, text: str) -> bool:
    """Publish a complete agent-owned file without replacing a competing writer."""
    fsutil.ensure_within(vault, path)
    staging = path.with_name(f".mm-recall-{uuid.uuid4().hex}.md")
    try:
        staged = fsutil.agent_write(vault, staging, text)
        try:
            os.link(staged, path)
        except FileExistsError:
            return False
        return True
    finally:
        staging.unlink(missing_ok=True)


def _read_note(vault: Vault, path: Path) -> Note:
    try:
        path = fsutil.checked_regular_path(vault, path)
    except (fsutil.PathTraversalError, fsutil.WriteBoundaryError) as exc:
        raise VaultError("telemetry cannot be read through redirected paths") from exc
    if not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
        raise VaultError("telemetry requires a bounded regular file inside the vault")
    return load_note(path, vault)


def _safe_directory(vault: Vault, path: Path) -> bool:
    try:
        fsutil.ensure_within(vault, path)
    except fsutil.PathTraversalError:
        return False
    return path.is_dir() and not any(
        fsutil.is_link(component) for component in (path, *path.parents)
        if component.is_relative_to(vault.root)
    )


def record_attempt(
    vault: Vault, task_text: str, result: RecallResult, *, tool: str = "cli",
    session_id: str | None = None, task_id: str | None = None,
    attempt_id: str | None = None, now: datetime | None = None,
) -> tuple[RecallAttempt, bool]:
    """Persist exactly one result; returns (attempt, newly_created).

    This performs exact-path reads only. It never scans previous recalls or
    knowledge. The caller writes legacy TSV rows only for newly created records.
    """
    clean, redacted = _clean(vault, task_text, None)
    clean_tool, tool_redacted = _clean(vault, tool, 100)
    if not session_id:
        session_id = (
            "standalone-" + _digest(attempt_id)[:32] if attempt_id
            else "standalone-" + uuid.uuid4().hex
        )
    domains = tuple(result.domains or ["unclassified"])
    target = load_settings(vault).feedback.recall_target_minimum
    attempt = RecallAttempt(
        attempt_id=attempt_id or "pending",
        timestamp=_now(now).isoformat(timespec="seconds"),
        session_id=session_id, task_id=task_id, task_revision=result.task_revision,
        task_text=clean[:MAX_TASK_TEXT], task_fingerprint=_digest(clean), tool=clean_tool,
        route="+".join(domains), domains=domains,
        note_refs=tuple(vault.rel(note.path).removesuffix(".md") for note in result.notes),
        note_domains=tuple(note.domain for note in result.notes),
        note_revisions=tuple(
            note.revision or hashlib.sha256(note.text.encode("utf-8")).hexdigest()
            for note in result.notes
        ),
        total_count=max(result.candidate_count, len(result.notes)),
        usable_count=len(result.notes), target_minimum=target,
        potential_gap=(
            len(result.notes) < target and result.mode not in ("off", "shadow")
            and result.abstention != "missing_task_context"
        ),
        mode=result.mode, abstention=result.abstention,
        sensitivity="redacted" if redacted or tool_redacted else "checked",
    )
    if attempt_id is None:
        attempt = RecallAttempt(**{
            **attempt.as_dict(), "attempt_id": "recall-" + _digest(attempt.intent())[:32],
        })
    data = {"type": "recall-attempt", **attempt.as_dict()}
    text = frontmatter.compose(data, "# Recall attempt\n\nReported routing telemetry; not evidence of correctness.")
    if redact.scan(text, vault):
        raise VaultError("recall attempt metadata contains sensitive identifiers")
    path = vault.path(config.RECALL_ATTEMPTS) / (_digest(attempt.attempt_id) + ".md")
    if _write_once(vault, path, text):
        return attempt, True
    existing = parse_attempt_note(_read_note(vault, path))
    if existing.attempt_id != attempt.attempt_id or existing.intent() != attempt.intent():
        raise VaultError("recall attempt ID is already used for different intent")
    return existing, False


def read_attempt(vault: Vault, attempt_id: str) -> RecallAttempt:
    """Read one identified attempt without scanning unrelated telemetry."""
    require_id(attempt_id, "attempt_id")
    path = vault.path(config.RECALL_ATTEMPTS) / (_digest(attempt_id) + ".md")
    attempt = parse_attempt_note(_read_note(vault, path))
    if attempt.attempt_id != attempt_id:
        raise VaultError("recall attempt identity does not match its record")
    return attempt


def read_attempts(
    vault: Vault, *, session_id: str | None = None, since: datetime | None = None,
    until: datetime | None = None, diagnostics: list[str] | None = None,
) -> list[RecallAttempt]:
    """Read valid immutable attempts, deduplicating copies and flagging conflicts."""
    records: dict[str, RecallAttempt] = {}
    conflicts: set[str] = set()
    base = vault.path(config.RECALL_ATTEMPTS)
    if not base.exists() and not fsutil.is_link(base):
        return []
    if not _safe_directory(vault, base):
        if diagnostics is None:
            raise VaultError("recall attempt directory is not a safe directory")
        diagnostics.append("recall attempt directory is not a safe directory")
        return []
    for path in sorted(base.glob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            attempt = parse_attempt_note(_read_note(vault, path))
            existing = records.get(attempt.attempt_id)
            if existing and existing.intent() != attempt.intent():
                conflicts.add(attempt.attempt_id)
                raise VaultError("conflicting copies of one recall attempt")
            if existing and existing.timestamp <= attempt.timestamp:
                continue
            records[attempt.attempt_id] = attempt
        except (VaultError, ValueError, TypeError, OSError) as exc:
            message = f"{config.RECALL_ATTEMPTS}/{path.name}: invalid or conflicting recall attempt"
            if diagnostics is None:
                raise VaultError(message) from exc
            diagnostics.append(message)
    return sorted((
        attempt for key, attempt in records.items()
        if key not in conflicts and (session_id is None or attempt.session_id == session_id)
        and (since is None or parse_timestamp(attempt.timestamp) >= _now(since))
        and (until is None or parse_timestamp(attempt.timestamp) <= _now(until))
    ), key=lambda attempt: (attempt.timestamp, attempt.attempt_id))


def _window(vault: Vault, now: datetime | None, days: int | None, since: datetime | None):
    end = _now(now)
    days = load_settings(vault).feedback.recent_days if days is None else days
    if type(days) is not int or not 1 <= days <= 36_500:
        raise VaultError("diagnostic window days must be an integer between 1 and 36500")
    start = _now(since) if since is not None else end - timedelta(days=days)
    if start > end:
        raise VaultError("diagnostic window starts after it ends")
    return start, end, days


def recall_summary(
    vault: Vault, *, now: datetime | None = None, days: int | None = None,
    since: datetime | None = None, diagnostics: list[str] | None = None,
    attempts: Iterable[RecallAttempt] | None = None,
) -> dict:
    """Read-only attempt counts; disabled/context-less recall is not a knowledge gap."""
    start, end, days = _window(vault, now, days, since)
    records = (
        read_attempts(vault, since=start, until=end, diagnostics=diagnostics)
        if attempts is None else [
            item for item in attempts if start <= parse_timestamp(item.timestamp) <= end
        ]
    )

    keys = ("attempts", "empty_recalls", "weak_recalls", "potential_gaps", "served_notes")
    totals = dict.fromkeys(keys, 0)
    by_domain: dict[str, dict[str, int]] = {}
    by_route: dict[str, dict[str, int]] = {}
    domain_sessions: dict[str, set[str]] = {}
    route_sessions: dict[str, set[str]] = {}
    for item in records:
        increments = (
            1, int(item.usable_count == 0),
            int(0 < item.usable_count < item.target_minimum), int(item.potential_gap), item.usable_count,
        )
        groups = [totals, by_route.setdefault(item.route, dict.fromkeys(keys, 0))]
        groups.extend(by_domain.setdefault(domain, dict.fromkeys(keys, 0)) for domain in item.domains)
        for group in groups:
            for key, increment in zip(keys, increments):
                group[key] += increment
        route_sessions.setdefault(item.route, set()).add(item.session_id)
        for domain in item.domains:
            domain_sessions.setdefault(domain, set()).add(item.session_id)
    totals["unique_sessions"] = len({item.session_id for item in records})
    for domain, sessions in domain_sessions.items():
        by_domain[domain]["unique_sessions"] = len(sessions)
    for route, sessions in route_sessions.items():
        by_route[route]["unique_sessions"] = len(sessions)

    return {
        **totals, "window_days": days,
        "by_domain": dict(sorted(by_domain.items())), "by_route": dict(sorted(by_route.items())),
    }


def recall_quality_summary(
    vault: Vault, *, now: datetime | None = None, days: int | None = None,
    since: datetime | None = None, events: Iterable[OutcomeEvent] | None = None,
    diagnostics: list[str] | None = None,
    attempts: Iterable[RecallAttempt] | None = None,
) -> dict:
    """Group common reported recall/routing outcomes, never infer quality from retrieval."""
    from .outcomes import collect_evidence

    start, end, days = _window(vault, now, days, since)
    attempt_by_id = {
        item.attempt_id: item
        for item in (read_attempts(vault, diagnostics=diagnostics) if attempts is None else attempts)
    }
    totals = dict.fromkeys(_QUALITIES, 0)
    by_domain: dict[str, dict[str, int]] = {}
    by_route: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for event in collect_evidence(vault) if events is None else events:
        if (
            event.subject_type not in ("recall", "routing") or event.event_id in seen
            or event.outcome not in _QUALITIES or not start <= parse_timestamp(event.timestamp) <= end
        ):
            continue
        seen.add(event.event_id)
        attempt = attempt_by_id.get(event.subject_id)
        if attempt is not None and attempt.session_id != event.session_id:
            attempt = None
        domains = attempt.domains if attempt else (event.domain or "unclassified",)
        route = attempt.route if attempt else event.context.get("route", "+".join(domains))
        totals[event.outcome] += 1
        for domain in domains:
            by_domain.setdefault(domain, dict.fromkeys(_QUALITIES, 0))[event.outcome] += 1
        by_route.setdefault(route, dict.fromkeys(_QUALITIES, 0))[event.outcome] += 1
    return {
        "counts": totals, "window_days": days,
        "by_domain": dict(sorted(by_domain.items())), "by_route": dict(sorted(by_route.items())),
    }


def create_gap_candidate(
    vault: Vault, need: str, *, domain: str, source_episode: str = "",
    session_id: str | None = None, now: datetime | None = None,
) -> Path:
    """Capture an idempotent research need, without claims or approval fields."""
    declared = {item.name for item in router.load_domains(vault)}
    if domain not in declared | {"unclassified"}:
        raise VaultError("gap domain is not declared in the domain registry")
    if session_id is not None:
        require_id(session_id, "session_id")
    clean, was_redacted = _clean(vault, need, 1000)
    if not clean:
        raise VaultError("gap candidate requires a nonempty need")
    if not isinstance(source_episode, str):
        raise VaultError("gap source_episode must be an episode reference")
    source_episode = source_episode.strip().removesuffix(".md")
    if source_episode:
        if "/" not in source_episode:
            source_episode = config.EPISODES + "/" + source_episode
        if (
            not source_episode.startswith(config.EPISODES + "/")
            or any(part in ("", ".", "..") for part in source_episode.split("/"))
            or any(char in source_episode for char in "\\:[]#|\n\r\t")
        ):
            raise VaultError("gap source_episode must be a vault-relative episode reference")
        source = fsutil.ensure_within(vault, vault.path(source_episode + ".md"))
        if not source.is_relative_to(vault.root / config.EPISODES):
            raise VaultError("gap source_episode must stay in the episode tier")
        if source.exists() and _read_note(vault, source).type != "episode":
            raise VaultError("gap source_episode must reference an episode, not telemetry")
    intent = {
        "type": "gap", "title": "Research gap: " + clean[:100],
        "need": clean, "domains": [domain], "signal": "normal",
        "source": "recall-gap", "source_episode": source_episode, "session_id": session_id,
        "trust": "first-party",
    }
    candidate_id = "gap-" + _digest(intent)[:32]
    meta = {
        **intent, "candidate_id": candidate_id,
        "captured": _now(now).isoformat(timespec="seconds"),
        "sensitivity": "redacted" if was_redacted else "checked",
    }
    text = frontmatter.compose(
        meta, "# Research gap\n\n"
        f"Need: {clean}\n\nThis is a research/work signal, not a factual knowledge claim.",
    )
    if redact.scan(text, vault):
        raise VaultError("gap metadata contains sensitive identifiers")
    path = vault.path(config.INBOX) / f"{candidate_id}.md"
    if not _write_once(vault, path, text):
        existing = _read_note(vault, path)
        if any(existing.meta.get(key) != value for key, value in intent.items() if key != "signal"):
            raise VaultError("gap identity is already used for different intent")
    return path


@dataclass(frozen=True)
class RoutingSuggestion:
    episode_ref: str
    recalled_domains: tuple[str, ...]
    suggested_domain: str
    score: int
    matched_terms: tuple[str, ...]
    sections: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            item.name: list(value) if isinstance(value := getattr(self, item.name), tuple) else value
            for item in fields(self)
        }


def routing_suggestions(
    vault: Vault, *, episodes: Iterable[Note] | None = None, session_id: str | None = None,
    now: datetime | None = None, days: int | None = None, since: datetime | None = None,
    limit: int = 20, diagnostics: list[str] | None = None,
) -> list[RoutingSuggestion]:
    """Second pass over episode sections using exactly the first-pass matcher.

    An explicit domain name or at least two distinct vocabulary terms is
    required. Repetition of one generic word is not strong routing evidence.
    Suggestions are returned to a human/curator; no router or index is rewritten.
    """
    if type(limit) is not int or limit < 0:
        raise VaultError("routing suggestion limit must be a nonnegative integer")
    start, end, _ = _window(vault, now, days, since)
    domains = router.load_domains(vault)
    attempts_by_session: dict[str, list[RecallAttempt]] = {}
    for attempt in read_attempts(vault, until=end, diagnostics=diagnostics):
        attempts_by_session.setdefault(attempt.session_id, []).append(attempt)
    if episodes is None:
        loaded = []
        base = vault.path(config.EPISODES)
        if not _safe_directory(vault, base):
            if diagnostics is not None:
                diagnostics.append("episode directory is not a safe directory")
            return []
        for path in sorted(base.glob("*.md")):
            try:
                loaded.append(_read_note(vault, path))
            except (VaultError, OSError, ValueError):
                if diagnostics is not None:
                    diagnostics.append("an episode could not be read for routing diagnostics")
        episodes = loaded
    suggestions: list[RoutingSuggestion] = []
    for note in episodes:
        if note.type != "episode" or note.parse_error:
            continue
        try:
            stamp = parse_timestamp(note.meta.get("captured"))
        except VaultError:
            if diagnostics is not None:
                diagnostics.append("an episode has no valid timestamp for routing diagnostics")
            continue
        if not start <= stamp <= end:
            continue
        sid = note.meta.get("session_id")
        if session_id is not None and sid != session_id:
            continue
        linked = attempts_by_session.get(sid, []) if isinstance(sid, str) else []
        recorded = [domain for attempt in linked for domain in attempt.domains]
        recorded = recorded or note.meta.get("recalled_domains", note.meta.get("domains", []))
        if not isinstance(recorded, list) or not all(isinstance(domain, str) for domain in recorded):
            if diagnostics is not None:
                diagnostics.append("an episode has malformed recalled domains")
            continue
        recalled = tuple(sorted(set(recorded)))
        matched: dict[str, list[tuple[str, router.DomainMatch]]] = {}
        for heading in _EPISODE_SECTIONS:
            text = _clean(vault, section(note.body, heading), 8000)[0]
            for evidence in router.match_evidence(text, domains):
                matched.setdefault(evidence.domain, []).append((heading, evidence))
        for domain, evidence in matched.items():
            if domain in recalled:
                continue
            terms = tuple(sorted({term for _, item in evidence for term in item.terms}))
            explicit = domain.replace("-", " ") in terms
            if not explicit and len(terms) < 2:
                continue
            reasons = [
                "episode terms match a domain absent from recorded recall",
                "matched routing vocabulary: " + ", ".join(terms),
            ]
            if note.meta.get("recall_quality") in ("missed", "off-target"):
                reasons.append("episode reports " + note.meta["recall_quality"] + " recall")
            suggestions.append(RoutingSuggestion(
                note.ref, recalled, domain, sum(item.score for _, item in evidence),
                terms, tuple(heading for heading, _ in evidence), tuple(reasons),
            ))
    return sorted(
        suggestions, key=lambda item: (-item.score, item.episode_ref, item.suggested_domain),
    )[:limit]
