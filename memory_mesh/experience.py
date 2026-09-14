"""Typed task snapshots and attributable observations for the opt-in pilot."""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from . import redact
from .attestations import read_attestation
from .config import Vault, VaultError
from .experience_types import (
    Evidence, TaskSnapshot, digest, execution_result, require_id,
    require_revision, require_strings, require_text, version_matches,
)

if TYPE_CHECKING:
    from .experience_store import RecordStore


MAX_EVENTS = 128
MAX_EXECUTIONS = 32
MAX_PROPOSALS = 16


def safe_text(vault: Vault, value: object, field: str, limit: int = 500) -> str:
    text = require_text(value, field, limit)
    if redact.scan(text, vault):
        raise VaultError(f"{field} contains sensitive material; provide redacted text")
    return text


def get_mode(vault: Vault) -> str:
    from .experience_store import RecordStore

    store = RecordStore(vault)
    profile = store.load("profile", "default")
    if profile is None:
        if next(store.record_path("tasks", "probe").parent.glob("*.md"), None) is not None:
            raise VaultError("V2 records exist without a profile; refusing legacy fallback")
        return "legacy"
    if (
        set(profile) != {"schema_version", "mode"}
        or type(profile["schema_version"]) is not int or profile["schema_version"] != 1
    ):
        raise VaultError("unsupported experience profile")
    mode = profile["mode"]
    if mode not in ("shadow", "strict", "off"):
        raise VaultError("invalid experience mode; refusing legacy fallback")
    return mode


def set_mode(vault: Vault, mode: str) -> None:
    from .experience_store import RecordStore

    if mode not in ("shadow", "strict", "off"):
        raise VaultError("experience mode must be shadow, strict, or off")
    store = RecordStore(vault)
    with store.transaction():
        store.save("profile", "default", {"schema_version": 1, "mode": mode})


def require_active(vault: Vault) -> None:
    if get_mode(vault) not in ("strict", "shadow"):
        raise VaultError("enable the experimental shadow or strict profile first")


def _checks(vault: Vault, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 8:
        raise VaultError("task requires 1-8 declared checks")
    return {
        require_id(key, "check_id"): safe_text(vault, label, "check purpose", 250)
        for key, label in value.items()
    }


def load_task_record(store: RecordStore, task_id: str) -> dict[str, Any]:
    task_id = require_id(task_id, "task_id")
    record = store.load("tasks", task_id)
    fields = {
        "schema_version", "task_id", "revision", "project", "tool", "version",
        "goal", "checks", "facts", "events", "executions", "proposals", "workspace_digest",
    }
    if record is None:
        raise VaultError("experience task was not found")
    if (
        set(record) != fields or type(record["schema_version"]) is not int
        or record["schema_version"] != 1 or record["task_id"] != task_id
    ):
        raise VaultError("invalid or unsupported task record")
    require_revision(record["revision"])
    for field in ("project", "tool", "version"):
        require_id(record[field], field)
    require_text(record["goal"], "task goal")
    if not isinstance(record["checks"], dict) or not 1 <= len(record["checks"]) <= 8:
        raise VaultError("invalid task check declarations")
    for check_id, label in record["checks"].items():
        require_id(check_id, "check_id")
        require_text(label, "check purpose", 250)
    require_strings(record["facts"], "task facts", 0, 8, identifiers=True)
    if not version_matches(record["version"], record["version"]):
        raise VaultError("invalid task runtime version")
    workspace = record["workspace_digest"]
    if workspace is not None and (not isinstance(workspace, str) or not re.fullmatch(r"[a-f0-9]{64}", workspace)):
        raise VaultError("invalid task workspace identity")
    for name, limit in (("events", MAX_EVENTS), ("executions", MAX_EXECUTIONS), ("proposals", MAX_PROPOSALS)):
        if not isinstance(record[name], dict) or len(record[name]) > limit:
            raise VaultError("invalid or over-budget task history")
    return record


def context_digest(record: dict[str, Any]) -> str:
    return digest({
        key: record[key] for key in (
            "task_id", "revision", "project", "tool", "version",
            "goal", "checks", "facts", "workspace_digest",
        )
    })


def execution_key(task_id: str, event_id: str) -> str:
    return digest([require_id(task_id, "task_id"), require_id(event_id, "event_id")])


def execution_proof(vault: Vault, record: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    intent = record["executions"].get(event_id)
    fields = {"check_id", "revision", "context_digest", "request_hash", "artifact_digest", "phase", "sequence"}
    if not isinstance(intent, dict) or set(intent) != fields:
        raise VaultError("invalid execution intent")
    require_id(event_id, "event_id")
    require_id(intent["check_id"], "check_id")
    require_revision(intent["revision"])
    if type(intent["sequence"]) is not int or not 1 <= intent["sequence"] <= MAX_EVENTS:
        raise VaultError("invalid execution sequence")
    if intent["revision"] > record["revision"] or intent["phase"] not in ("pending", "complete"):
        raise VaultError("invalid execution revision or phase")
    for name in ("context_digest", "request_hash", "artifact_digest"):
        if not isinstance(intent[name], str) or not re.fullmatch(r"[a-f0-9]{64}", intent[name]):
            raise VaultError("invalid execution identity")
    if intent["revision"] == record["revision"] and intent["context_digest"] != context_digest(record):
        raise VaultError("task context no longer matches its execution intent")
    payload = read_attestation(vault, "execution", execution_key(record["task_id"], event_id))
    if payload is None:
        if intent["phase"] == "complete":
            raise VaultError("completed execution receipt is missing")
        return None
    expected = {
        "task_id": record["task_id"], "evidence_id": event_id,
        **{key: intent[key] for key in fields - {"phase"}},
    }
    if set(payload) != {*expected, "result", "completed_at"} or any(
        payload[key] != value for key, value in expected.items()
    ):
        raise VaultError("execution receipt does not match its task intent")
    execution_result(payload["result"])
    return payload


def snapshot(vault: Vault, record: dict[str, Any]) -> TaskSnapshot:
    observations = []
    for event_id in sorted(record["executions"]):
        proof = execution_proof(vault, record, event_id)
        intent = record["executions"][event_id]
        result = execution_result(proof["result"]) if proof is not None else None
        observations.append(Evidence(
            evidence_id=event_id, revision=intent["revision"], check_id=intent["check_id"],
            outcome=result.outcome if result is not None else "unknown",
            origin="local-unittest" if result is not None else "unverified",
            artifact_digest=intent["artifact_digest"],
            tests_run=result.tests_run if result is not None else None,
            tests_skipped=result.tests_skipped if result is not None else None,
            tool_version=result.tool_version if result is not None else "",
            expected_failures=result.expected_failures if result is not None else None,
            sequence=intent["sequence"],
            checks_executed=result.checks_executed if result is not None else None,
            failures=result.failures if result is not None else None,
            errors=result.errors if result is not None else None,
        ))
    return TaskSnapshot(
        task_id=record["task_id"], revision=record["revision"],
        project=record["project"], tool=record["tool"], version=record["version"],
        goal=record["goal"], checks=tuple(sorted(record["checks"])),
        evidence=tuple(sorted(observations, key=lambda item: item.sequence)),
        facts=tuple(record["facts"]),
    )


def get_task(vault: Vault, task_id: str) -> TaskSnapshot:
    from .experience_store import RecordStore

    return snapshot(vault, load_task_record(RecordStore(vault), task_id))


def event_replayed(record: dict[str, Any], event_id: str, request: object) -> bool:
    require_id(event_id, "event_id")
    previous = record["events"].get(event_id)
    if previous is not None:
        if previous != digest(request):
            raise VaultError("event identity was reused with conflicting content")
        return True
    if len(record["events"]) >= MAX_EVENTS:
        raise VaultError("task event budget exhausted; start a new bounded task")
    return False


def create_task(
    vault: Vault, *, task_id: str, event_id: str, project: str, tool: str,
    version: str, goal: str, checks: dict[str, str], facts: list[str] | None = None,
) -> TaskSnapshot:
    from .experience_store import RecordStore

    require_active(vault)
    values = {
        "task_id": require_id(task_id, "task_id"),
        "project": require_id(project, "project"),
        "tool": require_id(tool, "tool"),
        "version": require_id(version, "version"),
        "goal": safe_text(vault, goal, "task goal"),
        "checks": _checks(vault, checks),
        "facts": list(require_strings(facts if facts is not None else [], "task facts", 0, 8, identifiers=True)),
    }
    if not version_matches(values["version"], values["version"]):
        raise VaultError("task version must specify numeric major.minor or major.minor.patch")
    require_id(event_id, "event_id")
    request = {"kind": "start", **values}
    store = RecordStore(vault)
    with store.transaction():
        if store.load("tasks", task_id) is not None:
            record = load_task_record(store, task_id)
            if event_replayed(record, event_id, request):
                return snapshot(vault, record)
            raise VaultError("task identity already exists; revise it instead")
        record = {
            "schema_version": 1, **values, "revision": 1,
            "events": {event_id: digest(request)}, "executions": {}, "proposals": {},
            "workspace_digest": None,
        }
        store.save("tasks", task_id, record)
        return snapshot(vault, record)


def revise_task(
    vault: Vault, task_id: str, *, event_id: str, expected_revision: int,
    relation: str, reason: str, goal: str | None = None, facts: list[str] | None = None,
) -> TaskSnapshot:
    from .experience_store import RecordStore

    require_revision(expected_revision)
    if relation not in ("correction", "requirement_change"):
        raise VaultError("revision relation must be correction or requirement_change")
    request = {
        "kind": "revise", "expected_revision": expected_revision, "relation": relation,
        "reason": safe_text(vault, reason, "revision reason"),
        "goal": safe_text(vault, goal, "task goal") if goal is not None else None,
        "facts": list(require_strings(facts, "task facts", 0, 8, identifiers=True)) if facts is not None else None,
    }
    store = RecordStore(vault)
    with store.transaction():
        record = load_task_record(store, task_id)
        if event_replayed(record, event_id, request):
            return snapshot(vault, record)
        if record["revision"] != expected_revision:
            raise VaultError("task revision changed; reload before revising")
        record["revision"] += 1
        if request["goal"] is not None:
            record["goal"] = request["goal"]
        if request["facts"] is not None:
            record["facts"] = request["facts"]
        for proposal in record["proposals"].values():
            if not isinstance(proposal, dict):
                raise VaultError("invalid proposal state in task record")
            if proposal.get("state") == "pending":
                proposal["state"] = "outdated"
            elif relation == "correction" and proposal.get("state") == "approved":
                proposal["state"] = "held"
        record["events"][event_id] = digest(request)
        store.save("tasks", task_id, record)
        return snapshot(vault, record)
