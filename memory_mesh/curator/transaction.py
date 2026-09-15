"""Immediate local curation with optimistic inputs and write-ahead recovery.

Wrap the complete read/decide/write run, not just its final writes. Normal
curator inputs are snapshotted at entry; load_note also registers exact bytes
read. Curator/atomic writes and appends to owned paths are intercepted. Replace
direct rename/unlink calls with fsutil.curator_rename/curator_unlink.

V2 backends join through the same fsutil write helpers. Record paths must stay
in config.CURATOR_WRITABLE. Register each bounded backend read with observe,
including absent files; do not replace an existing snapshot after a reread.
RecordStore.transaction contexts go inside this boundary so the experience
lock is released before publication or recovery reacquires it. Include
publishable_paths in the Git change set, not just the caller's report.

Git command failures poison the enclosing transaction, even if a caller only
logs its failed CommitResult. Proposed Git stages are isolated from the user's
index. Exiting a failed boundary restores owned post-images, including archived
reviews. A successful Git commit is reconciled into the real index with a
non-destructive Git merge; reconciliation conflicts remain explicitly pending.
A vault without Git remains explicitly local-only.

All registered inputs are checked before the first mutation and at publication
or successful exit; each intervening write checks its target's exact post-image.
After the first write, drift in a different input may therefore be detected only
at a later read or final barrier, which aborts and rolls back the whole run.
Writes/readbacks are provisional and immediately visible. Readers that need a
consistent curated view must share the curator lock; a view including V2 records
or receipts also needs the experience lock, acquired second. This is not
snapshot isolation, and arbitrary readers can observe changes later rolled back.
A crash leaves a durable journal in
_meta/session-state/curation-transactions; the next curator rolls back only
bytes still matching its own post-images. Conflicting sources, proposed bytes
and supplied decision payloads remain there for explicit review. Cooperating
processes use the existing local OS lock. Arbitrary editors do not participate
in that lock: hashes detect observed divergence, not an OS-level compare/swap.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .. import config, fsutil
from ..collaboration import curator_lock, require_curator
from ..config import Vault, VaultError
from ..experience_store import exclusive_lock
from ..feedback_config import load_settings

JOURNAL_DIR = "_meta/session-state/curation-transactions"
_TERMINAL = {"committed", "rolled-back", "acknowledged"}


class CurationConflict(VaultError):
    def __init__(self, path: Path, journal: Path):
        self.path, self.journal = path, journal
        super().__init__(f"curation conflict at {path}; preserved inputs and decision: {journal}")


class CurationRecoveryError(VaultError):
    pass


class CurationPublicationError(VaultError):
    """Git publication failed; the enclosing run must not finalize its writes."""

    def __init__(self, message: str, journal: Path):
        self.journal = journal
        super().__init__(f"curation publication failed: {message}; recovery journal: {journal}")


@dataclass(frozen=True)
class RecoveryResult:
    transaction_id: str
    state: str
    journal: Path
    conflicts: tuple[str, ...] = ()


def _encode(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _decode(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CurationRecoveryError("invalid recovery bytes")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CurationRecoveryError("invalid recovery bytes") from exc


def _hash(data: bytes | None) -> str | None:
    return None if data is None else fsutil.content_hash(data)


def _read(path: Path) -> bytes | None:
    try:
        return fsutil.read_regular_bytes(path)
    except FileNotFoundError:
        return None


def _needs_experience_lock(relative: str) -> bool:
    return fsutil._allowed(relative, (
        config.EXPERIENCE_RECORDS, "_meta/review/v2-attestations",
    ))


@contextmanager
def _experience_guard(vault: Vault, paths: Iterable[str]) -> Iterator[None]:
    if any(_needs_experience_lock(path) for path in paths):
        timeout = load_settings(vault).curation.lock_timeout_seconds
        with exclusive_lock(vault, "experience", timeout=timeout):
            yield
    else:
        yield


def _journal_path(vault: Vault, transaction_id: str) -> Path:
    if len(transaction_id) != 32 or any(c not in "0123456789abcdef" for c in transaction_id):
        raise CurationRecoveryError("invalid curation transaction ID")
    return fsutil.checked_regular_path(vault, vault.path(JOURNAL_DIR) / f"{transaction_id}.json")


def _save(vault: Vault, journal: dict) -> Path:
    path = _journal_path(vault, journal["id"])
    data = (json.dumps(journal, ensure_ascii=True, allow_nan=False, sort_keys=True) + "\n").encode()
    fsutil._atomic_write_bytes(path, data)
    return path


def _relative_path(vault: Vault, relative: object) -> Path:
    if (not isinstance(relative, str) or not relative
            or "\\" in relative or ":" in relative or relative.startswith("/")
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise CurationRecoveryError("unsafe path in curation journal")
    return vault.path(relative)


def _operation_path(vault: Vault, relative: object) -> Path:
    return fsutil._check(vault, _relative_path(vault, relative), config.CURATOR_WRITABLE, "curator")


def _load(vault: Vault, path: Path) -> dict:
    try:
        path = fsutil.checked_regular_path(vault, path)
        if path.stat().st_size > 64 * 1024 * 1024:
            raise CurationRecoveryError("curation journal exceeds recovery size limit")
        journal = json.loads(fsutil.read_regular_bytes(path))
        if (not isinstance(journal, dict) or type(journal.get("version")) is not int
                or journal.get("version") != 1
                or journal.get("id") != path.stem
                or journal.get("state") not in _TERMINAL | {"active", "committing", "rolling-back", "conflict"}
                or not isinstance(journal.get("operations"), list)
                or not isinstance(journal.get("conflicts"), list)):
            raise CurationRecoveryError("invalid curation journal")
        for field in ("git_isolated_index", "git_commit_started", "git_commit_finished", "git_index_reconciled"):
            if field in journal and type(journal[field]) is not bool:
                raise CurationRecoveryError("invalid Git recovery marker")
        for operation in journal["operations"]:
            if journal["state"] not in _TERMINAL | {"conflict"}:
                _operation_path(vault, operation["path"])
            else:
                _relative_path(vault, operation["path"])
            if type(operation.get("rolled_back", False)) is not bool:
                raise CurationRecoveryError("invalid curation rollback marker")
            for key in ("before", "after"):
                if _hash(_decode(operation[key])) != operation[key + "_hash"]:
                    raise CurationRecoveryError("corrupted curation recovery bytes")
        for conflict in journal["conflicts"]:
            _relative_path(vault, conflict["path"])
            if _hash(_decode(conflict["observed"])) != conflict["observed_hash"]:
                raise CurationRecoveryError("corrupted curation conflict bytes")
        return journal
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise CurationRecoveryError(f"cannot read curation journal {path.name}") from exc


def _git_committed(vault: Vault, journal: dict, *, confirmed_git_stopped: bool = False) -> bool:
    from .. import gitutil

    if not gitutil.available(vault):
        raise CurationRecoveryError(
            "Git commit outcome is unknown; restore local Git access before recovery"
        )
    try:
        commit = gitutil.transaction_commit(vault, journal["id"])
    except gitutil.GitError as exc:
        raise CurationRecoveryError("Git commit outcome could not be checked") from exc
    if commit is None:
        if journal.get("git_commit_started") and not journal.get("git_commit_finished"):
            if not confirmed_git_stopped:
                raise CurationRecoveryError(
                    "Git commit may still be running; confirm it has stopped before retrying recovery"
                )
            journal["git_commit_finished"] = True
            _save(vault, journal)
        return False
    journal["git_commit"] = commit
    if journal.get("git_isolated_index") and not journal.get("git_index_reconciled"):
        try:
            gitutil.reconcile_index(vault, commit)
        except (OSError, gitutil.GitError) as exc:
            journal["git_index_error"] = str(exc)
            journal["state"] = "conflict"
            _save(vault, journal)
            return True
        journal["git_index_reconciled"] = True
        journal.pop("git_index_error", None)
    journal["state"] = "conflict" if journal["conflicts"] else "committed"
    journal["publication"] = "committed"
    _save(vault, journal)
    return True


def _rollback(vault: Vault, journal: dict, *, confirmed_git_stopped: bool = False) -> RecoveryResult:
    with _experience_guard(vault, (operation["path"] for operation in journal["operations"])):
        return _rollback_files(vault, journal, confirmed_git_stopped=confirmed_git_stopped)


def _rollback_files(vault: Vault, journal: dict, *, confirmed_git_stopped: bool = False) -> RecoveryResult:
    path = _journal_path(vault, journal["id"])
    if journal["state"] == "committing" and _git_committed(
        vault, journal, confirmed_git_stopped=confirmed_git_stopped,
    ):
        return RecoveryResult(
            journal["id"], journal["state"], path,
            tuple(sorted({item["path"] for item in journal["conflicts"]})),
        )
    journal["state"] = "rolling-back"
    _save(vault, journal)
    blocked: set[str] = set()
    for operation in reversed(journal["operations"]):
        relative = operation["path"]
        if relative in blocked or operation.get("rolled_back"):
            continue
        target = _operation_path(vault, relative)
        before, after = _decode(operation["before"]), _decode(operation["after"])
        actual = _read(target)
        if actual == before:
            operation["rolled_back"] = True
            _save(vault, journal)
            continue
        if actual != after:
            blocked.add(relative)
            journal["conflicts"].append({
                "path": relative, "expected_hash": _hash(after),
                "observed": _encode(actual), "observed_hash": _hash(actual),
            })
            _save(vault, journal)
            continue
        try:
            if before is None:
                fsutil._atomic_unlink(target, expected_hash=_hash(after))
            else:
                fsutil._atomic_write_bytes(target, before, expected_hash=_hash(after))
            operation["rolled_back"] = True
            _save(vault, journal)
        except fsutil.WriteConflictError:
            actual = _read(target)
            blocked.add(relative)
            journal["conflicts"].append({
                "path": relative, "expected_hash": _hash(after),
                "observed": _encode(actual), "observed_hash": _hash(actual),
            })
            _save(vault, journal)
    journal["state"] = "conflict" if journal["conflicts"] else "rolled-back"
    _save(vault, journal)
    conflicts = tuple(sorted({item["path"] for item in journal["conflicts"]}))
    return RecoveryResult(journal["id"], journal["state"], path, conflicts)


def _recover_locked(vault: Vault, *, confirmed_git_stopped: bool = False) -> list[RecoveryResult]:
    directory = vault.path(JOURNAL_DIR)
    fsutil.checked_regular_path(vault, directory / ".path-check")
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        journal = _load(vault, path)
        if journal["state"] in _TERMINAL:
            continue
        if journal["state"] == "conflict" and journal.get("git_index_error"):
            with _experience_guard(vault, (item["path"] for item in journal["operations"])):
                if not _git_committed(vault, journal, confirmed_git_stopped=confirmed_git_stopped):
                    raise CurationRecoveryError("published Git commit cannot be located; index left unchanged")
            results.append(RecoveryResult(
                journal["id"], journal["state"], path,
                tuple(sorted({item["path"] for item in journal["conflicts"]})),
            ))
            continue
        if journal["state"] == "conflict":
            results.append(RecoveryResult(
                journal["id"], "conflict", path,
                tuple(sorted({item["path"] for item in journal["conflicts"]})),
            ))
        else:
            results.append(_rollback(vault, journal, confirmed_git_stopped=confirmed_git_stopped))
    return results


def inspect_curation_transactions(vault: Vault, *, pending_only: bool = True) -> list[RecoveryResult]:
    """Read recovery state without applying recovery or requiring writer identity."""
    directory = vault.path(JOURNAL_DIR)
    fsutil.checked_regular_path(vault, directory / ".path-check")
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        journal = _load(vault, path)
        if pending_only and journal["state"] in _TERMINAL:
            continue
        results.append(RecoveryResult(
            journal["id"], journal["state"], path,
            tuple(sorted({item["path"] for item in journal["conflicts"]})),
        ))
    return results


def recover_curation_transactions(
    vault: Vault, *, existing_lock: bool = False, confirmed_git_stopped: bool = False,
) -> list[RecoveryResult]:
    """Recover interrupted runs without replacing competing files/index stages.

    confirmed_git_stopped is an explicit operator assertion, never an automatic
    retry default: use it only after verifying all potentially involved native
    Git processes have stopped. An unconfirmed in-flight commit blocks rollback.
    """
    if type(confirmed_git_stopped) is not bool:
        raise CurationRecoveryError("Git process confirmation must be an explicit boolean")
    with curator_lock(vault, existing_lock=existing_lock):
        return _recover_locked(vault, confirmed_git_stopped=confirmed_git_stopped)


def acknowledge_curation_conflict(vault: Vault, transaction_id: str) -> Path:
    """Explicitly keep current files after human review; retain all evidence.

    This does not apply the old decision or resolve Git merges. A fresh curator
    run must recompute its decisions against current bytes.
    """
    with curator_lock(vault):
        path = _journal_path(vault, transaction_id)
        journal = _load(vault, path)
        if journal["state"] != "conflict":
            raise CurationRecoveryError("only reviewed conflicts can be acknowledged")
        journal["state"] = "acknowledged"
        return _save(vault, journal)


class CurationTransaction:
    def __init__(self, vault: Vault, run_id: str | None = None):
        self.vault = vault
        self.owner = (os.getpid(), threading.get_ident())
        self.observed: dict[Path, bytes | None] = {}
        self.original: dict[Path, bytes | None] = {}
        self.failure: VaultError | None = None
        self.journal = {
            "version": 1, "id": uuid.uuid4().hex, "run_id": run_id,
            "state": "active", "operations": [], "decisions": [], "conflicts": [],
        }
        self.saved = False
        self.closed = False
        self._publishing = False

    @property
    def journal_path(self) -> Path:
        return _journal_path(self.vault, self.journal["id"])

    @property
    def changed_paths(self) -> set[str]:
        """Net writes owned by this run, excluding pre-existing user dirt."""
        return {
            self._relative(path) for path, value in self.observed.items()
            if value != self.original[path]
        }

    @property
    def publishable_paths(self) -> set[str]:
        """Durable changed paths; generated context packs stay local-only."""
        return {
            path for path in self.changed_paths
            if not fsutil._allowed(path, (config.CONTEXT_PACKS,))
        }

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.vault.root).as_posix()

    def _owned(self) -> None:
        if self.closed or self.owner != (os.getpid(), threading.get_ident()):
            raise CurationRecoveryError("curation transaction is not owned by this execution")

    def handles(self, path: Path) -> bool:
        absolute = fsutil._comparison_path(Path(os.path.abspath(path)))
        try:
            rel = absolute.relative_to(fsutil._comparison_path(self.vault.root)).as_posix()
        except ValueError:
            return False
        return fsutil._allowed(rel, config.CURATOR_WRITABLE)

    def _path(self, path) -> Path:
        if isinstance(path, str):
            path = self.vault.path(path)
        return fsutil.checked_regular_path(self.vault, Path(path))

    def watch(self, path) -> str | None:
        """Capture input bytes BEFORE using them to make a decision."""
        self._owned()
        path = self._path(path)
        if path not in self.observed:
            self.observed[path] = self.original[path] = _read(path)
        return _hash(self.observed[path])

    def observe(self, path: Path | str, data: bytes | None) -> str | None:
        """Register exact bytes already read by a bounded, validated backend.

        Call before interpreting/returning the read, including None for a
        genuinely missing file. This does not reread the file or grant write
        permission. Never use it to bless bytes after a bypassed raw write.
        """
        self._owned()
        if self.failure is not None:
            raise self.failure
        if data is not None and not isinstance(data, bytes):
            raise CurationRecoveryError("observed input must be bytes or None")
        path = self._path(path)
        if path in self.observed:
            if data != self.observed[path]:
                self._conflict(path, data)
        else:
            self.observed[path] = self.original[path] = data
        return _hash(data)

    def read_bytes(self, path, *, missing_ok: bool = False) -> bytes | None:
        self.watch(path)
        path = self._path(path)
        value = _read(path)
        if value != self.observed[path]:
            self._conflict(path, value)
        if value is None and not missing_ok:
            raise FileNotFoundError(path)
        return value

    def _persist(self) -> None:
        _save(self.vault, self.journal)
        self.saved = True

    @contextmanager
    def publication_lock(self) -> Iterator[None]:
        """Serialize V2 publication against cooperating record/receipt writers.

        Enter only after all inner RecordStore.transaction contexts have
        exited. The outer curator lock is already held. Nested publication
        barriers reuse this instance's known ownership, not another OS lock.
        """
        self._owned()
        if self._publishing:
            yield
            return
        paths = [self._relative(path) for path in self.observed]
        if not any(_needs_experience_lock(path) for path in paths):
            yield
            return
        with _experience_guard(self.vault, paths):
            self._publishing = True
            try:
                yield
            finally:
                self._publishing = False

    def _conflict(
        self, path: Path, actual: bytes | None, *,
        proposed=None, expected_hash=fsutil.UNCHECKED,
    ) -> None:
        if expected_hash is fsutil.UNCHECKED:
            expected_hash = _hash(self.observed.get(path))
        self.journal["conflicts"].append({
            "path": self._relative(path), "expected_hash": expected_hash,
            "original": _encode(self.original.get(path)), "observed": _encode(actual),
            "observed_hash": _hash(actual), "proposed": proposed,
        })
        self.failure = CurationConflict(path, self.journal_path)
        self._persist()
        raise self.failure

    def validate(self, *, proposed=None) -> None:
        """Verify the entire registered input snapshot, never a cached verdict."""
        self._validate_paths(tuple(self.observed), proposed=proposed)

    def _validate_paths(self, paths: Iterable[Path], *, proposed=None) -> None:
        self._owned()
        if self.failure is not None:
            raise self.failure
        require_curator(self.vault)
        for path in paths:
            expected = self.observed[path]
            fsutil.checked_regular_path(self.vault, path)
            actual = _read(path)
            if actual != expected:
                self._conflict(path, actual, proposed=proposed)

    def expect_hashes(self, expected: Mapping[str, str | None], *, decision=None) -> None:
        """Bind an approved review to its saved source hashes, not today's bytes."""
        self._owned()
        if not isinstance(expected, Mapping):
            raise CurationRecoveryError("expected input hashes must be a mapping")
        if decision is not None:
            self.journal["decisions"].append(json.loads(json.dumps(decision, allow_nan=False)))
        for relative, digest in expected.items():
            if digest is not None and (
                not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise CurationRecoveryError("expected input hashes must be SHA-256 or null")
            path = _operation_path(self.vault, relative)
            self.watch(path)
            actual = _read(path)
            if _hash(actual) != digest:
                self.journal["decisions"].append({"expected_hashes": dict(expected)})
                self._conflict(path, actual, expected_hash=digest)

    def _change(self, path: Path, after: bytes | None, *, expected_hash=fsutil.UNCHECKED) -> None:
        self._owned()
        path = fsutil._check(self.vault, path, config.CURATOR_WRITABLE, "curator")
        if self.journal["state"] != "active":
            raise CurationRecoveryError("no mutations are allowed after Git commit preparation")
        if path not in self.observed:
            self.observed[path] = self.original[path] = None
        proposal = {"path": self._relative(path), "after": _encode(after)}
        self._validate_paths((path,), proposed=proposal)
        before = self.observed[path]
        if expected_hash is not fsutil.UNCHECKED and _hash(before) != expected_hash:
            self._conflict(path, _read(path), proposed=proposal, expected_hash=expected_hash)
        if before == after:
            return
        if not self.journal["operations"]:
            self.validate(proposed=proposal)
        self.journal["operations"].append({
            "path": self._relative(path), "before": _encode(before), "after": _encode(after),
            "before_hash": _hash(before), "after_hash": _hash(after),
        })
        try:
            self._persist()
            if after is None:
                fsutil._atomic_unlink(path, expected_hash=_hash(before))
            else:
                fsutil._atomic_write_bytes(path, after, expected_hash=_hash(before))
        except fsutil.WriteConflictError:
            self._conflict(path, _read(path), proposed=proposal)
        except (OSError, fsutil.PathTraversalError, fsutil.WriteBoundaryError):
            self.failure = CurationRecoveryError(
                f"curation mutation failed; recovery retained at {self.journal_path}"
            )
            raise
        self.observed[path] = after

    def write(self, path, data: bytes, *, expected_hash=fsutil.UNCHECKED) -> Path:
        path = self._path(path)
        self._change(path, data, expected_hash=expected_hash)
        return path

    def unlink(self, path, *, missing_ok: bool = False) -> None:
        path = self._path(path)
        if path not in self.observed and not path.exists() and not missing_ok:
            raise FileNotFoundError(path)
        if path in self.observed and self.observed[path] is None and not missing_ok:
            raise FileNotFoundError(path)
        self._change(path, None)

    def rename(self, source: Path, destination: Path) -> Path:
        data = self.read_bytes(source)
        if data is None:
            raise FileNotFoundError(source)
        self._change(destination, data, expected_hash=None)
        self.unlink(source)
        return destination

    def prepare_git_commit(self, *, isolated_index: bool = False) -> str:
        from .. import gitutil

        self.validate()
        self.journal["git_head_before"] = gitutil.head_commit(self.vault)
        if isolated_index:
            self.journal["git_isolated_index"] = True
            self.journal["git_commit_started"] = False
            self.journal["git_commit_finished"] = False
            self.journal["git_index_reconciled"] = False
        self.journal["state"] = "committing"
        self._persist()
        return f"Memory-Mesh-Transaction: {self.journal['id']}"

    def git_commit_started(self) -> None:
        self._owned()
        self.journal["git_commit_started"] = True
        self._persist()

    def git_commit_finished(self) -> None:
        self._owned()
        self.journal["git_commit_finished"] = True
        self._persist()

    def fail_publication(self, message: str) -> None:
        """Retain a failed result and force rollback at the run boundary."""
        self._owned()
        self.failure = CurationPublicationError(message, self.journal_path)
        self.journal["publication_error"] = message
        self._persist()

    def record_git_unavailable(self) -> None:
        self._owned()
        self.journal["publication"] = "manual-commit-required"
        if self.saved:
            self._persist()

    def finish_git_commit(
        self, *, committed: bool, sha: str | None = None, error: str | None = None,
    ) -> None:
        if not committed:
            self.fail_publication(error or "Git did not publish the requested changes")
            return
        self.journal["state"] = "committed"
        self.journal["publication"] = "committed"
        self.journal["git_commit"] = sha
        if self.journal.get("git_isolated_index"):
            self.journal["git_index_reconciled"] = True
        self._persist()


def current_transaction(vault: Vault | None = None) -> CurationTransaction | None:
    tx = fsutil._curation_context.get()
    if tx is None:
        return None
    tx._owned()
    if vault is not None and tx.vault.root != vault.root:
        raise CurationRecoveryError("cannot mix vaults in one curation transaction")
    return tx


def _default_inputs(vault: Vault) -> Iterator[Path]:
    for relative in (
        config.KNOWLEDGE, config.INBOX, config.EPISODES, config.REVIEW_DIR,
        config.SKILLS, config.CONTEXT_PACKS,
    ):
        base = vault.path(relative)
        if not base.exists():
            continue
        fsutil.checked_regular_path(vault, base / ".path-check")
        for parent, dirs, files in os.walk(base, followlinks=False):
            for child in dirs:
                fsutil.checked_regular_path(vault, Path(parent) / child / ".path-check")
            for name in files:
                if name.endswith((".md", ".tsv")):
                    yield Path(parent) / name
    for relative in (
        config.SETTINGS_FILE, config.REDACT_FILE, config.GRADUATION_FILE, config.CURATION_LOG,
    ):
        yield vault.path(relative)


@contextmanager
def curation_transaction(
    vault: Vault, *, run_id: str | None = None,
    inputs: Iterable[Path | str] | None = None, existing_lock: bool = False,
) -> Iterator[CurationTransaction]:
    """Authorize, recover, snapshot, mutate, then validate a complete run.

    inputs=None snapshots normal curator inputs. Explicit inputs narrow that
    set; every additional decision input must be watched/read before use.
    existing_lock=True is ONLY for callers already inside the V2 curator lock.
    Do not nest transactions; pass current_transaction(vault) to helpers.
    Place RecordStore.transaction contexts INSIDE this boundary, not around
    it: final validation, Git publication and rollback acquire the experience
    lock when records or attestations participate.
    """
    if fsutil._curation_context.get() is not None:
        raise CurationRecoveryError("curation transactions are not reentrant")
    with curator_lock(vault, existing_lock=existing_lock):
        conflicts = [r for r in _recover_locked(vault) if r.state == "conflict"]
        if conflicts:
            raise CurationRecoveryError(
                f"unresolved curation conflict; review and acknowledge {conflicts[0].journal}"
            )
        tx = CurationTransaction(vault, run_id)
        for path in _default_inputs(vault) if inputs is None else inputs:
            tx.watch(path)
        token = fsutil._curation_context.set(tx)
        try:
            yield tx
            if tx.journal["state"] != "committed":
                with tx.publication_lock():
                    tx.validate()
                    if tx.saved:
                        tx.journal["state"] = "committed"
                        tx._persist()
        except BaseException as error:
            if tx.saved and tx.journal["state"] != "committed":
                try:
                    recovery = _rollback(vault, tx.journal)
                except (
                    OSError, CurationRecoveryError, fsutil.PathTraversalError, fsutil.WriteBoundaryError,
                ) as recovery_error:
                    raise CurationRecoveryError(
                        f"curation rollback interrupted; recovery retained at {tx.journal_path}"
                    ) from recovery_error
                if recovery.state == "conflict" and not isinstance(error, CurationConflict):
                    if not recovery.conflicts:
                        raise CurationRecoveryError(
                            f"Git publication exists but its index needs review: {recovery.journal}"
                        ) from error
                    raise CurationConflict(
                        vault.path(recovery.conflicts[0]), recovery.journal,
                    ) from error
            raise
        finally:
            tx.closed = True
            fsutil._curation_context.reset(token)
