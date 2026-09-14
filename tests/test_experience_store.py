import contextlib
import errno
import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_vault

from memory_mesh import frontmatter
from memory_mesh.cli import main
from memory_mesh.config import VaultError
from memory_mesh.experience_store import (
    MAX_RECORD_BYTES,
    ExperienceBusy,
    ExperienceConflict,
    ExperienceError,
    ExperienceLimit,
    RecordStore,
    exclusive_lock,
)
from memory_mesh.notes import load_note
from memory_mesh.schema import validate_note


_CHILD = r"""
import os
import sys
import time
from pathlib import Path

from memory_mesh.config import Vault
from memory_mesh.experience_store import RecordStore, exclusive_lock

store = RecordStore(Vault(Path(sys.argv[1])))
if sys.argv[2] in ("hold", "curator"):
    lock = (
        store.transaction(timeout=5)
        if sys.argv[2] == "hold"
        else exclusive_lock(store.vault, name="curator", timeout=5)
    )
    with lock:
        print("locked", flush=True)
        if sys.stdin.readline().strip() == "exit":
            os._exit(23)
else:
    print("ready", flush=True)
    sys.stdin.readline()
    for _ in range(8):
        with store.transaction(timeout=5):
            data = store.load("tasks", "counter")
            time.sleep(0.005)
            data["count"] += 1
            store.save("tasks", "counter", data)
    print("done", flush=True)
"""


class TestRecordStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix=".mm-store-test-", dir=".")
        self.addCleanup(self._tmp.cleanup)
        self.vault, _ = make_vault(Path(self._tmp.name))
        self.store = RecordStore(self.vault)

    def _snapshot(self):
        def content(path):
            if not path.is_file():
                return None
            if path.name in ("memory-mesh-v2-records.lock", "memory-mesh-v2-curator.lock"):
                # Windows mandatory byte locks disallow reading the held byte.
                info = path.stat()
                return info.st_ino, info.st_size
            return path.read_bytes()

        return {
            path.relative_to(self.vault.root): content(path)
            for path in self.vault.root.rglob("*")
        }

    def _save_one(self):
        with self.store.transaction():
            return self.store.save("tasks", "one", {"count": 1})

    def _replace_payload(self, path, payload):
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        head, _, after = body.partition("```json\n")
        _, _, tail = after.rpartition("\n```")
        meta["payload_sha256"] = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        path.write_text(
            frontmatter.compose(meta, head + "```json\n" + payload + "\n```" + tail),
            encoding="utf-8",
            newline="\n",
        )

    def _assert_private_error(self, action, forbidden):
        try:
            action()
        except ExperienceError as error:
            diagnostic = "".join(traceback.format_exception(error))
            self.assertNotIn(forbidden, str(error))
            self.assertNotIn(forbidden, diagnostic)
            return error
        else:
            self.fail("Invalid private content was accepted")

    def _acquire(self):
        with self.store.transaction(timeout=0):
            pass

    def _acquire_named(self, name="experience", timeout=0):
        with exclusive_lock(self.vault, name=name, timeout=timeout):
            pass

    def _start_child(self, mode):
        child = subprocess.Popen(
            [sys.executable, "-B", "-u", "-c", _CHILD, str(self.vault.root), mode],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def cleanup():
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

        self.addCleanup(cleanup)
        ready = queue.Queue()
        reader = threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True)
        reader.start()
        self.assertEqual(ready.get(timeout=15).strip(), "ready" if mode == "increment" else "locked")
        reader.join(timeout=2)
        return child

    def _directory_link(self, link, target):
        target.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if os.name != "nt" or error.winerror != 1314:
                raise
            # Junctions exercise real Windows redirection without symlink privileges.
            env = dict(os.environ, MM_TEST_LINK=str(link), MM_TEST_TARGET=str(target))
            result = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                    "-Path $env:MM_TEST_LINK -Target $env:MM_TEST_TARGET | Out-Null",
                ],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_errors_follow_the_vault_error_contract(self):
        self.assertTrue(issubclass(ExperienceError, VaultError))
        for error in (ExperienceBusy, ExperienceConflict, ExperienceLimit):
            self.assertTrue(issubclass(error, ExperienceError))
        self.assertEqual(MAX_RECORD_BYTES, 262144)

    def test_roundtrip_is_one_lint_clean_project_record(self):
        data = {
            "summary": "A bounded local record",
            "nested": {"items": [None, True, False, 3, -8, 0.25, "café\n```"]},
        }
        with self.store.transaction() as acquired:
            self.assertIs(acquired, self.store)
            path = self.store.save("tasks", "Task:1", data)

        self.assertEqual(self.store.load("tasks", "Task:1"), data)
        self.assertEqual(RecordStore(self.vault).load("tasks", "Task:1"), data)
        self.assertEqual(path, self.store.record_path("tasks", "Task:1"))
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["type"], "project")
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(meta["bucket"], "tasks")
        self.assertNotIn("domains", meta)
        self.assertIn("```json\n", body)
        self.assertEqual(validate_note(load_note(path, self.vault), self.vault), [])
        self.assertEqual(list(path.parent.iterdir()), [path])
        before = self._snapshot()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["--root", str(self.vault.root), "lint"])
        self.assertEqual(result, 0, output.getvalue())
        self.assertEqual(self._snapshot(), before)

    def test_missing_reads_and_references_never_create_files(self):
        before = self._snapshot()
        self.assertIsNone(self.store.load("tasks", "missing"))
        self.assertEqual(list(self.store.iter_records("profile")), [])
        self.store.record_path("tasks", "missing")
        self.store.record_ref("tasks", "missing")
        self.assertEqual(self._snapshot(), before)

    def test_paths_and_references_hash_the_exact_key(self):
        keys = ["Task", "task", "a" * 99 + "x", "a" * 99 + "y", "CON", "x:y.z_-"]
        paths = []
        for key in keys:
            digest = hashlib.sha256(key.encode("ascii")).hexdigest()
            path = self.store.record_path("tasks", key)
            expected = self.vault.root / "projects" / "_memory-mesh-v2" / "records" / "tasks" / (digest + ".md")
            self.assertEqual(path, expected)
            self.assertEqual(
                self.store.record_ref("tasks", key),
                expected.relative_to(self.vault.root).with_suffix("").as_posix(),
            )
            paths.append(path)
        self.assertEqual(len(set(paths)), len(keys))

    def test_scalar_looking_keys_preserve_string_identity(self):
        keys = ["0", "001", "True", "False", "null", "-3", "1.5"]
        with self.store.transaction():
            for key in keys:
                self.store.save("tasks", key, {"label": key})
        for key in keys:
            self.assertEqual(self.store.load("tasks", key), {"label": key})

    def test_bucket_and_key_validation_is_read_only(self):
        before = self._snapshot()
        for bucket in ("knowledge", "profiles", "Tasks", "../tasks", "", None, 1):
            with self.subTest(bucket=bucket):
                with self.assertRaises(ExperienceError):
                    self.store.record_path(bucket, "valid")
                with self.assertRaises(ExperienceError):
                    list(self.store.iter_records(bucket))
        for key in ("", ".", "..", "../x", "a/b", "a\\b", "x y", "é", "a\n", "\0", "a" * 101, None, 1):
            with self.subTest(key=key):
                with self.assertRaises(ExperienceError):
                    self.store.load("tasks", key)
        self.assertEqual(self._snapshot(), before)

    def test_save_requires_this_instances_transaction(self):
        before = self._snapshot()
        with self.assertRaises(ExperienceConflict):
            self.store.save("tasks", "one", {})
        self.assertEqual(self._snapshot(), before)
        other = RecordStore(self.vault)
        with self.store.transaction():
            with self.assertRaises(ExperienceConflict):
                other.save("tasks", "one", {})
        with self.assertRaises(ExperienceConflict):
            self.store.save("tasks", "one", {})

    def test_payloads_are_isolated_without_a_mutable_cache(self):
        data = {"values": [{"count": 1}]}
        with self.store.transaction():
            self.store.save("tasks", "one", data)
        data["values"][0]["count"] = 2
        first = self.store.load("tasks", "one")
        self.assertEqual(first, {"values": [{"count": 1}]})
        first["values"][0]["count"] = 3
        self.assertEqual(self.store.load("tasks", "one"), {"values": [{"count": 1}]})

    def test_empty_payload_is_not_missing_and_buckets_are_independent(self):
        with self.store.transaction():
            self.store.save("tasks", "same", {})
            self.store.save("profile", "same", {"value": 1})
        self.assertEqual(self.store.load("tasks", "same"), {})
        self.assertEqual(self.store.load("profile", "same"), {"value": 1})

    def test_iteration_returns_original_keys_and_independent_payloads(self):
        with self.store.transaction():
            self.store.save("tasks", "FIRST", {"items": [1]})
            self.store.save("tasks", "second", {"items": [2]})
            self.store.save("profile", "separate", {})
        records = dict(self.store.iter_records("tasks"))
        self.assertEqual(records, {"FIRST": {"items": [1]}, "second": {"items": [2]}})
        records["FIRST"]["items"].append(3)
        self.assertEqual(self.store.load("tasks", "FIRST"), {"items": [1]})

    def test_store_does_not_add_semantic_revisions_or_block_replacement(self):
        with self.store.transaction():
            self.store.save("tasks", "one", {"revision": 7})
            self.store.save("tasks", "one", {"revision": 2})
        self.assertEqual(self.store.load("tasks", "one"), {"revision": 2})

    def test_corrupt_records_are_never_treated_as_missing(self):
        path = self._save_one()
        for raw in (
            b"",
            b"not a record",
            b"\xff",
            b"---\ntype: project\n",
            b"---\ninvalid metadata\n---\n",
        ):
            path.write_bytes(raw)
            with self.assertRaises(ExperienceError):
                self.store.load("tasks", "one")
            with self.assertRaises(ExperienceError):
                list(self.store.iter_records("tasks"))

    def test_checksum_detects_payload_changes(self):
        path = self._save_one()
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"count":1', '"count":2'), encoding="utf-8")
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")

    def test_metadata_must_match_the_schema_and_bucket(self):
        path = self._save_one()
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        for changes in (
            {"type": "pattern"},
            {"schema_version": 2},
            {"schema_version": True},
            {"bucket": "profile"},
            {"extra": "unexpected"},
        ):
            path.write_text(frontmatter.compose(dict(meta, **changes), body), encoding="utf-8")
            with self.assertRaises(ExperienceError):
                self.store.load("tasks", "one")
        duplicate = frontmatter.compose(meta, body).replace("type: project", "type: project\ntype: project")
        path.write_text(duplicate, encoding="utf-8")
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")

    def test_identity_is_verified_even_with_a_recomputed_checksum(self):
        path = self._save_one()
        self._replace_payload(path, json.dumps({"key": "two", "data": {"count": 1}}))
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")
        with self.assertRaises(ExperienceError):
            list(self.store.iter_records("tasks"))

    def test_copied_records_cannot_alias_another_key_or_bucket(self):
        original = self._save_one()
        for bucket, key in (("tasks", "two"), ("profile", "one")):
            path = self.store.record_path(bucket, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original.read_bytes())
            with self.assertRaises(ExperienceError):
                self.store.load(bucket, key)

    def test_json_shape_duplicates_and_numbers_are_checked_on_read(self):
        path = self._save_one()
        for payload in (
            "not JSON",
            "[]",
            '{"key":"one"}',
            '{"key":"one","data":[]}',
            '{"key":1,"data":{}}',
            '{"key":"one","data":{},"extra":1}',
            '{"key":"one","key":"one","data":{}}',
            '{"key":"one","data":{"same":1,"same":2}}',
            '{"key":"one","data":{"value":NaN}}',
            '{"key":"one","data":{"value":1e999}}',
        ):
            self._replace_payload(path, payload)
            with self.assertRaises(ExperienceError):
                self.store.load("tasks", "one")

    def test_read_rejects_unencodable_json_strings(self):
        path = self._save_one()
        self._replace_payload(path, '{"key":"one","data":{"value":"\\ud800"}}')
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")

    def test_deep_json_is_a_safe_read_limit(self):
        path = self._save_one()
        for depth in (40, 2000):
            payload = '{"key":"one","data":{"nested":' + "[" * depth + "0" + "]" * depth + "}}"
            self._replace_payload(path, payload)
            with self.assertRaises(ExperienceLimit):
                self.store.load("tasks", "one")

    def test_non_json_types_cycles_and_depth_are_rejected_without_changes(self):
        cycle = []
        cycle.append(cycle)
        nested = {}
        for _ in range(40):
            nested = {"nested": nested}
        invalid = (
            [],
            {1: "number key"},
            {"value": (1, 2)},
            {"value": {1, 2}},
            {"value": b"bytes"},
            {"value": Path("not-json")},
            {"value": float("nan")},
            {"value": float("inf")},
            {"value": float("-inf")},
            {"value": "\ud800"},
            {"value": cycle},
            nested,
        )
        with self.store.transaction():
            before = self._snapshot()
            for data in invalid:
                with self.assertRaises(ExperienceError):
                    self.store.save("tasks", "invalid", data)
                self.assertEqual(self._snapshot(), before)

    def test_record_byte_limit_includes_metadata_and_utf8(self):
        path = self._save_one()
        with self.store.transaction():
            before = self._snapshot()
            for value in ("x" * MAX_RECORD_BYTES, "é" * (MAX_RECORD_BYTES // 2)):
                with self.assertRaises(ExperienceLimit):
                    self.store.save("tasks", "one", {"large": value})
                with self.assertRaises(ExperienceLimit):
                    self.store.save("profile", "new", {"large": value})
                self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.store.load("tasks", "one"), {"count": 1})
        self.assertTrue(path.exists())

    def test_oversized_file_is_rejected_before_opening_a_reader(self):
        path = self._save_one()
        path.write_bytes(b"\xff" * (MAX_RECORD_BYTES + 1))
        with mock.patch("memory_mesh.experience_store.os.fdopen", side_effect=AssertionError("Unbounded read")):
            with self.assertRaises(ExperienceLimit):
                self.store.load("tasks", "one")

    def test_growth_after_stat_is_still_bounded_before_decode(self):
        path = self._save_one()
        info = path.stat()
        path.write_bytes(b"\xff" * (MAX_RECORD_BYTES + 1))
        fdopen = os.fdopen

        @contextlib.contextmanager
        def bounded_reader(*args, **kwargs):
            with fdopen(*args, **kwargs) as stream:
                def read(limit=-1):
                    self.assertGreater(limit, 0)
                    self.assertLessEqual(limit, MAX_RECORD_BYTES + 1)
                    return stream.read(limit)

                yield mock.Mock(read=read)

        with (
            mock.patch("memory_mesh.experience_store.os.fstat", return_value=info),
            mock.patch("memory_mesh.experience_store.os.fdopen", side_effect=bounded_reader),
        ):
            with self.assertRaises(ExperienceLimit):
                self.store.load("tasks", "one")

    def test_an_open_read_snapshot_can_outlive_its_directory_entry(self):
        path = self._save_one()
        info = list(path.stat())
        info[3] = 0  # POSIX atomic replacement can unlink the already-open old inode.
        with mock.patch("memory_mesh.experience_store.os.fstat", return_value=os.stat_result(info)):
            self.assertEqual(self.store.load("tasks", "one"), {"count": 1})

    def test_builtin_privacy_covers_ids_object_keys_and_nested_values(self):
        marker = "ghp_" + "a" * 24
        with self.store.transaction():
            before = self._snapshot()
            for action in (
                lambda: self.store.save("tasks", marker, {}),
                lambda: self.store.record_ref("profile", marker),
                lambda: self.store.save("tasks", "one", {marker: "value"}),
                lambda: self.store.save("tasks", "one", {"nested": [{"text": marker}]}),
                lambda: self.store.save("tasks", "one", {"password": marker}),
            ):
                self._assert_private_error(action, marker)
                self.assertEqual(self._snapshot(), before)

    def test_split_secret_assignments_are_not_a_privacy_bypass(self):
        marker = "sentinel-credential-value"
        with self.store.transaction():
            for key in ("password", "api-key", "client-secret"):
                self._assert_private_error(
                    lambda: self.store.save("tasks", "one", {key: marker}),
                    marker,
                )
        self.assertIsNone(self.store.load("tasks", "one"))

    def test_custom_privacy_rules_apply_to_keys_and_values_including_on_read(self):
        marker = "private-sentinel"
        with self.store.transaction():
            path = self.store.save("tasks", "one", {"value": marker})
        rules = self.vault.root / "_meta" / "redact.txt"
        rules.write_text("literal:" + marker + "\n", encoding="utf-8")
        original = path.read_bytes()
        self._assert_private_error(lambda: self.store.load("tasks", "one"), marker)
        self._assert_private_error(lambda: list(self.store.iter_records("tasks")), marker)
        with self.store.transaction():
            for key, data in ((marker, {}), ("new", {marker: 1}), ("new", {"value": marker})):
                self._assert_private_error(lambda: self.store.save("tasks", key, data), marker)
        self.assertEqual(path.read_bytes(), original)

    def test_private_json_and_parser_errors_do_not_echo_content(self):
        path = self._save_one()
        marker = "ghp_" + "b" * 24
        for payload in (
            json.dumps({"key": "one", "data": {"value": marker}}),
            '{"key":"one","data":' + marker,
        ):
            self._replace_payload(path, payload)
            self._assert_private_error(lambda: self.store.load("tasks", "one"), marker)
        path.write_text("---\n" + marker + "\n---\n", encoding="utf-8")
        self._assert_private_error(lambda: self.store.load("tasks", "one"), marker)

    def test_io_and_redaction_errors_are_safe_not_missing(self):
        marker = "private-filesystem-detail"
        with mock.patch("memory_mesh.experience_store.os.open", side_effect=PermissionError(marker)):
            self._assert_private_error(lambda: self.store.load("tasks", "one"), marker)
        with mock.patch("memory_mesh.experience_store.redact.redact", side_effect=OSError(marker)):
            self._assert_private_error(lambda: self.store.load("tasks", "one"), marker)

    def test_failed_atomic_replace_preserves_the_previous_record(self):
        self._save_one()
        marker = "private-filesystem-detail"
        with self.store.transaction():
            before = self._snapshot()
            with mock.patch("memory_mesh.fsutil.os.replace", side_effect=PermissionError(marker)):
                self._assert_private_error(
                    lambda: self.store.save("tasks", "one", {"count": 2}),
                    marker,
                )
            self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.store.load("tasks", "one"), {"count": 1})

    def test_save_will_not_silently_repair_a_corrupt_existing_record(self):
        path = self._save_one()
        path.write_bytes(b"corrupt")
        with self.store.transaction():
            before = self._snapshot()
            with self.assertRaises(ExperienceError):
                self.store.save("tasks", "one", {})
            self.assertEqual(self._snapshot(), before)

    def test_iteration_rejects_noncanonical_markdown_names(self):
        path = self._save_one()
        path.rename(path.with_name("not-a-record-id.md"))
        with self.assertRaises(ExperienceError):
            list(self.store.iter_records("tasks"))

    def test_lock_setup_errors_are_safe_and_release_instance_state(self):
        marker = "private-lock-filesystem-detail"
        with mock.patch("memory_mesh.experience_store.os.fstat", side_effect=OSError(errno.EIO, marker)):
            self._assert_private_error(self._acquire, marker)
        with self.store.transaction(timeout=0):
            self.store.save("tasks", "one", {})

    def test_close_errors_are_safe_and_do_not_strand_the_transaction(self):
        self._save_one()
        marker = "private-close-filesystem-detail"
        real_close = os.close

        def failing_close(fd):
            real_close(fd)
            raise OSError(errno.EIO, marker)

        for action in (lambda: self.store.load("tasks", "one"), self._acquire):
            with mock.patch("memory_mesh.experience_store.os.close", side_effect=failing_close):
                self._assert_private_error(action, marker)
        self._acquire()

    def test_unexpected_os_lock_errors_are_not_misreported_as_busy(self):
        marker = "private-lock-detail"
        lock_function = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"
        with mock.patch(lock_function, side_effect=OSError(errno.EIO, marker)):
            error = self._assert_private_error(self._acquire, marker)
            self.assertNotIsInstance(error, ExperienceBusy)
        self._acquire()

    def test_lock_initialization_failure_releases_the_os_lock(self):
        marker = "private-lock-detail"
        with mock.patch("memory_mesh.experience_store.os.write", side_effect=OSError(errno.EIO, marker)):
            self._assert_private_error(self._acquire, marker)
        with RecordStore(self.vault).transaction(timeout=0):
            pass

    def test_transaction_releases_on_exception_but_does_not_roll_back_saved_records(self):
        error = OSError("caller-owned failure")
        with self.assertRaises(OSError) as caught:
            with self.store.transaction():
                self.store.save("tasks", "one", {"count": 1})
                raise error
        self.assertIs(caught.exception, error)
        with RecordStore(self.vault).transaction(timeout=0):
            self.assertEqual(self.store.load("tasks", "one"), {"count": 1})
        with self.assertRaises(ExperienceConflict):
            self.store.save("tasks", "one", {})

    def test_nested_transactions_fail_without_releasing_the_outer_lock(self):
        other = RecordStore(self.vault)
        with self.store.transaction():
            with self.assertRaises(ExperienceConflict):
                with self.store.transaction(timeout=0):
                    self.fail("Nested transaction entered")
            with self.assertRaises(ExperienceBusy):
                with other.transaction(timeout=0):
                    self.fail("Concurrent transaction entered")
            self.store.save("tasks", "one", {})
        with other.transaction(timeout=0):
            other.save("profile", "one", {})

    def test_transaction_ownership_cannot_be_borrowed_by_another_thread(self):
        results = []

        def other_thread():
            try:
                self.store.save("tasks", "one", {})
            except ExperienceError as error:
                results.append(type(error))
            try:
                self._acquire()
            except ExperienceError as error:
                results.append(type(error))

        with self.store.transaction():
            worker = threading.Thread(target=other_thread, daemon=True)
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results, [ExperienceConflict, ExperienceBusy])
            self.store.save("tasks", "one", {})

    def test_invalid_timeouts_do_not_create_state(self):
        before = self._snapshot()
        for timeout in (-1, float("nan"), float("inf"), float("-inf"), "1", None, True, 10**400):
            with self.assertRaises(ExperienceError):
                with self.store.transaction(timeout=timeout):
                    self.fail("Invalid timeout accepted")
        self.assertEqual(self._snapshot(), before)

    def test_lock_file_is_stable_across_acquisitions(self):
        self._acquire()
        path = self.vault.root / "_meta" / "session-state" / "memory-mesh-v2-records.lock"
        first = path.stat()
        original = path.read_bytes()
        self._acquire()
        second = path.stat()
        self.assertEqual(first.st_ino, second.st_ino)
        self.assertEqual(first.st_mtime_ns, second.st_mtime_ns)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(original, b"\0")

    def test_child_contention_is_bounded_and_abrupt_exit_releases_the_lock(self):
        child = self._start_child("hold")
        path = self.vault.root / "_meta" / "session-state" / "memory-mesh-v2-records.lock"
        inode = path.stat().st_ino
        start = time.monotonic()
        with self.assertRaises(ExperienceBusy):
            with self.store.transaction(timeout=0.05):
                self.fail("Entered a lock held by another process")
        self.assertLess(time.monotonic() - start, 5)
        with self.assertRaises(ExperienceBusy):
            self._acquire_named()
        child.stdin.write("exit\n")
        child.stdin.flush()
        self.assertEqual(child.wait(timeout=10), 23)
        with self.store.transaction(timeout=1):
            self.store.save("tasks", "recovered", {})
        self.assertEqual(path.stat().st_ino, inode)
        self.assertEqual(self.store.load("tasks", "recovered"), {})

    def test_killed_child_does_not_leave_a_stale_lock(self):
        child = self._start_child("hold")
        child.kill()
        child.wait(timeout=10)
        with self.store.transaction(timeout=1):
            self.store.save("tasks", "recovered", {})
        self.assertEqual(self.store.load("tasks", "recovered"), {})

    def test_cooperating_processes_serialize_read_modify_write(self):
        with self.store.transaction():
            self.store.save("tasks", "counter", {"count": 0})
        children = [self._start_child("increment"), self._start_child("increment")]
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "done")
        self.assertEqual(self.store.load("tasks", "counter"), {"count": 16})

    def test_directory_redirection_cannot_reach_other_projects_or_canonical_data(self):
        targets = (
            self.vault.root / "knowledge",
            self.vault.root / "projects" / "unowned",
            Path(self._tmp.name).resolve() / "outside",
        )
        link = self.vault.root / "projects" / "_memory-mesh-v2"
        for target in targets:
            self._directory_link(link, target)
            try:
                before = sorted(target.rglob("*"))
                for action in (
                    lambda: self.store.load("tasks", "one"),
                    lambda: self.store.record_path("profile", "one"),
                    lambda: list(self.store.iter_records("tasks")),
                ):
                    with self.assertRaises(ExperienceError):
                        action()
                with self.store.transaction():
                    with self.assertRaises(ExperienceError):
                        self.store.save("tasks", "one", {})
                self.assertEqual(sorted(target.rglob("*")), before)
            finally:
                if link.is_symlink():
                    link.unlink()
                else:
                    link.rmdir()

    def test_lock_directory_redirection_is_rejected_before_creating_a_lock(self):
        link = self.vault.root / "_meta" / "session-state"
        link.rmdir()
        target = Path(self._tmp.name).resolve() / "outside-state"
        self._directory_link(link, target)
        with self.assertRaises(ExperienceError):
            self._acquire()
        with self.assertRaises(ExperienceError):
            self._acquire_named("curator")
        self.assertEqual(list(target.iterdir()), [])

    def test_record_and_lock_hard_links_are_rejected(self):
        path = self._save_one()
        other = self.vault.root / "projects" / "other.md"
        os.link(path, other)
        original = other.read_bytes()
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")
        with self.store.transaction():
            with self.assertRaises(ExperienceError):
                self.store.save("tasks", "one", {})
        self.assertEqual(other.read_bytes(), original)
        lock = self.vault.root / "_meta" / "session-state" / "memory-mesh-v2-records.lock"
        os.link(lock, self.vault.root / "projects" / "other.lock")
        with self.assertRaises(ExperienceError):
            self._acquire()

    def test_nonregular_records_and_lock_paths_are_safe_errors(self):
        path = self.store.record_path("tasks", "one")
        path.mkdir(parents=True)
        with self.assertRaises(ExperienceError):
            self.store.load("tasks", "one")
        lock = self.vault.root / "_meta" / "session-state" / "memory-mesh-v2-records.lock"
        lock.mkdir()
        with self.assertRaises(ExperienceError):
            self._acquire()

    def test_default_named_lock_and_record_transactions_share_one_lock(self):
        with exclusive_lock(self.vault, timeout=0):
            with self.assertRaises(ExperienceBusy):
                self._acquire()
            with self.assertRaises(ExperienceConflict):
                self.store.save("tasks", "one", {})
        with self.store.transaction(timeout=0):
            with self.assertRaises(ExperienceBusy):
                self._acquire_named()
            self.store.save("tasks", "one", {})
        self._acquire_named()

    def test_curator_can_wrap_record_transactions_without_reentrancy(self):
        with exclusive_lock(self.vault, name="curator", timeout=0):
            with self.store.transaction(timeout=0):
                self.store.save("tasks", "one", {"revision": 1})
            with self.assertRaises(ExperienceBusy):
                self._acquire_named("curator")
            with self.store.transaction(timeout=0):
                self.store.save("tasks", "one", {"revision": 2})
        self._acquire_named("curator")
        self.assertEqual(self.store.load("tasks", "one"), {"revision": 2})

    def test_named_locks_only_accept_static_allowlisted_names_without_writes(self):
        before = self._snapshot()
        names = ("", ".", "..", "../curator", "curator.lock", "Curator", "curator/other", "CON", None, 1, [])
        for name in names:
            with self.assertRaises(ExperienceError):
                self._acquire_named(name)
        marker = "ghp_" + "c" * 24
        self._assert_private_error(lambda: self._acquire_named(marker), marker)
        self.assertEqual(self._snapshot(), before)

    def test_named_lock_timeout_validation_does_not_create_files(self):
        before = self._snapshot()
        for timeout in (-1, float("nan"), float("inf"), None, True, "2", 10**400):
            with self.assertRaises(ExperienceError):
                self._acquire_named("curator", timeout=timeout)
        self.assertEqual(self._snapshot(), before)

    def test_named_lock_releases_after_caller_exception(self):
        error = OSError("caller-owned failure")
        with self.assertRaises(OSError) as caught:
            with exclusive_lock(self.vault, name="curator", timeout=0):
                raise error
        self.assertIs(caught.exception, error)
        self._acquire_named("curator")

    def test_named_locks_keep_distinct_stable_files(self):
        self._acquire()
        directory = self.vault.root / "_meta" / "session-state"
        original = (directory / "memory-mesh-v2-records.lock").stat().st_ino
        self._acquire_named("curator")
        paths = list(directory.glob("*.lock"))
        self.assertEqual(
            {path.name for path in paths},
            {"memory-mesh-v2-records.lock", "memory-mesh-v2-curator.lock"},
        )
        before = {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in paths}
        with exclusive_lock(self.vault, name="curator", timeout=0):
            with exclusive_lock(self.vault, timeout=0):
                pass
        after = {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in paths}
        self.assertEqual(after, before)
        self.assertEqual((directory / "memory-mesh-v2-records.lock").stat().st_ino, original)

    def test_curator_process_lock_does_not_block_records_and_releases_on_death(self):
        child = self._start_child("curator")
        with self.assertRaises(ExperienceBusy):
            self._acquire_named("curator", timeout=0.05)
        with self.store.transaction(timeout=0):
            self.store.save("profile", "one", {})
        child.kill()
        child.wait(timeout=10)
        self._acquire_named("curator", timeout=1)
        self.assertEqual(self.store.load("profile", "one"), {})


if __name__ == "__main__":
    unittest.main()
