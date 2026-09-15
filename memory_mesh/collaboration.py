"""Local many-contributor, designated-curator policy.

Identity is a convenience guard, NOT authentication: a user controlling the
vault can change its configuration, Git identity, or MEMORY_MESH_ACTOR. The
environment override is explicit; otherwise repository-local user.email (then
user.name) identifies the actor. There is no distributed consensus across
clones or synchronization services.
"""

from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from typing import Iterator

from . import gitutil
from .config import Vault, VaultError
from .experience_store import exclusive_lock
from .feedback_config import load_settings

ACTOR_ENV = "MEMORY_MESH_ACTOR"


class CuratorPermissionError(VaultError):
    """Capture remains available, but this actor cannot curate."""


def current_actor(vault: Vault) -> str | None:
    override = os.environ.get(ACTOR_ENV)
    if override is not None:
        identity = override.strip()
        if not identity or len(identity) > 200 or any(ord(c) < 32 for c in override):
            raise CuratorPermissionError(f"{ACTOR_ENV} must contain one nonempty identity")
        return identity
    if not gitutil.available(vault):
        return None
    for field in ("user.email", "user.name"):
        result = gitutil._git(vault, "config", "--local", "--get", field)
        if result.returncode == 0 and result.stdout.strip():
            identity = result.stdout.strip()
            if len(identity) > 200 or any(ord(c) < 32 for c in identity):
                raise CuratorPermissionError("local Git curator identity must be a single line")
            return identity
    return None


def require_curator(vault: Vault) -> str | None:
    policy = load_settings(vault).curation
    if policy.mode == "single-user":
        return None
    actor = current_actor(vault)
    if actor is None or actor.casefold() != policy.curator.strip().casefold():
        raise CuratorPermissionError(
            "designated curator identity does not match; contributors may still capture "
            f"candidates, episodes and feedback (identity: local Git or {ACTOR_ENV})"
        )
    return actor


@contextmanager
def curator_lock(vault: Vault, *, existing_lock: bool = False) -> Iterator[None]:
    """Authorize and reuse the V2 OS lock (curator before experience).

    existing_lock=True is an assertion by an internal caller that it already
    owns experience_store.exclusive_lock(vault, "curator"). It MUST be nested
    inside that context, never used as a user-controlled bypass or after
    acquiring the experience lock. The legacy OS lock is not reentrant.
    """
    require_curator(vault)
    policy = load_settings(vault).curation
    context = nullcontext() if existing_lock else exclusive_lock(
        vault, "curator", timeout=policy.lock_timeout_seconds
    )
    with context:
        require_curator(vault)
        yield
