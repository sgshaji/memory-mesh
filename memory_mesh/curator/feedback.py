"""Transactional legacy feedback maintenance and non-factual attention queues.

Confidence is recomputed from reports, not decremented from yesterday's score.
Matched behaviour-change quorums quarantine validated legacy knowledge; aging
remains a separate review signal. Neither later successes nor acknowledgements
reactivate knowledge. V2 authority and skill bodies are never mutated here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Callable, Iterable

from .. import confidence, config, frontmatter, fsutil, indexes, outcomes, routing_diagnostics, skill_health
from ..config import Vault, VaultError
from ..experience import get_mode
from ..notes import WIKILINK_RE, Note, iter_notes, knowledge_notes
from ..outcome_types import OutcomeEvent
from . import analytics
from .analytics import KnowledgeAssessment, assess_knowledge as assess_knowledge
from .decisions import Decision
from .transaction import current_transaction

if TYPE_CHECKING:
    from .engine import RunReport


@dataclass
class FeedbackSnapshot:
    now: datetime
    events: tuple[OutcomeEvent, ...]
    notes: dict[str, Note]
    episodes: tuple[Note, ...]
    assessments: dict[str, KnowledgeAssessment]


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()[:24]


def queue_attention(
    report: RunReport, kind: str, subject: str, rationale: str,
    details: dict[str, object], *, identity: object,
) -> None:
    """Acknowledgeable advice only; never an executable factual decision."""
    report.decisions.append(Decision(
        "HOLD", rationale, target_ref=subject,
        claim=json.dumps(details, ensure_ascii=True, sort_keys=True, indent=2),
        payload={
            "review_only": True, "review_key": kind + "-" + _fingerprint([subject, identity]),
            "attention_kind": kind, "subject_ref": subject, "details": details,
        },
    ))


def queue_gap(report: RunReport, note: Note, priority: analytics.CandidatePriority | None) -> None:
    need = note.meta.get("need")
    if not isinstance(need, str) or not need.strip():
        report.warnings.append(f"{note.ref}: gap has no valid research need; repair its metadata")
    details: dict[str, object] = {
        "need": note.meta.get("need", ""), "source_episode": note.meta.get("source_episode"),
        "signal": priority.signal if priority is not None else "normal",
        "episode_refs": list(priority.episode_refs) if priority is not None else [],
        "priority_reasons": list(priority.reasons) if priority is not None else [],
        "next_action": "Research this need and capture separately verified observations; acknowledgement admits nothing",
    }
    queue_attention(
        report, "gap", note.ref, "Knowledge gap needs research, not factual promotion",
        details, identity=details,
    )


def inbox_reference_filter(inbox: Iterable[Note]) -> Callable[[str], bool]:
    """Episode links preserve context; gap needs never become factual claims."""
    def reference_key(value: str) -> str:
        value = value.strip().replace("\\", "/")
        if not value.lower().endswith(".md"):
            value += ".md"
        # Use filesystem case semantics without collapsing unsafe dot segments.
        return os.path.normcase(value).replace("\\", "/")

    notes = list(inbox)
    by_ref = {reference_key(note.ref): note for note in notes}
    by_slug: dict[str, list[Note]] = {}
    for note in notes:
        by_slug.setdefault(reference_key(note.path.name), []).append(note)

    def is_reference(text: str) -> bool:
        inbox_link = False
        for link in WIKILINK_RE.finditer(text):
            ref = reference_key(link.group(1))
            referenced = by_ref.get(ref)
            if referenced is None and "/" not in ref and len(by_slug.get(ref, [])) == 1:
                referenced = by_slug[ref][0]
            if referenced is not None and referenced.type == "gap":
                return True
            inbox_link |= ref.startswith((config.INBOX + "/", config.EPISODE_UNREVIEWED + "/")) or referenced is not None
        remaining = WIKILINK_RE.sub("", text).strip(" \t.-:;")
        return inbox_link and not remaining

    return is_reference


def apply_knowledge_feedback(vault: Vault, report: RunReport, *, now: datetime | date | None = None) -> FeedbackSnapshot:
    """Collect once, update legacy metadata, and return the shared assessment batch."""
    if get_mode(vault) != "legacy" or current_transaction(vault) is None:
        raise VaultError("legacy feedback maintenance requires its active curation transaction")
    stamp = analytics._now(now)
    events = tuple(outcomes.collect_evidence(vault, diagnostics=report.warnings))
    notes = {note.ref: note for note in knowledge_notes(vault)}
    episode_notes = tuple(iter_notes(vault, config.EPISODES))
    assessed = analytics.assess_all_knowledge(
        vault, now=stamp, events=events, notes=notes.values(), episodes=episode_notes,
        diagnostics=report.warnings,
    )
    health: dict[str, KnowledgeAssessment] = {}
    for item in assessed:
        note = notes[item.subject_id]
        if not item.maintenance_allowed:
            health[item.subject_id] = item
            continue
        meta = dict(note.meta)
        meta["feedback"] = dict(item.feedback)
        if item.confidence is not None:
            meta["confidence"] = item.confidence
        if item.last_verified is not None:
            meta["last_verified"] = item.last_verified
        if note.status == "validated" and (item.possible_behaviour_change or item.aging_due):
            reason = "behaviour_changed" if item.possible_behaviour_change else "verification_aging"
            meta["status"] = "stale"
            meta["feedback_quarantine"] = {
                "reason": reason, "since": stamp.date().isoformat(),
                "evidence": _fingerprint(
                    item.evidence.event_ids if item.possible_behaviour_change
                    else [item.last_verified, meta.get("first_observed")]
                ),
            }
            report.log("STALE", note.ref, f"{reason}; explicit review required; confidence remains independently derived")
            item = replace(item, status="stale", needs_review=True)
        summary = (
            f"{item.confidence_source}; {item.feedback['held']} held, {item.feedback['failed']} failed, "
            f"{item.feedback['unclear']} unclear; confidence={item.confidence or 'unknown'}; "
            f"review={'required' if item.needs_review else 'not-required'}"
        )
        if meta != note.meta or "feedback_summary" in note.meta:
            meta["feedback_summary"] = summary
        if meta != note.meta:
            fsutil.curator_write(vault, note.path, frontmatter.compose(meta, note.body))
            report.touched.add(note.rel)
            report.log("FEEDBACK", note.ref, meta["feedback_summary"])
            notes[note.ref] = Note(note.path, meta, note.body, vault)
        health[item.subject_id] = item
    return FeedbackSnapshot(stamp, events, notes, episode_notes, health)


def _changed_entry(index: indexes.DomainIndex, references, ref: str, reason: str) -> None:
    entries = index.sections.setdefault("Recently changed", [])
    for entry in entries:
        existing, _ = references.resolve(entry.ref)
        if existing == ref or entry.ref == ref:
            entry.gloss = reason
            return
    index.add("Recently changed", ref, reason)


def refresh_indexes(vault: Vault, report: RunReport, snapshot: FeedbackSnapshot) -> None:
    """Remove unsafe trusted placements and rebuild only evidenced recent holds."""
    references = analytics._References(list(snapshot.notes.values()), config.KNOWLEDGE)
    for index in indexes.list_domain_indexes(vault):
        for section_name in list(index.sections):
            if section_name == "Recently changed":
                continue
            for entry in list(index.sections[section_name]):
                ref, error = references.resolve(entry.ref)
                note = snapshot.notes.get(ref) if ref is not None else None
                if section_name == "Active project" and note is None:
                    continue  # The knowledge inventory does not contain genuine project context.
                if note is not None and "v2_admission" in note.meta:
                    continue
                if note is None or not indexes.eligible_for_section(note, section_name, now=snapshot.now):
                    index.sections[section_name].remove(entry)
                    reason = (
                        error or "unresolved reference" if note is None
                        else f"{note.status}; outside current trusted placement"
                    )
                    _changed_entry(index, references, ref or entry.ref, reason)
                    report.log("INDEX-FIX", index.domain, f"{ref or entry.ref}: {reason}")
        linked: set[str] = set()
        for section_name, entry in index.all_entries():
            if section_name in indexes.LINK_SECTIONS:
                ref, _ = references.resolve(entry.ref)
                if ref is not None:
                    linked.add(ref)
        recent = []
        for entry in index.sections.get("Recently verified (30 days)", []):
            ref, _ = references.resolve(entry.ref)
            if ref in snapshot.notes and "v2_admission" in snapshot.notes[ref].meta:
                recent.append(entry)
        for ref, item in sorted(snapshot.assessments.items()):
            verified = item.evidence.last_verified
            note = snapshot.notes[ref]
            if (
                ref not in linked or not verified or not item.maintenance_allowed
                or not indexes.eligible_for_section(note, "Recently verified (30 days)", now=snapshot.now)
            ):
                continue
            age = (snapshot.now.date() - date.fromisoformat(verified)).days
            if 0 <= age <= 30:
                recent.append(indexes.Entry(ref, f"held {verified}"))
        index.sections["Recently verified (30 days)"] = recent
        for section_name in indexes.SECTIONS:
            index.sections.setdefault(section_name, [])
        if index.link_count() > config.INDEX_MAX_LINKS:
            queue_attention(
                report, "index-budget", index.domain, "Review index capacity; no automatic usage-based eviction",
                {"links": index.link_count(), "maximum": config.INDEX_MAX_LINKS},
                identity=[index.domain, index.link_count(), config.INDEX_MAX_LINKS],
            )
        if indexes.write_index_if_changed(vault, index, snapshot.now.date().isoformat()):
            report.touched.add(vault.rel(index.path))


def graduation_candidates(vault: Vault, assessments: dict[str, KnowledgeAssessment], report: RunReport) -> None:
    """Retain graduation attention, requiring independent matched supporting sessions."""
    lines = []
    for note in knowledge_notes(vault):
        item = assessments.get(note.ref)
        if item is None or not item.maintenance_allowed or item.needs_review:
            continue
        sessions = {
            contribution.event.session_id for contribution in item.evidence.contributions
            if contribution.included and contribution.bucket == "held"
            and contribution.applicability.state == "match"
        }
        state = confidence.FeedbackState(held=len(sessions), failed=item.feedback["failed"])
        procedure = any(kind in ("procedure", "fix", "command", "step") for kind, _ in note.observations())
        if confidence.graduation_ready(state, str(note.status), procedure):
            lines.append(f"- [[{note.ref}]] - held in {len(sessions)} independent sessions, failed 0 - propose a skill; never edit its body")
    if not lines:
        return
    path = vault.path(config.GRADUATION_FILE)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Graduation candidates\n"
    new_lines = [line for line in lines if line.split("]]", 1)[0] + "]]" not in existing]
    if new_lines:
        fsutil.curator_write(vault, path, existing.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n")
        report.touched.add(config.GRADUATION_FILE)
        for line in new_lines:
            report.log("GRADUATE?", line.split("]]", 1)[0].removeprefix("- [["))


def complete_attention(vault: Vault, report: RunReport, snapshot: FeedbackSnapshot) -> None:
    """Index hygiene and durable review-only advice share the precollected evidence."""
    refresh_indexes(vault, report, snapshot)
    for ref, item in snapshot.assessments.items():
        if not item.maintenance_allowed or not item.needs_review:
            continue
        note = snapshot.notes[ref]
        identity = (
            note.meta.get("feedback_quarantine", {"status": "stale"})
            if item.status == "stale" else {
                "events": item.evidence.event_ids, "aging": item.aging_due,
                "never_exercised": item.never_exercised, "applicability": item.applicability.state,
            }
        )
        queue_attention(report, "knowledge", ref, "Review legacy knowledge; acknowledgement changes no factual state", {
            "status": item.status, "confidence": item.confidence,
            "possible_behaviour_change": item.possible_behaviour_change,
            "reasons": list(item.reasons), "event_count": len(item.evidence.event_ids),
            "next_action": "Inspect assess_knowledge evidence and independently revalidate; never automatically reactivate",
        }, identity=identity)
    attempts = routing_diagnostics.read_attempts(vault, diagnostics=report.warnings)
    usage = analytics.recall_usage(
        vault, now=snapshot.now, attempts=attempts, notes=snapshot.notes.values(),
    )
    report.warnings.extend(usage.warnings)
    for suggestion in analytics.index_suggestions(
        vault, now=snapshot.now, usage=usage, assessments=snapshot.assessments.values(),
        notes=snapshot.notes.values(),
    ):
        queue_attention(report, "index", suggestion.subject_id, "Review index placement; usage is not truth",
                        suggestion.as_dict(), identity=[
                            suggestion.domain, suggestion.action, suggestion.section,
                            suggestion.usage.attempt_ids, suggestion.usage.legacy_count,
                        ])
    for suggestion in routing_diagnostics.routing_suggestions(
        vault, episodes=snapshot.episodes, now=snapshot.now, diagnostics=report.warnings,
    ):
        details = suggestion.as_dict()
        details["next_action"] = "Review domain aliases, keywords and concepts against these episode sections; do not automatically rewrite routing"
        queue_attention(report, "routing", suggestion.episode_ref, "Review routing vocabulary using recorded contextual evidence",
                        details, identity=[suggestion.suggested_domain, suggestion.matched_terms, suggestion.sections])
    for skill in skill_health.assess_skills(vault, now=snapshot.now, events=snapshot.events):
        if not skill.needs_review:
            continue
        dependencies = [
            {"subject_id": item.subject_id, "status": item.status, "confidence": item.confidence,
             "potentially_stale": item.potentially_stale, "needs_review": item.needs_review}
            for item in skill.dependencies
        ]
        details = {
            "confidence": skill.confidence, "confidence_source": skill.confidence_source,
            "potentially_stale": skill.potentially_stale, "reasons": list(skill.reasons),
            "dependencies": dependencies, "event_count": len(skill.evidence.get("event_ids", [])),
            "next_action": "Re-test the skill and dependencies; this notice never edits skill bodies or admission",
        }
        queue_attention(report, "skill", skill.subject_id, "Review skill health; reported outcomes are not execution proof",
                        details, identity=[skill.confidence, skill.potentially_stale, dependencies, skill.evidence.get("event_ids", [])])
    report.warnings[:] = list(dict.fromkeys(report.warnings))
