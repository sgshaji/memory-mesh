"""Explicit validation adapter with durable intent-before-execution accounting."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from . import execution_evidence
from .attestations import write_attestation
from .config import Vault, VaultError
from .experience import (
    MAX_EXECUTIONS, context_digest, event_replayed, execution_key,
    execution_proof, load_task_record, require_active,
)
from .experience_store import RecordStore
from .experience_types import (
    ExecutionResult, digest, execution_result, require_id, require_revision,
)


def execute_check(
    vault: Vault, task_id: str, *, event_id: str, expected_revision: int,
    check_id: str, workspace: Path, artifacts: list[str], start: str = ".",
    pattern: str = "test_*.py", timeout: float = 120,
) -> ExecutionResult:
    require_active(vault)
    require_revision(expected_revision)
    require_id(check_id, "check_id")
    root, directory = execution_evidence.validate_request(workspace, start, pattern, timeout)
    before = execution_evidence.fingerprint(root, artifacts)
    workspace_hash = digest(str(root))
    store = RecordStore(vault)
    with store.transaction():
        record = load_task_record(store, task_id)
        if record["tool"] != "python" or check_id not in record["checks"]:
            raise VaultError("only a declared Python unittest check can execute")
        if record["workspace_digest"] not in (None, workspace_hash):
            raise VaultError("task is bound to a different validation workspace")
        record["workspace_digest"] = workspace_hash
        request = {
            "kind": "check", "revision": expected_revision, "check_id": check_id,
            "workspace_digest": workspace_hash, "artifact_digest": before,
            "start": directory.relative_to(root).as_posix(), "pattern": pattern,
            "timeout": timeout,
        }
        if event_replayed(record, event_id, request):
            proof = execution_proof(vault, record, event_id)
            if proof is not None:
                if record["executions"][event_id]["phase"] != "complete":
                    record["executions"][event_id]["phase"] = "complete"
                    store.save("tasks", task_id, record)
                return execution_result(proof["result"])
            return ExecutionResult(
                "unknown", None, None, None, None, None, "", 0, "pending_execution",
            )
        if record["revision"] != expected_revision:
            raise VaultError("task revision changed; reload before executing checks")
        if len(record["executions"]) >= MAX_EXECUTIONS:
            raise VaultError("task execution budget exhausted")
        intent = {
            "check_id": check_id, "revision": expected_revision,
            "context_digest": context_digest(record), "request_hash": digest(request),
            "artifact_digest": before, "phase": "pending", "sequence": len(record["events"]) + 1,
        }
        record["events"][event_id] = digest(request)
        record["executions"][event_id] = intent
        store.save("tasks", task_id, record)

    result = execution_evidence.run_unittest(root, start=start, pattern=pattern, timeout=timeout)
    try:
        after = execution_evidence.fingerprint(root, artifacts)
    except VaultError:
        result = replace(result, outcome="unknown", reason="artifacts_unavailable")
    else:
        if before != after:
            result = replace(result, outcome="unknown", reason="artifacts_changed")
    payload = {
        "task_id": task_id, "evidence_id": event_id,
        **{key: value for key, value in intent.items() if key != "phase"},
        "result": asdict(result),
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with store.transaction():
        record = load_task_record(store, task_id)
        current = record["executions"].get(event_id)
        if not isinstance(current, dict) or current["request_hash"] != intent["request_hash"]:
            raise VaultError("execution intent changed while the check was running")
        write_attestation(vault, "execution", execution_key(task_id, event_id), payload)
        current["phase"] = "complete"
        store.save("tasks", task_id, record)
    return result
