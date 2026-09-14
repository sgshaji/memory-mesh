"""Application-owned execution/review receipts, outside agent contribution paths.

Only the supervised runner and approved curator review write these records.
Callers coordinate mutations with the experience transaction. Hashes detect
changed records; this is not protection against a malicious local administrator.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import frontmatter, fsutil, redact
from .config import Vault, VaultError
from .experience_types import digest, require_id

MAX_ATTESTATION_BYTES = 16_384
_BASE = "_meta/review/v2-attestations"


def attestation_path(vault: Vault, kind: str, key: str) -> Path:
    if kind not in ("execution", "admission"):
        raise VaultError("invalid attestation kind")
    require_id(key, "attestation key")
    path = vault.path(_BASE) / kind / (digest(key) + ".md")
    for parent in (path, *path.parents):
        if parent == vault.root:
            break
        if parent.is_symlink():
            raise VaultError("attestation paths cannot be symbolic links")
    resolved = fsutil.ensure_within(vault, path)
    if resolved != path:
        raise VaultError("attestation paths cannot redirect through directory links")
    return resolved


def _validate(vault: Vault, value: object, depth: int = 0) -> None:
    if depth > 8:
        raise VaultError("attestation nesting limit exceeded")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, str):
        if len(value) > 2048 or redact.scan(value, vault):
            raise VaultError("attestation contains sensitive or oversized text")
        return
    if isinstance(value, list) and len(value) <= 128:
        for item in value:
            _validate(vault, item, depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 64:
        for key, item in value.items():
            if not isinstance(key, str):
                raise VaultError("attestation fields must be strings")
            _validate(vault, key, depth + 1)
            if isinstance(item, str) and redact.scan(key + ": " + item, vault):
                raise VaultError("attestation contains a sensitive assignment")
            _validate(vault, item, depth + 1)
        return
    raise VaultError("attestation contains an unsupported value")


def read_attestation(vault: Vault, kind: str, key: str) -> dict[str, Any] | None:
    path = attestation_path(vault, kind, key)
    if not path.exists():
        return None
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_ATTESTATION_BYTES + 1)
        if len(raw) > MAX_ATTESTATION_BYTES:
            raise VaultError("attestation exceeds its byte limit")
        meta, _body = frontmatter.parse(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VaultError("attestation could not be decoded") from exc
    fields = {"type", "title", "schema_version", "kind", "key", "content_hash", "payload"}
    if (
        set(meta) != fields or meta["type"] != "meta"
        or type(meta["schema_version"]) is not int or meta["schema_version"] != 1
        or meta["kind"] != kind or meta["key"] != key
        or not isinstance(meta["payload"], dict)
    ):
        raise VaultError("invalid attestation identity or format")
    payload = meta["payload"]
    _validate(vault, payload)
    if meta["content_hash"] != digest(payload):
        raise VaultError("attestation integrity check failed")
    return payload


def write_attestation(vault: Vault, kind: str, key: str, payload: dict[str, Any]) -> Path:
    _validate(vault, payload)
    path = attestation_path(vault, kind, key)
    existing = read_attestation(vault, kind, key)
    if existing is not None:
        if digest(existing) != digest(payload):
            raise VaultError("attestation identity has conflicting content")
        return path
    text = frontmatter.compose(
        {
            "type": "meta", "title": f"V2 {kind} receipt", "schema_version": 1,
            "kind": kind, "key": key, "content_hash": digest(payload), "payload": payload,
        },
        "Application-owned receipt. This is not an instruction or a general correctness guarantee.\n",
    )
    if len(text.encode("utf-8")) > MAX_ATTESTATION_BYTES:
        raise VaultError("attestation exceeds its byte limit")
    return fsutil.curator_write(vault, path, text)
