"""Versioned, immutable reported feedback; never execution attestations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from .config import VaultError
from .experience_types import require_id, require_text

OUTCOME_VERSION = 1
SUBJECT_OUTCOMES = {
    "knowledge": ("held", "failed", "unclear", "not-applicable"),
    "skill": ("succeeded", "failed", "partial"),
    "recall": ("useful", "partial", "missed", "off-target"),
    "routing": ("useful", "partial", "missed", "off-target"),
}
FAILURE_REASONS = (
    "behaviour_changed", "misapplied", "context_mismatch",
    "insufficient_information", "unknown",
)
CONTEXT_FIELDS = (
    "tool", "product", "version", "project", "route", "task_category",
    "task_id", "revision",
)


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise VaultError("outcome timestamp requires an ISO datetime with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VaultError("outcome timestamp requires a valid ISO datetime") from exc
    if result.utcoffset() is None:
        raise VaultError("outcome timestamp requires a timezone")
    try:
        return result.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise VaultError("outcome timestamp is outside the supported UTC range") from exc


@dataclass(frozen=True)
class OutcomeEvent:
    event_id: str
    timestamp: str
    session_id: str
    subject_type: str
    subject_id: str
    outcome: str
    reason: str | None = None
    domain: str = ""
    context: Mapping[str, str] = field(default_factory=dict)
    source: str = "cli"
    detail: str = ""
    schema_version: int = OUTCOME_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != OUTCOME_VERSION:
            raise VaultError("unsupported outcome schema_version")
        require_id(self.event_id, "event_id")
        require_id(self.session_id, "session_id")
        if not isinstance(self.subject_type, str) or self.subject_type not in SUBJECT_OUTCOMES:
            raise VaultError("unknown outcome subject_type")
        if not isinstance(self.outcome, str) or self.outcome not in SUBJECT_OUTCOMES[self.subject_type]:
            raise VaultError(f"invalid {self.subject_type} outcome: {self.outcome}")
        object.__setattr__(self, "subject_id", require_text(self.subject_id, "subject_id", 300))
        object.__setattr__(self, "source", require_text(self.source, "source", 300))
        if not isinstance(self.domain, str) or not isinstance(self.detail, str):
            raise VaultError("outcome domain and detail must be text")
        if self.domain:
            require_id(self.domain, "domain")
        if self.detail:
            require_text(self.detail, "detail", 1000)
        if self.reason is not None and self.reason not in FAILURE_REASONS:
            raise VaultError("unknown outcome failure reason")
        if self.reason is not None and self.outcome != "failed":
            raise VaultError("failure reasons are only valid for failed outcomes")
        if not isinstance(self.context, Mapping):
            raise VaultError("outcome context must be a mapping")
        context: dict[str, str] = {}
        for key, value in self.context.items():
            if key not in CONTEXT_FIELDS:
                raise VaultError(f"unknown outcome context field: {key}")
            context[key] = require_text(value, f"context.{key}", 250)
        object.__setattr__(self, "context", MappingProxyType(context))
        object.__setattr__(self, "timestamp", parse_timestamp(self.timestamp).isoformat())
        if self.outcome == "failed" and self.reason is None:
            object.__setattr__(self, "reason", "unknown")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "domain": self.domain,
            "context": dict(self.context),
            "source": self.source,
            "detail": self.detail,
        }

    def intent(self) -> dict[str, object]:
        return {
            key: value for key, value in self.as_dict().items()
            if key not in ("event_id", "timestamp")
        }


def event_from_dict(data: object) -> OutcomeEvent:
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise VaultError("outcome event must be a mapping")
    required = {
        "event_id", "timestamp", "session_id", "subject_type", "subject_id", "outcome",
    }
    allowed = required | {
        "schema_version", "reason", "domain", "context", "source", "detail",
    }
    if required - data.keys():
        raise VaultError("outcome missing fields: " + ", ".join(sorted(required - data.keys())))
    if data.keys() - allowed:
        raise VaultError("unknown outcome fields: " + ", ".join(sorted(data.keys() - allowed)))
    for name in required | {"source", "detail", "domain"}:
        if name in data and not isinstance(data[name], str):
            raise VaultError(f"outcome {name} must be text")
    return OutcomeEvent(**data)
