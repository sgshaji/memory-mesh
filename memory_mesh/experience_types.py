"""Side-effect-free vocabulary shared by the V2 ledger, policy, and adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .config import VaultError


def require_text(value: object, field: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VaultError(f"{field} requires non-empty text")
    if len(value) > limit or len(value.splitlines()) != 1:
        raise VaultError(f"{field} exceeds its single-line text limit")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise VaultError(f"{field} contains control characters")
    return value.strip()


def require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise VaultError(f"{field} requires a canonical identifier without surrounding whitespace")
    text = require_text(value, field, 100)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", text):
        raise VaultError(f"{field} requires an opaque ASCII identifier")
    return text


def require_revision(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise VaultError("task revision requires a positive integer")
    return value


def require_strings(
    value: object, field: str, minimum: int, maximum: int, *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise VaultError(f"{field} has an invalid item count")
    result = tuple(
        require_id(item, field) if identifiers else require_text(item, field, 250)
        for item in value
    )
    if len(set(result)) != len(result):
        raise VaultError(f"{field} contains duplicate items")
    return result


def digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def version_matches(requested: str, actual: str) -> bool:
    pattern = r"\d+\.\d+(?:\.\d+)?"
    if not re.fullmatch(pattern, requested) or not re.fullmatch(pattern, actual):
        return False
    wanted, observed = requested.split("."), actual.split(".")
    return observed[:len(wanted)] == wanted


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    revision: int
    check_id: str
    outcome: str
    origin: str
    artifact_digest: str
    tests_run: int | None
    tests_skipped: int | None
    tool_version: str
    expected_failures: int | None = 0
    sequence: int = 0
    checks_executed: int | None = None
    failures: int | None = None
    errors: int | None = None


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    revision: int
    project: str
    tool: str
    version: str
    goal: str
    checks: tuple[str, ...]
    evidence: tuple[Evidence, ...] = ()
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    outcome: str
    tests_run: int | None
    tests_skipped: int | None
    expected_failures: int | None
    failures: int | None
    errors: int | None
    tool_version: str
    active_ms: int
    reason: str
    checks_executed: int | None = None


def exercised_checks(
    tests_run: int | None, skipped: int | None, expected_failures: int | None,
    checks_executed: int | None,
) -> int | None:
    if checks_executed is not None:
        return checks_executed
    # Legacy receipts did not distinguish skipped methods from skip events.
    return tests_run if skipped == 0 and expected_failures == 0 else None


def execution_result(data: object) -> ExecutionResult:
    counts = ("tests_run", "tests_skipped", "expected_failures", "failures", "errors")
    fields = {*counts, "outcome", "tool_version", "active_ms", "reason"}
    if not isinstance(data, dict) or not fields <= data.keys() or set(data) - (fields | {"checks_executed"}):
        raise VaultError("invalid recorded execution result")
    values: dict[str, Any] = data
    if values["outcome"] not in ("passed", "failed", "unknown"):
        raise VaultError("invalid recorded execution outcome")
    for name in counts:
        value = values[name]
        if value is not None and (type(value) is not int or value < 0):
            raise VaultError("invalid recorded execution count")
    executed = values.get("checks_executed")
    if executed is not None and (
        type(executed) is not int or executed < 0
        or values["tests_run"] is None or executed > values["tests_run"]
    ):
        raise VaultError("invalid recorded executed-check count")
    if type(values["active_ms"]) is not int or values["active_ms"] < 0:
        raise VaultError("invalid recorded execution duration")
    if not isinstance(values["tool_version"], str):
        raise VaultError("invalid recorded execution runtime")
    if values["reason"] not in (
        "completed", "no_executed_checks", "timeout", "runner_failed",
        "invalid_runner_result", "artifacts_changed", "artifacts_unavailable",
        "pending_execution", "discovery_outside_workspace",
    ):
        raise VaultError("invalid recorded execution reason")
    if values["outcome"] != "unknown":
        if any(values[name] is None for name in counts):
            raise VaultError("completed execution is missing counts")
        if not version_matches(values["tool_version"], values["tool_version"]):
            raise VaultError("completed execution is missing its runtime version")
        succeeded = values["failures"] == 0 and values["errors"] == 0
        if succeeded != (values["outcome"] == "passed"):
            raise VaultError("execution outcome contradicts its recorded counts")
        exercised = exercised_checks(
            values["tests_run"], values["tests_skipped"], values["expected_failures"], executed,
        )
        if values["outcome"] == "passed" and (exercised is None or exercised <= 0):
            raise VaultError("successful execution did not exercise a verified check")
    return ExecutionResult(**values)
