"""Pure admission policy. Semantic approval comes from curator review, not JSON."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .config import VaultError
from .experience_types import (
    TaskSnapshot, require_id, require_revision, require_strings, require_text,
    exercised_checks, version_matches,
)


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    task_revision: int
    title: str
    domain: str
    action: str
    conditions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    projects: tuple[str, ...]
    limitations: tuple[str, ...]
    rationale: str
    expected_outcome: str


@dataclass(frozen=True)
class AdmissionDecision:
    outcome: str
    reasons: tuple[str, ...]


def parse_proposal(data: object) -> Proposal | None:
    if data is None:
        return None
    fields = {
        "proposal_id", "task_revision", "title", "domain", "action",
        "conditions", "evidence_ids", "projects", "limitations", "rationale",
        "expected_outcome",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise VaultError("learning proposal has missing or unsupported fields")
    outcome = data["expected_outcome"]
    if outcome not in ("passed", "failed"):
        raise VaultError("learning proposal requires a passed or failed observation")
    return Proposal(
        proposal_id=require_id(data["proposal_id"], "proposal_id"),
        task_revision=require_revision(data["task_revision"]),
        title=require_text(data["title"], "title", 120),
        domain=require_id(data["domain"], "domain"),
        action=require_text(data["action"], "action"),
        conditions=require_strings(data["conditions"], "conditions", 1, 4, identifiers=True),
        evidence_ids=require_strings(data["evidence_ids"], "evidence_ids", 0, 6, identifiers=True),
        projects=require_strings(data["projects"], "projects", 1, 8, identifiers=True),
        limitations=require_strings(data["limitations"], "limitations", 0, 4),
        rationale=require_text(data["rationale"], "rationale"),
        expected_outcome=outcome,
    )


def assess(
    task: TaskSnapshot,
    proposal: Proposal | None,
    *,
    semantic_approved: bool = False,
) -> AdmissionDecision:
    if proposal is None:
        return AdmissionDecision("ignore", ("no_proposal",))
    if proposal.task_revision != task.revision:
        return AdmissionDecision("defer", ("stale_task_revision",))
    if task.project not in proposal.projects:
        return AdmissionDecision("defer", ("source_project_outside_scope",))
    if not set(proposal.conditions).issubset(task.facts):
        return AdmissionDecision("defer", ("source_conditions_not_declared",))
    if not proposal.evidence_ids:
        return AdmissionDecision("defer", ("missing_evidence",))
    evidence = {item.evidence_id: item for item in task.evidence}
    if len(evidence) != len(task.evidence):
        return AdmissionDecision("defer", ("conflicting_evidence_identity",))
    if len(set(proposal.evidence_ids)) != len(proposal.evidence_ids):
        return AdmissionDecision("defer", ("duplicate_evidence",))
    observed_versions = set()
    for ref in proposal.evidence_ids:
        item = evidence.get(ref)
        if item is None:
            return AdmissionDecision("defer", ("missing_evidence",))
        if item.origin != "local-unittest":
            return AdmissionDecision("defer", ("unverified_evidence",))
        if item.revision != task.revision:
            return AdmissionDecision("defer", ("stale_evidence_revision",))
        if item.check_id not in task.checks:
            return AdmissionDecision("defer", ("unrelated_check",))
        if item.outcome != proposal.expected_outcome or item.outcome not in ("passed", "failed"):
            return AdmissionDecision("defer", ("unsupported_outcome",))
        if (
            type(item.tests_run) is not int
            or type(item.tests_skipped) is not int
            or type(item.expected_failures) is not int
            or item.tests_skipped < 0
            or item.expected_failures < 0
            or item.tests_run < 0
        ):
            return AdmissionDecision("defer", ("no_executed_checks",))
        exercised = exercised_checks(
            item.tests_run, item.tests_skipped, item.expected_failures, item.checks_executed,
        )
        if item.outcome == "passed" and (exercised is None or exercised <= 0):
            return AdmissionDecision("defer", ("no_executed_checks",))
        if item.outcome == "failed" and not (
            type(item.failures) is int and type(item.errors) is int
            and item.failures >= 0 and item.errors >= 0 and item.failures + item.errors > 0
        ):
            return AdmissionDecision("defer", ("unverified_failure",))
        if not re.fullmatch(r"[a-f0-9]{64}", item.artifact_digest):
            return AdmissionDecision("defer", ("missing_artifact_identity",))
        if task.tool != "python" or not version_matches(task.version, item.tool_version):
            return AdmissionDecision("defer", ("runtime_context_mismatch",))
        observed_versions.add(item.tool_version)
    if len(observed_versions) != 1:
        return AdmissionDecision("defer", ("mixed_runtime_evidence",))
    if len({evidence[ref].artifact_digest for ref in proposal.evidence_ids}) != 1:
        return AdmissionDecision("defer", ("mixed_artifact_evidence",))
    for ref in proposal.evidence_ids:
        item = evidence[ref]
        peers = [
            other for other in task.evidence
            if other.revision == task.revision and other.check_id == item.check_id
        ]
        if len(peers) > 1:
            if any(type(other.sequence) is not int or other.sequence <= 0 for other in peers):
                return AdmissionDecision("defer", ("ambiguous_execution_order",))
            if item.sequence != max(other.sequence for other in peers):
                return AdmissionDecision("defer", ("newer_check_exists",))
        for other in peers:
            if other.evidence_id == ref or other.artifact_digest != item.artifact_digest:
                continue
            if other.outcome == "unknown":
                return AdmissionDecision("defer", ("pending_comparable_check",))
            if other.outcome in ("passed", "failed") and other.outcome != item.outcome:
                return AdmissionDecision("defer", ("contradictory_execution_evidence",))
    if not semantic_approved:
        return AdmissionDecision("review", ("semantic_review_required",))
    return AdmissionDecision("admit", ("supported_reviewed_lesson",))
