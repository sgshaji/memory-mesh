"""Bounded metadata from an explicitly requested check, never a replayed lesson.

The worker discards test stdout/stderr before running project code. Only
counts and runtime metadata cross back; no test output is stored in the vault.
Approved project tests execute with the caller's privileges, not in a sandbox.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import VaultError
from .experience_types import ExecutionResult, execution_result, version_matches

MAX_ARTIFACT_BYTES = 1_048_576
MAX_TOTAL_ARTIFACT_BYTES = 8_388_608


def _workspace(root: Path) -> Path:
    try:
        resolved = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VaultError("validation workspace is unavailable") from exc
    if not resolved.is_dir():
        raise VaultError("validation workspace must be a directory")
    return resolved


def _contained(root: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise VaultError("validation paths must remain inside the workspace")
    try:
        resolved = (root / path).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise VaultError("validation path is unavailable or outside the workspace") from exc
    return resolved


def validate_request(root: Path, start: str, pattern: str, timeout: float) -> tuple[Path, Path]:
    if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise VaultError("validation timeout must be finite and within 300 seconds")
    if not pattern or len(pattern) > 100 or "/" in pattern or "\\" in pattern:
        raise VaultError("validation pattern must be a bounded filename pattern")
    workspace = _workspace(root)
    directory = _contained(workspace, start)
    if not directory.is_dir():
        raise VaultError("validation start must be a directory")
    return workspace, directory


def fingerprint(root: Path, names: list[str]) -> str:
    workspace = _workspace(root)
    if not 1 <= len(names) <= 32:
        raise VaultError("validation requires 1-32 explicit artifact files")
    files = [_contained(workspace, name) for name in names]
    if len(set(files)) != len(files):
        raise VaultError("validation artifacts must be unique")
    digest = hashlib.sha256()
    total = 0
    for path in sorted(files):
        try:
            if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
                raise VaultError("validation artifact is not a bounded regular file")
            with path.open("rb") as source:
                content = source.read(MAX_ARTIFACT_BYTES + 1)
        except OSError as exc:
            raise VaultError("validation artifact could not be read") from exc
        total += len(content)
        if len(content) > MAX_ARTIFACT_BYTES or total > MAX_TOTAL_ARTIFACT_BYTES:
            raise VaultError("validation artifacts exceed their byte budget")
        relative = path.relative_to(workspace).as_posix().encode("utf-8")
        digest.update(hashlib.sha256(relative).digest())
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def run_unittest(
    root: Path, *, start: str = ".", pattern: str = "test_*.py", timeout: float = 120,
) -> ExecutionResult:
    workspace, directory = validate_request(root, start, pattern, timeout)
    began = time.monotonic()

    def unknown(reason: str) -> ExecutionResult:
        return ExecutionResult(
            "unknown", None, None, None, None, None, "",
            round((time.monotonic() - began) * 1000), reason,
        )

    try:
        with tempfile.TemporaryDirectory(prefix="mm-bytecode-view-") as cache:
            completed = subprocess.run(
                [
                    sys.executable, "-I", "-B", "-X", f"pycache_prefix={cache}",
                    str(Path(__file__).with_name("_execution_runner.py")),
                    str(workspace), str(directory), pattern,
                ],
                cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        return unknown("timeout")
    except OSError as exc:
        raise VaultError("validation worker could not be started") from exc
    if completed.returncode != 0:
        return unknown("runner_failed")
    if len(completed.stdout) > 4096:
        return unknown("invalid_runner_result")
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, UnicodeDecodeError):
        return unknown("invalid_runner_result")
    counts = ("tests_run", "tests_skipped", "expected_failures", "failures", "errors")
    fields = {*counts, "protocol", "successful", "tool_version", "checks_executed", "boundary_violation"}
    if (
        not isinstance(payload, dict) or set(payload) != fields
        or type(payload.get("protocol")) is not int or payload["protocol"] != 1
        or any(type(payload.get(key)) is not int or payload[key] < 0 for key in counts)
        or type(payload.get("successful")) is not bool
        or not isinstance(payload.get("tool_version"), str)
        or not version_matches(payload["tool_version"], payload["tool_version"])
        or type(payload.get("boundary_violation")) is not bool
        or type(payload.get("checks_executed")) is not int
        or not 0 <= payload["checks_executed"] <= payload["tests_run"]
        or payload["successful"] != (payload["failures"] == 0 and payload["errors"] == 0)
    ):
        return unknown("invalid_runner_result")
    if payload["boundary_violation"]:
        return unknown("discovery_outside_workspace")
    outcome = "failed" if not payload["successful"] else "passed" if payload["checks_executed"] > 0 else "unknown"
    return execution_result({
        "outcome": outcome, **{key: payload[key] for key in counts},
        "tool_version": payload["tool_version"],
        "active_ms": round((time.monotonic() - began) * 1000),
        "reason": "no_executed_checks" if outcome == "unknown" else "completed",
        "checks_executed": payload["checks_executed"],
    })
