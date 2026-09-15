"""Neutral, bounded V2 records; Markdown remains the only source of truth.

Transactions serialize cooperating processes on one machine. They are not
distributed/OneDrive multi-machine locks, nor rollback-capable transactions:
each successful save is independently atomic. Callers own semantic revisions,
idempotency and admission. Checksums detect corruption, not a malicious writer
that can replace both a record and its checksum.

Schema 1 stores the original key alongside ``data`` in its JSON block, avoiding
YAML coercion of scalar-looking IDs. Payloads use plain JSON dicts/lists and
scalars, with at most 32 nesting levels.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import frontmatter, fsutil, redact
from .config import EXPERIENCE_RECORDS, Vault, VaultError

MAX_RECORD_BYTES = 262144
_MAX_JSON_DEPTH = 32
_BUCKETS = frozenset(("tasks", "profile"))
_LOCK_FILENAMES = {
    "experience": "memory-mesh-v2-records.lock",
    "curator": "memory-mesh-v2-curator.lock",
}
_KEY = re.compile(r"[A-Za-z0-9._:-]{1,100}")
_FILENAME = re.compile(r"[0-9a-f]{64}\.md")
_BODY_START = "# Memory Mesh V2 record\n\n```json\n"
_BODY_END = "\n```\n"


class ExperienceError(VaultError):
    """A safe record-store diagnostic, without record content."""


class ExperienceConflict(ExperienceError):
    """An operation conflicts with the required transaction ownership."""


class ExperienceBusy(ExperienceError):
    """The local exclusive lock could not be acquired before its deadline."""


class ExperienceLimit(ExperienceError):
    """A record exceeds a byte, JSON complexity or nesting limit."""


def _checked_path(vault: Vault, path: Path) -> Path:
    try:
        resolved = fsutil.ensure_within(vault, path)
    except (fsutil.PathTraversalError, OSError, RuntimeError):
        raise ExperienceError("The record store path is unsafe.") from None
    if resolved != path:
        raise ExperienceError("The record store path must not redirect through links.")
    return resolved


def _deadline(timeout: float) -> float:
    if type(timeout) not in (int, float):
        raise ExperienceError("The lock timeout must be finite and nonnegative.")
    try:
        timeout = float(timeout)
    except OverflowError:
        raise ExperienceError("The lock timeout must be finite and nonnegative.") from None
    if not math.isfinite(timeout) or timeout < 0:
        raise ExperienceError("The lock timeout must be finite and nonnegative.")
    return time.monotonic() + timeout


def _wait(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExperienceBusy("The local exclusive lock is busy; locks are not reentrant.")
    time.sleep(min(remaining, 0.025))


def _os_lock(fd: int, *, release: bool = False) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
        elif os.name == "posix":
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            raise ExperienceError("Local record locking is unsupported on this platform.")
    except OSError as error:
        if not release and error.errno in (errno.EACCES, errno.EAGAIN, errno.EINTR):
            return False
        raise ExperienceError("The local record lock operation failed.") from None
    return True


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        raise ExperienceError("The record store file could not be closed.") from None


@contextmanager
def exclusive_lock(
    vault: Vault, name: str = "experience", timeout: float = 2.0
) -> Iterator[None]:
    """Hold an allowlisted local OS lock: ``experience`` or ``curator``.

    Same-name acquisitions are not reentrant and raise ExperienceBusy at the
    deadline. Acquire curator before experience when both are needed. Holding
    this context alone does not authorize RecordStore.save; use transaction.
    Lock files remain in _meta/session-state and are never deleted.
    """
    if type(name) is not str or name not in _LOCK_FILENAMES:
        raise ExperienceError("The local lock name is invalid.")
    deadline = _deadline(timeout)
    path = _checked_path(vault, vault.root / "_meta" / "session-state" / _LOCK_FILENAMES[name])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(_checked_path(vault, path), flags, 0o600)
    except OSError:
        raise ExperienceError("The local record lock could not be opened.") from None
    locked = False
    try:
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ExperienceError("The record lock must be a regular file without hard links.")
            while not _os_lock(fd):
                _wait(deadline)
            locked = True
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
        except OSError:
            raise ExperienceError("The local record lock could not be initialized.") from None
        yield
    finally:
        try:
            if locked:
                _os_lock(fd, release=True)
        finally:
            _close(fd)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExperienceError("A record contains duplicate JSON keys.")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> Any:
    raise ExperienceError("A record contains a non-finite JSON number.")


def _json_text(data: dict[str, Any]) -> str:
    chunks = []
    size = 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    try:
        for chunk in encoder.iterencode(data):
            size += len(chunk.encode("utf-8"))
            if size > MAX_RECORD_BYTES:
                raise ExperienceLimit("The record exceeds the byte limit.")
            chunks.append(chunk)
    except (TypeError, ValueError, RecursionError):
        raise ExperienceError("The record cannot be encoded as JSON.") from None
    return "".join(chunks)


class RecordStore:
    """Records in the exclusively owned projects/_memory-mesh-v2/records tree.

    Reads never create directories or acquire a write lock. Missing records
    return None; invalid records always raise. Transactions are non-reentrant
    and save is allowed only on the owning instance, process and thread.
    """

    def __init__(self, vault: Vault):
        self.vault = vault
        self._mutex = threading.Lock()
        self._owner: tuple[int, int] | None = None

    def _bucket_path(self, bucket: str) -> Path:
        if type(bucket) is not str or bucket not in _BUCKETS:
            raise ExperienceError("The record bucket is invalid.")
        return _checked_path(
            self.vault,
            self.vault.path(EXPERIENCE_RECORDS) / bucket
        )

    def _reject_sensitive(self, text: str) -> None:
        if len(text) > MAX_RECORD_BYTES:
            raise ExperienceLimit("The record exceeds the byte limit.")
        try:
            if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
                raise ExperienceLimit("The record exceeds the byte limit.")
            _, findings = redact.redact(text, self.vault)
        except (OSError, UnicodeError, re.error, IndexError):
            raise ExperienceError("The record privacy check could not be completed.") from None
        if findings:
            raise ExperienceError("Sensitive record content is not permitted.")

    def _validate_key(self, key: str) -> None:
        if type(key) is not str or not _KEY.fullmatch(key) or key in (".", ".."):
            raise ExperienceError("The record key is invalid.")
        self._reject_sensitive(key)

    def record_path(self, bucket: str, key: str) -> Path:
        """Return the validated path without creating it; key case is significant."""
        directory = self._bucket_path(bucket)
        self._validate_key(key)
        digest = hashlib.sha256(key.encode("ascii")).hexdigest()
        return _checked_path(self.vault, directory / (digest + ".md"))

    def record_ref(self, bucket: str, key: str) -> str:
        """Return the canonical vault-relative reference, without .md."""
        path = self.record_path(bucket, key)
        return path.relative_to(self.vault.root).with_suffix("").as_posix()

    def _copy_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        if type(data) is not dict:
            raise ExperienceError("The record payload must be a JSON object.")
        ancestors: set[int] = set()
        remaining = MAX_RECORD_BYTES

        def spend(size: int) -> None:
            nonlocal remaining
            remaining -= size
            if remaining < 0:
                raise ExperienceLimit("The record exceeds the JSON complexity limit.")

        def copy(value: Any, depth: int) -> Any:
            if depth > _MAX_JSON_DEPTH:
                raise ExperienceLimit("The record exceeds the JSON nesting limit.")
            spend(1)
            kind = type(value)
            if value is None or kind in (bool, int):
                return value
            if kind is float:
                if not math.isfinite(value):
                    raise ExperienceError("The record contains a non-finite JSON number.")
                return value
            if kind is str:
                spend(len(value))
                self._reject_sensitive(value)
                return value
            if kind not in (dict, list):
                raise ExperienceError("The record contains a non-JSON value.")
            identity = id(value)
            if identity in ancestors:
                raise ExperienceError("The record payload contains a cycle.")
            ancestors.add(identity)
            try:
                if kind is list:
                    return [copy(child, depth + 1) for child in value]
                result = {}
                for key, child in value.items():
                    if type(key) is not str:
                        raise ExperienceError("JSON object keys must be strings.")
                    spend(len(key) + 1)
                    self._reject_sensitive(key)
                    if type(child) is str:
                        self._reject_sensitive(key + ": " + child)
                    result[key] = copy(child, depth + 1)
                return result
            finally:
                ancestors.remove(identity)

        try:
            return copy(data, 0)
        except RuntimeError:
            raise ExperienceError("The record payload changed during validation.") from None

    def _document(self, bucket: str, key: str, data: dict[str, Any]) -> str:
        payload = _json_text({"key": key, "data": self._copy_payload(data)})
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        meta = {
            "type": "project",
            "schema_version": 1,
            "bucket": bucket,
            "payload_sha256": "sha256:" + checksum,
        }
        text = frontmatter.compose(meta, _BODY_START + payload + _BODY_END)
        if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ExperienceLimit("The record exceeds the byte limit.")
        return text

    def _read_bytes(self, path: Path) -> bytes | None:
        path = _checked_path(self.vault, path)
        from .curator.transaction import current_transaction

        curation = current_transaction(self.vault)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            if curation is not None:
                curation.observe(path, None)
            return None
        except OSError:
            raise ExperienceError("The record could not be opened.") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ExperienceError("The record must be a regular file without hard links.")
            if info.st_size > MAX_RECORD_BYTES:
                raise ExperienceLimit("The record exceeds the byte limit.")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise ExperienceLimit("The record exceeds the byte limit.")
            if curation is not None:
                curation.observe(path, raw)
            return raw
        except OSError:
            raise ExperienceError("The record could not be read.") from None
        finally:
            _close(fd)

    def _load_record(
        self, path: Path, bucket: str, expected_key: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        raw = self._read_bytes(path)
        if raw is None:
            return None
        try:
            text = raw.decode("utf-8")
            if not text.startswith("---\n") or text.find("\n---\n", 4, 2048) == -1:
                raise ExperienceError("The record metadata is malformed.")
            meta, body = frontmatter.parse(text)
        except (ValueError, RecursionError):
            raise ExperienceError("The record metadata is malformed.") from None
        if (
            set(meta) != {"type", "schema_version", "bucket", "payload_sha256"}
            or meta["type"] != "project"
            or type(meta["schema_version"]) is not int
            or meta["schema_version"] != 1
            or meta["bucket"] != bucket
            or text != frontmatter.compose(meta, body)
        ):
            raise ExperienceError("The record metadata does not match its schema or bucket.")
        if not body.startswith(_BODY_START) or not body.endswith(_BODY_END):
            raise ExperienceError("The record JSON block is malformed.")
        payload = body[len(_BODY_START) : -len(_BODY_END)]
        checksum = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if meta["payload_sha256"] != checksum:
            raise ExperienceError("The record checksum does not match its payload.")
        try:
            envelope = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except RecursionError:
            raise ExperienceLimit("The record exceeds the JSON nesting limit.") from None
        except ValueError:
            raise ExperienceError("The record JSON block is malformed.") from None
        if type(envelope) is not dict or set(envelope) != {"key", "data"}:
            raise ExperienceError("The record envelope is malformed.")
        key = envelope["key"]
        if self.record_path(bucket, key) != path or (expected_key is not None and key != expected_key):
            raise ExperienceError("The record identity does not match its path.")
        return key, self._copy_payload(envelope["data"])

    def load(self, bucket: str, key: str) -> dict[str, Any] | None:
        """Load an isolated payload, or None for a genuinely absent record."""
        result = self._load_record(self.record_path(bucket, key), bucket, key)
        return None if result is None else result[1]

    def save(self, bucket: str, key: str, data: dict[str, Any]) -> Path:
        """Atomically replace a valid record under this instance's transaction."""
        if self._owner != (os.getpid(), threading.get_ident()):
            raise ExperienceConflict("Saving requires this instance's active transaction.")
        path = self.record_path(bucket, key)
        text = self._document(bucket, key, data)
        self._load_record(path, bucket, key)
        try:
            return fsutil.agent_write(self.vault, _checked_path(self.vault, path), text)
        except (OSError, fsutil.PathTraversalError, fsutil.WriteBoundaryError):
            raise ExperienceError("The record could not be written atomically.") from None

    def iter_records(self, bucket: str) -> Iterator[tuple[str, dict[str, Any]]]:
        """Scan one bucket for maintenance only; this is not a transaction snapshot."""
        directory = self._bucket_path(bucket)
        try:
            if not directory.exists():
                return
            for path in directory.iterdir():
                if path.suffix.lower() != ".md":
                    continue
                if not _FILENAME.fullmatch(path.name):
                    raise ExperienceError("The record filename is not canonical.")
                result = self._load_record(path, bucket)
                if result is not None:
                    yield result
        except OSError:
            raise ExperienceError("The record bucket could not be read.") from None

    @contextmanager
    def transaction(self, timeout: float = 2.0) -> Iterator[RecordStore]:
        """Acquire a bounded, process-safe local lock; never delete its stable inode."""
        deadline = _deadline(timeout)
        owner = (os.getpid(), threading.get_ident())
        if self._owner == owner:
            raise ExperienceConflict("Record store transactions are not reentrant.")
        while not self._mutex.acquire(blocking=False):
            _wait(deadline)
        try:
            with exclusive_lock(
                self.vault, name="experience", timeout=max(0.0, deadline - time.monotonic())
            ):
                self._owner = owner
                try:
                    yield self
                finally:
                    self._owner = None
        finally:
            self._mutex.release()
