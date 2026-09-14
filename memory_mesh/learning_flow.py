"""Selective proposal staging; only a curator-reviewed proposal becomes a note."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .config import Vault, VaultError
from .attestations import read_attestation
from . import fsutil
from .experience import (
    MAX_EVENTS, MAX_PROPOSALS, context_digest, event_replayed, get_mode, load_task_record,
    require_active, safe_text, snapshot,
)
from .experience_store import ExperienceLimit, RecordStore
from .experience_types import TaskSnapshot, digest, require_id, require_revision, require_strings, version_matches
from .learning_admission import Proposal, assess, parse_proposal
from .notes import Note, load_note, resolve_ref
from .router import load_domains

if TYPE_CHECKING:
    from .curator.decisions import Decision

POLICY_VERSION = 1


@dataclass(frozen=True)
class ApprovedLesson:
    proposal: Proposal
    binding: dict[str, str]
    source: dict[str, Any]
    receipt: dict[str, Any]
    state: str
    runtime_version: str


def admission_key(task_id: str, proposal_id: str) -> str:
    return digest([require_id(task_id, "task_id"), require_id(proposal_id, "proposal_id")])


def proposal_data(proposal: Proposal) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in asdict(proposal).items()
    }


def source_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": record["task_id"], "project": record["project"],
        "tool": record["tool"], "version": record["version"], "revision": record["revision"],
        "goal": record["goal"], "checks": list(record["checks"]), "facts": list(record["facts"]),
        "context_digest": context_digest(record),
    }


def claim_text(proposal: Proposal) -> str:
    limitations = "; ".join(proposal.limitations) or "No broader behavior was established."
    return (
        f"When declared conditions [{', '.join(proposal.conditions)}] apply: {proposal.action} "
        f"Observed check outcome: {proposal.expected_outcome}. "
        f"Limitations: {limitations} Expected reuse benefit (not measured): {proposal.rationale}"
    )


def _safe_proposal(vault: Vault, proposal: Proposal) -> None:
    for key, value in proposal_data(proposal).items():
        if isinstance(value, str):
            safe_text(vault, value, "proposal text", 500)
        elif isinstance(value, list):
            for item in value:
                safe_text(vault, item, "proposal text", 250)
    if proposal.domain not in {domain.name for domain in load_domains(vault)}:
        raise VaultError("proposal domain is not declared in this vault")


def load_proposal(record: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    require_id(proposal_id, "proposal_id")
    entry = record["proposals"].get(proposal_id)
    fields = {
        "proposal", "proposal_hash", "content_hash", "source", "state", "feedback",
        "created_at", "admission_key", "candidate_ref",
    }
    if not isinstance(entry, dict) or set(entry) != fields:
        raise VaultError("proposal was not found or has an invalid record")
    proposal = parse_proposal(entry["proposal"])
    if proposal is None or proposal.proposal_id != proposal_id:
        raise VaultError("invalid recorded proposal identity")
    if entry["proposal_hash"] != digest(proposal_data(proposal)):
        raise VaultError("recorded proposal content has changed")
    if entry["state"] not in ("pending", "approved", "held", "outdated"):
        raise VaultError("invalid recorded proposal state")
    if not isinstance(entry["feedback"], dict) or len(entry["feedback"]) > 64:
        raise VaultError("invalid or over-budget proposal feedback")
    source = entry["source"]
    source_fields = {
        "task_id", "project", "tool", "version", "revision", "goal",
        "checks", "facts", "context_digest",
    }
    if not isinstance(source, dict) or set(source) != source_fields:
        raise VaultError("invalid proposal source snapshot")
    if source["task_id"] != record["task_id"] or source["revision"] != proposal.task_revision:
        raise VaultError("proposal source identity does not match")
    require_revision(source["revision"])
    for name in ("task_id", "project", "tool", "version"):
        require_id(source[name], "proposal source")
    if not version_matches(source["version"], source["version"]):
        raise VaultError("invalid proposal source version")
    require_strings(source["checks"], "source checks", 1, 8, identifiers=True)
    require_strings(source["facts"], "source facts", 0, 8, identifiers=True)
    return entry


def approved_lesson(vault: Vault, binding: object, *, allow_held: bool = False) -> ApprovedLesson:
    if not isinstance(binding, dict) or set(binding) != {"task_id", "proposal_id", "proposal_hash"}:
        raise VaultError("missing or invalid V2 admission binding")
    task_id = require_id(binding["task_id"], "task_id")
    proposal_id = require_id(binding["proposal_id"], "proposal_id")
    record = load_task_record(RecordStore(vault), task_id)
    entry = load_proposal(record, proposal_id)
    proposal = parse_proposal(entry["proposal"])
    assert proposal is not None
    _safe_proposal(vault, proposal)
    if entry["state"] != "approved" and not (allow_held and entry["state"] == "held"):
        raise VaultError("lesson is not approved for reuse")
    key = admission_key(task_id, proposal_id)
    receipt = read_attestation(vault, "admission", key)
    fields = {
        "policy_version", "task_id", "proposal_id", "proposal_hash", "source_hash",
        "claim_hash", "episode_ref", "episode_body_hash", "observed_at", "approved_at",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise VaultError("approved admission receipt is missing")
    if (
        type(receipt["policy_version"]) is not int or receipt["policy_version"] != POLICY_VERSION
        or receipt["task_id"] != task_id or receipt["proposal_id"] != proposal_id
        or receipt["proposal_hash"] != entry["proposal_hash"]
        or binding["proposal_hash"] != entry["proposal_hash"]
        or receipt["source_hash"] != digest(entry["source"])
        or receipt["claim_hash"] != digest(claim_text(proposal))
        or entry["admission_key"] != key
    ):
        raise VaultError("admission receipt does not match the reviewed proposal")
    source = entry["source"]
    observed = snapshot(vault, record)
    reviewed_context = TaskSnapshot(
        task_id=task_id, revision=source["revision"], project=source["project"],
        tool=source["tool"], version=source["version"], goal=source["goal"],
        checks=tuple(source["checks"]), facts=tuple(source["facts"]), evidence=observed.evidence,
    )
    if assess(reviewed_context, proposal, semantic_approved=True).outcome != "admit":
        raise VaultError("reviewed execution evidence is no longer valid")
    ref = receipt["episode_ref"]
    if not isinstance(ref, str) or not ref.startswith("episodes/") or ".." in ref.split("/"):
        raise VaultError("admission receipt has an invalid evidence reference")
    path = fsutil.ensure_within(vault, vault.path(ref + ".md"))
    if not path.is_file() or path.is_symlink():
        raise VaultError("admission evidence episode is missing")
    episode = load_note(path, vault)
    if episode.type != "episode" or episode.status not in ("summarised", "mined"):
        raise VaultError("admission evidence episode is not finalized")
    if digest(episode.body) != receipt["episode_body_hash"]:
        raise VaultError("admission evidence episode has changed")
    versions = {
        item.tool_version for item in reviewed_context.evidence
        if item.evidence_id in proposal.evidence_ids
    }
    return ApprovedLesson(proposal, dict(binding), source, receipt, entry["state"], versions.pop())


def validate_note_binding(vault: Vault, note: Note, *, allow_held: bool = False) -> ApprovedLesson:
    lesson = approved_lesson(vault, note.meta.get("v2_admission"), allow_held=allow_held)
    observed_text = " ".join(text for _kind, text in note.observations())
    if (
        observed_text != claim_text(lesson.proposal)
        or note.title != lesson.proposal.title
        or note.meta.get("domains") != [lesson.proposal.domain]
        or note.meta.get("trust") != "first-party"
    ):
        raise VaultError("note content does not match its reviewed admission")
    return lesson


def _review_result(proposal: Proposal, *, shadow: bool = False) -> dict[str, Any]:
    return {
        "outcome": "review", "reasons": ["semantic_review_required"],
        "proposal_id": proposal.proposal_id,
        "proposal_hash": digest(proposal_data(proposal)),
        "preview": claim_text(proposal), "shadow": shadow,
    }


def submit_proposal(vault: Vault, task_id: str, data: object) -> dict[str, Any]:
    require_active(vault)
    proposal = parse_proposal(data)
    if proposal is None:
        return {"outcome": "ignore", "reasons": ["no_proposal"]}
    _safe_proposal(vault, proposal)
    payload = proposal_data(proposal)
    content_hash = digest({key: value for key, value in payload.items() if key != "proposal_id"})
    store = RecordStore(vault)
    with store.transaction():
        record = load_task_record(store, task_id)
        if proposal.proposal_id in record["proposals"]:
            previous = load_proposal(record, proposal.proposal_id)
            if previous["proposal_hash"] != digest(payload):
                raise VaultError("proposal identity was reused with conflicting content")
            if previous["state"] == "pending":
                return _review_result(proposal)
            return {"outcome": "defer", "reasons": [f"proposal_{previous['state']}"]}
        decision = assess(snapshot(vault, record), proposal)
        if decision.outcome != "review":
            return {"outcome": decision.outcome, "reasons": list(decision.reasons)}
        for entry in record["proposals"].values():
            if isinstance(entry, dict) and entry.get("content_hash") == content_hash:
                return {"outcome": "ignore", "reasons": ["duplicate_proposal_content"]}
        if get_mode(vault) == "shadow":
            return _review_result(proposal, shadow=True)
        if len(record["proposals"]) >= MAX_PROPOSALS:
            raise VaultError("task proposal budget exhausted")
        event_id = "proposal-" + digest(proposal.proposal_id)
        event_replayed(record, event_id, payload)
        record["proposals"][proposal.proposal_id] = {
            "proposal": payload, "proposal_hash": digest(payload), "content_hash": content_hash,
            "state": "pending", "feedback": {},
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "admission_key": None, "candidate_ref": None,
            "source": source_snapshot(record),
        }
        record["events"][event_id] = digest(payload)
        store.save("tasks", task_id, record)
        return _review_result(proposal)


def review_decisions(vault: Vault) -> list[Decision]:
    from .curator.decisions import Decision

    if get_mode(vault) != "strict":
        return []
    store = RecordStore(vault)
    decisions = []
    for task_id, _raw in store.iter_records("tasks"):
        record = load_task_record(store, task_id)
        for proposal_id in record["proposals"]:
            entry = load_proposal(record, proposal_id)
            if entry["state"] != "pending":
                continue
            proposal = parse_proposal(entry["proposal"])
            assert proposal is not None
            _safe_proposal(vault, proposal)
            decision = assess(snapshot(vault, record), proposal)
            reference = f"{store.record_ref('tasks', task_id)}::{proposal_id}"
            if decision.outcome != "review":
                decisions.append(Decision(
                    "HOLD", "admission deferred: " + ", ".join(decision.reasons),
                    source_ref=reference,
                ))
                continue
            decisions.append(Decision(
                "ADMIT",
                "Verify the evidence supports the wording and that this lesson is worth retaining.",
                source_ref=reference,
                claim=(
                    f"{proposal.title}\n{claim_text(proposal)}\n"
                    f"Reviewed project scope: {', '.join(proposal.projects)}\n"
                    f"Runtime: {record['tool']} {record['version']}; "
                    f"execution references: {', '.join(proposal.evidence_ids)}"
                ),
                payload={
                    "task_id": task_id, "proposal_id": proposal_id,
                    "revision": proposal.task_revision, "proposal_hash": entry["proposal_hash"],
                },
            ))
    return decisions


def record_feedback(
    vault: Vault, *, task_id: str, event_id: str, note_ref: str,
    lesson_revision: str, outcome: str, reason: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    if outcome not in ("held", "failed", "unclear", "not-applicable"):
        raise VaultError("invalid reuse feedback outcome")
    require_id(task_id, "task_id")
    require_id(event_id, "event_id")
    note_ref = safe_text(vault, note_ref, "note reference", 200).replace("\\", "/")
    if ":" in note_ref or note_ref.startswith("/") or ".." in note_ref.split("/"):
        raise VaultError("feedback requires a knowledge reference")
    ids = require_strings(evidence_ids or [], "feedback evidence", 0, 6, identifiers=True)
    reason = safe_text(vault, reason, "feedback reason", 250)
    path = resolve_ref(vault, note_ref)
    if path is None:
        raise VaultError("feedback lesson was not found")
    path = fsutil.ensure_within(vault, path)
    try:
        path.relative_to(vault.root / "knowledge")
    except ValueError as exc:
        raise VaultError("feedback requires a knowledge reference") from exc
    if path.is_symlink() or path.stat().st_size > 16_384:
        raise VaultError("feedback lesson is outside its path or size boundary")
    store = RecordStore(vault)
    with store.transaction():
        note = load_note(path, vault)
        lesson = validate_note_binding(vault, note, allow_held=True)
        if lesson_revision != lesson.binding["proposal_hash"]:
            raise VaultError("feedback refers to a different lesson revision")
        if task_id == lesson.binding["task_id"]:
            return {"recorded": False, "outcome": "defer", "reasons": ["origin_task_is_not_reuse"]}
        target_record = load_task_record(store, task_id)
        target = snapshot(vault, target_record)
        proposal = lesson.proposal
        if target.project not in proposal.projects:
            raise VaultError("feedback task is outside the reviewed project scope")
        if outcome != "not-applicable" and (
            target.tool != lesson.source["tool"]
            or not version_matches(lesson.runtime_version, target.version)
            or not set(proposal.conditions).issubset(target.facts)
        ):
            raise VaultError("feedback task does not match the lesson conditions")
        source = load_task_record(store, lesson.binding["task_id"])
        entry = load_proposal(source, proposal.proposal_id)
        verification = "reported"
        if outcome == "held":
            checked = assess(target, replace(
                proposal, task_revision=target.revision, evidence_ids=ids,
            ), semantic_approved=True)
            supported_checks = {
                source["executions"][ref]["check_id"] for ref in proposal.evidence_ids
            }
            relevant = all(
                item.check_id in supported_checks
                and target_record["checks"].get(item.check_id) == source["checks"].get(item.check_id)
                for item in target.evidence if item.evidence_id in ids
            )
            if checked.outcome != "admit" or not relevant:
                return {
                    "recorded": False, "outcome": "defer",
                    "reasons": ["verification_evidence_required"],
                }
            verification = "execution-observed"
        request = {
            "kind": "reuse", "task_id": task_id, "task_revision": target.revision,
            "proposal_id": proposal.proposal_id, "lesson_revision": lesson_revision,
            "outcome": outcome, "reason": reason, "evidence_ids": list(ids),
        }
        key = "reuse-" + digest([task_id, proposal.proposal_id, event_id])
        if key in source["events"]:
            event_replayed(source, key, request)
            return {
                "recorded": True, "replayed": True, "lesson_state": entry["state"],
                "distinct_task_records": len(entry["feedback"]), "causal_claims_supported": False,
            }
        feedback_count = sum(len(item.get("feedback", {})) for item in source["proposals"].values())
        full = len(source["events"]) >= MAX_EVENTS or (
            task_id not in entry["feedback"] and feedback_count >= 64
        )
        if full:
            if outcome == "failed":
                entry["state"] = "held"
                store.save("tasks", source["task_id"], source)
            return {
                "recorded": False, "outcome": "defer", "lesson_state": entry["state"],
                "reasons": ["receipt_budget_exhausted"], "causal_claims_supported": False,
            }
        entry["feedback"][task_id] = {
            **request, "verification": verification,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if outcome == "failed":
            entry["state"] = "held"
        source["events"][key] = digest(request)
        try:
            store.save("tasks", source["task_id"], source)
        except ExperienceLimit:
            if outcome != "failed":
                raise
            preserved = load_task_record(store, source["task_id"])
            load_proposal(preserved, proposal.proposal_id)["state"] = "held"
            store.save("tasks", source["task_id"], preserved)
            return {
                "recorded": False, "outcome": "defer", "lesson_state": "held",
                "reasons": ["receipt_budget_exhausted"], "causal_claims_supported": False,
            }
        return {
            "recorded": True, "replayed": False, "outcome": outcome,
            "verification": verification, "usage_basis": "operator-reported",
            "lesson_state": entry["state"], "distinct_task_records": len(entry["feedback"]),
            "causal_claims_supported": False,
        }
