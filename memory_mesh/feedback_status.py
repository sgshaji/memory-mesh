"""Read-only operational summaries; detailed evidence belongs in explain."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math

from . import config
from .config import Vault
from .curator.analytics import assess_all_knowledge, inbox_health
from .curator.review import pending_review_files
from .curator.transaction import inspect_curation_transactions
from .feedback_config import load_settings
from .notes import iter_notes, knowledge_notes
from .outcomes import collect_evidence
from .redact import redaction_snapshot
from .routing_diagnostics import (
    read_attempts, recall_quality_summary, recall_summary, routing_suggestions,
)
from .skill_health import assess_skills


def build_status(vault: Vault, *, now: datetime | None = None, days: int | None = None) -> dict:
    with redaction_snapshot(vault):
        return _build_status(vault, now=now, days=days)


def _build_status(vault: Vault, *, now: datetime | None, days: int | None) -> dict:
    stamp = now or datetime.now(timezone.utc)
    settings = load_settings(vault)
    diagnostics: list[str] = []
    knowledge = knowledge_notes(vault)
    episodes = [note for note in iter_notes(vault, config.EPISODES) if note.type == "episode"]
    inbox = list(iter_notes(vault, config.INBOX))
    events = collect_evidence(vault, diagnostics=diagnostics, episodes=episodes)
    attempts = read_attempts(vault, diagnostics=diagnostics)
    recalled = recall_summary(vault, now=stamp, days=days, attempts=attempts, diagnostics=diagnostics)
    quality = recall_quality_summary(
        vault, now=stamp, days=days, attempts=attempts, events=events, diagnostics=diagnostics,
    )
    health = inbox_health(vault, now=stamp, inbox=inbox, episodes=episodes)
    attention = health.as_dict()
    if health.oldest_age_days is not None:
        attention["oldest_age_days"] = math.floor(health.oldest_age_days)
    attention["total"] = len(inbox)
    diagnostics.extend(health.warnings)

    assessments = assess_all_knowledge(
        vault, now=stamp, events=events, notes=knowledge, episodes=episodes, diagnostics=diagnostics,
    )
    signals = [
        {
            "reference": item.reference, "needs_review": item.needs_review,
            "recent_behaviour_changes": item.evidence.recent_behaviour_changes,
            "maintenance_allowed": item.maintenance_allowed,
            "basis": "reported feedback; not admission authority",
        }
        for item in assessments if item.evidence.recent_behaviour_changes
    ]
    skills = assess_skills(vault, now=stamp, events=events)
    skill_details = [
        {
            "reference": item.reference, "confidence": item.confidence,
            "confidence_source": item.confidence_source,
            "potentially_stale": item.potentially_stale, "needs_review": item.needs_review,
            "failed_recently": item.failed_recently, "reasons": list(item.reasons),
        }
        for item in skills
    ]
    suggestions = routing_suggestions(vault, episodes=episodes, now=stamp, days=days, diagnostics=diagnostics)
    recovery = inspect_curation_transactions(vault)
    return {
        "schema_version": 1,
        "vault": str(vault.root),
        "recall": {**recalled, "quality": quality},
        "inbox": attention,
        "episodes": {
            "total": len(episodes),
            "by_status": dict(sorted(Counter(note.status or "unknown" for note in episodes).items())),
        },
        "knowledge": {
            "total": len(knowledge),
            "by_status": dict(sorted(Counter(note.status or "unknown" for note in knowledge).items())),
            "confidence_warnings": sorted(
                note.ref for note in knowledge
                if note.status == "validated" and note.meta.get("confidence") == "low"
            ),
            "behaviour_change_signals": sorted(signals, key=lambda item: item["reference"]),
            "needing_review": [item.reference for item in assessments if item.needs_review],
        },
        "skills": {
            "total": len(skills),
            "potentially_stale": sum(item.potentially_stale for item in skills),
            "failed_recently": sum(item.failed_recently for item in skills),
            "needs_review": sum(item.needs_review for item in skills),
            "details": skill_details,
        },
        "routing": {
            "quality_by_domain": quality["by_domain"],
            "suggestions": [item.as_dict() for item in suggestions],
        },
        "curation": {
            "mode": settings.curation.mode, "curator": settings.curation.curator or None,
            "pending_review": [vault.rel(path) for path in pending_review_files(vault)],
            "conflicts": sum(item.state == "conflict" for item in recovery),
            "recovery": [
                {
                    "transaction_id": item.transaction_id, "state": item.state,
                    "journal": vault.rel(item.journal), "conflicts": list(item.conflicts),
                }
                for item in recovery
            ],
        },
        "warnings": sorted(set(diagnostics)),
    }
