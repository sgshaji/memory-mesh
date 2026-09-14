"""Assisted host handoff. Session mappings are disposable, never evidence."""

from __future__ import annotations

import json

from . import config, fsutil
from .config import Vault, VaultError
from .experience import get_task
from .experience_types import digest, require_id, require_text


def capabilities() -> dict[str, object]:
    return {
        "schema_version": 1, "grade": "assisted",
        "automatic_task_observation": False,
        "verified_execution_adapter": "local-unittest",
        "semantic_review": "human-curator-review",
        "background_model_calls": False,
        "executes_recalled_commands": False,
        "distributed_writers": False,
    }


def _binding_path(vault: Vault, session_id: str):
    require_text(session_id, "session identifier", 200)
    return vault.path(config.SESSION_STATE) / f"v2-task-{digest(session_id)}.json"


def bind_session(vault: Vault, session_id: str, task_id: str) -> None:
    get_task(vault, task_id)
    path = _binding_path(vault, session_id)
    try:
        fsutil.agent_write(vault, path, json.dumps({"schema_version": 1, "task_id": task_id}) + "\n")
    except OSError as exc:
        raise VaultError("task exists but its session handoff could not be written") from exc


def bound_task(vault: Vault, session_id: str | None) -> str | None:
    if session_id is None:
        return None
    path = fsutil.ensure_within(vault, _binding_path(vault, session_id))
    if not path.exists():
        return None
    try:
        if path.is_symlink() or path.stat().st_size > 2048:
            raise VaultError("invalid session task handoff")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VaultError("session task handoff could not be read") from exc
    if (
        not isinstance(data, dict) or set(data) != {"schema_version", "task_id"}
        or type(data["schema_version"]) is not int or data["schema_version"] != 1
    ):
        raise VaultError("invalid session task handoff")
    return require_id(data["task_id"], "task_id")
