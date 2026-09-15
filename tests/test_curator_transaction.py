import base64
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import init_git, make_vault
from memory_mesh import attestations, fsutil, gitutil, notes
from memory_mesh.curator.transaction import (
    JOURNAL_DIR, CurationConflict, CurationPublicationError, CurationRecoveryError,
    acknowledge_curation_conflict, current_transaction, curation_transaction,
    recover_curation_transactions,
)
from memory_mesh.experience_store import ExperienceBusy, RecordStore, exclusive_lock


class TestCuratorTransaction(unittest.TestCase):
    def setUp(self):
        self.vault, self.holder = make_vault()
        self.path = self.vault.path("knowledge/patterns/transaction.md")
        self.path.write_bytes(b"original")
        self.saved_actor = os.environ.pop("MEMORY_MESH_ACTOR", None)

    def tearDown(self):
        if self.saved_actor is None:
            os.environ.pop("MEMORY_MESH_ACTOR", None)
        else:
            os.environ["MEMORY_MESH_ACTOR"] = self.saved_actor
        self.holder.cleanup()

    def journals(self):
        return [
            json.loads(path.read_bytes())
            for path in sorted(self.vault.path(JOURNAL_DIR).glob("*.json"))
        ]

    def test_read_after_write_and_single_transaction_context(self):
        with curation_transaction(self.vault, run_id="visible") as tx:
            self.assertIs(current_transaction(self.vault), tx)
            fsutil.curator_write(self.vault, self.path, "updated")
            self.assertEqual(self.path.read_bytes(), b"updated")
            self.assertEqual(notes.load_note(self.path, self.vault).body, "updated")
            fsutil.curator_write(self.vault, self.path, "again")
        self.assertIsNone(current_transaction())
        self.assertEqual(self.path.read_bytes(), b"again")
        self.assertEqual(self.journals()[0]["state"], "committed")

    def test_noop_transactions_do_not_create_journals_or_rewrite(self):
        before = self.path.stat().st_mtime_ns
        for _ in range(3):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "original")
        self.assertEqual(before, self.path.stat().st_mtime_ns)
        self.assertEqual(self.journals(), [])

    def test_manual_source_edit_conflicts_before_any_destination_mutation(self):
        target = self.vault.path("knowledge/patterns/new-decision.md")
        with self.assertRaises(CurationConflict) as caught:
            with curation_transaction(self.vault):
                self.path.write_bytes(b"manual")
                fsutil.curator_write(self.vault, target, "proposed")
        self.assertFalse(target.exists())
        self.assertEqual(self.path.read_bytes(), b"manual")
        journal = json.loads(caught.exception.journal.read_bytes())
        conflict = journal["conflicts"][0]
        self.assertEqual(base64.b64decode(conflict["original"]), b"original")
        self.assertEqual(base64.b64decode(conflict["observed"]), b"manual")
        self.assertEqual(base64.b64decode(conflict["proposed"]["after"]), b"proposed")

    def test_same_length_and_restored_timestamp_edit_is_detected_by_content(self):
        stamp = self.path.stat()
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                self.path.write_bytes(b"manually")
                os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                fsutil.curator_write(self.vault, self.path, "decision")
        self.assertEqual(self.path.read_bytes(), b"manually")

    def test_rollback_restores_only_owned_postimages(self):
        second = self.vault.path("knowledge/patterns/another.md")
        with self.assertRaises(RuntimeError):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "ours")
                fsutil.curator_write(self.vault, second, "new")
                raise RuntimeError("interrupt")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertFalse(second.exists())
        self.assertEqual(self.journals()[0]["state"], "rolled-back")

    def test_rollback_preserves_concurrent_edit_and_other_owned_paths_restore(self):
        second = self.vault.path("knowledge/patterns/another.md")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "ours")
                fsutil.curator_write(self.vault, second, "new")
                self.path.write_bytes(b"manual later")
        self.assertEqual(self.path.read_bytes(), b"manual later")
        self.assertFalse(second.exists())
        self.assertEqual(self.journals()[0]["state"], "conflict")

    def test_swallowed_conflict_cannot_be_committed(self):
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                self.path.write_bytes(b"manual")
                try:
                    fsutil.curator_write(self.vault, self.path, "overwrite")
                except CurationConflict:
                    pass
        self.assertEqual(self.path.read_bytes(), b"manual")

    def test_expected_review_hashes_preserve_original_decision(self):
        expected = fsutil.content_hash(b"previously approved input")
        decision = {"kind": "SUPERSEDE", "new_content": "original approved decision"}
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault) as tx:
                tx.expect_hashes({self.vault.rel(self.path): expected}, decision=decision)
        journal = self.journals()[0]
        self.assertIn(decision, journal["decisions"])
        self.assertEqual(journal["conflicts"][0]["expected_hash"], expected)
        self.assertEqual(journal["conflicts"][0]["observed_hash"], fsutil.content_hash(b"original"))
        self.assertEqual(self.path.read_bytes(), b"original")

    def test_conflict_requires_explicit_acknowledgment_before_recompute(self):
        with self.assertRaises(CurationConflict) as caught:
            with curation_transaction(self.vault):
                self.path.write_bytes(b"manual")
        with self.assertRaisesRegex(CurationRecoveryError, "unresolved"):
            with curation_transaction(self.vault):
                pass
        acknowledge_curation_conflict(self.vault, caught.exception.journal.stem)
        with curation_transaction(self.vault):
            fsutil.curator_write(self.vault, self.path, "recomputed")
        self.assertEqual(self.path.read_bytes(), b"recomputed")
        journal = json.loads(caught.exception.journal.read_bytes())
        self.assertEqual(journal["conflicts"][0]["observed_hash"], fsutil.content_hash(b"manual"))

    def test_direct_atomic_write_and_append_are_intercepted(self):
        log = self.vault.path("_meta/curation-log.md")
        original_log = log.read_bytes() if log.exists() else None
        with self.assertRaises(RuntimeError):
            with curation_transaction(self.vault):
                fsutil.atomic_write(self.path, "atomic")
                fsutil.append_line(log, "transaction log")
                raise RuntimeError("rollback")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(log.read_bytes() if log.exists() else None, original_log)

    def test_curator_rename_and_unlink_are_recoverable(self):
        dest = self.vault.path("_meta/review/archive/moved.md")
        with self.assertRaises(RuntimeError):
            with curation_transaction(self.vault):
                fsutil.curator_rename(self.vault, self.path, dest)
                self.assertFalse(self.path.exists())
                self.assertEqual(dest.read_bytes(), b"original")
                fsutil.curator_unlink(self.vault, dest)
                raise RuntimeError("interrupt")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertFalse(dest.exists())

    def test_rename_never_replaces_existing_destination(self):
        dest = self.vault.path("knowledge/patterns/destination.md")
        dest.write_bytes(b"other source")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                fsutil.curator_rename(self.vault, self.path, dest)
        self.assertEqual(dest.read_bytes(), b"other source")
        self.assertEqual(self.path.read_bytes(), b"original")

    def test_new_contributions_during_curator_run_remain_available(self):
        contribution = self.vault.path("00-inbox/concurrent.md")
        with curation_transaction(self.vault):
            subprocess.run(
                [sys.executable, "-c",
                 "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'contributor')",
                 str(contribution)], check=True, capture_output=True,
            )
            fsutil.curator_write(self.vault, self.path, "curated")
        self.assertEqual(contribution.read_bytes(), b"contributor")

    def test_existing_lock_integration_avoids_reacquisition(self):
        with exclusive_lock(self.vault, "curator"):
            with curation_transaction(self.vault, existing_lock=True):
                fsutil.curator_write(self.vault, self.path, "v2")
                with self.assertRaises(ExperienceBusy):
                    with exclusive_lock(self.vault, "curator", timeout=0.02):
                        pass
        self.assertEqual(self.path.read_bytes(), b"v2")

    def test_nested_transaction_and_expired_context_fail(self):
        with curation_transaction(self.vault) as tx:
            with self.assertRaises(CurationRecoveryError):
                with curation_transaction(self.vault, existing_lock=True):
                    pass
        with self.assertRaises(CurationRecoveryError):
            tx.write(self.path, b"expired")

    def _child(self, body, *args):
        root = str(Path(__file__).resolve().parents[1])
        env = dict(os.environ, PYTHONPATH=root)
        code = (
            "import os, sys, time\nfrom pathlib import Path\n"
            "from memory_mesh.config import Vault\n"
            "from memory_mesh import fsutil\n"
            "from memory_mesh.curator.transaction import curation_transaction\n"
            "from memory_mesh.experience_store import ExperienceBusy\n"
            "v=Vault(Path(sys.argv[1]))\n"
            + body
        )
        return subprocess.Popen(
            [sys.executable, "-c", code, str(self.vault.root), *map(str, args)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )

    def test_two_processes_cannot_curate_same_vault(self):
        ready = self.vault.path("_meta/session-state/ready")
        child = self._child(
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','child')\n"
            " Path(sys.argv[2]).write_text('ready')\n"
            " time.sleep(30)\n", ready,
        )
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "child did not acquire the curator lock")
            with self.assertRaises(ExperienceBusy):
                with curation_transaction(self.vault):
                    pass
            self.assertEqual(self.path.read_bytes(), b"child")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        results = recover_curation_transactions(self.vault)
        self.assertEqual(results[0].state, "rolled-back")
        self.assertEqual(self.path.read_bytes(), b"original")
        with curation_transaction(self.vault):
            pass

    def test_process_death_after_first_file_recovers_before_next_run(self):
        child = self._child(
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','interrupted')\n"
            " os._exit(17)\n"
        )
        out, err = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 17, (out, err))
        self.assertEqual(self.path.read_bytes(), b"interrupted")
        with curation_transaction(self.vault):
            self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(recover_curation_transactions(self.vault), [])

    def test_crash_recovery_preserves_manual_edits(self):
        child = self._child(
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','interrupted')\n"
            " os._exit(18)\n"
        )
        child.communicate(timeout=10)
        self.assertEqual(child.returncode, 18)
        self.path.write_bytes(b"manual after death")
        result = recover_curation_transactions(self.vault)[0]
        self.assertEqual(result.state, "conflict")
        self.assertEqual(self.path.read_bytes(), b"manual after death")

    def test_interrupted_rollback_is_resumable_with_multiple_writes(self):
        raw = fsutil._atomic_write_bytes
        failed = False

        def interrupt(path, data, **kwargs):
            nonlocal failed
            if Path(path) == self.path and data == b"original" and not failed:
                failed = True
                raise OSError("simulated interrupted rollback")
            return raw(path, data, **kwargs)

        with mock.patch.object(fsutil, "_atomic_write_bytes", side_effect=interrupt):
            with self.assertRaisesRegex(CurationRecoveryError, "rollback interrupted"):
                with curation_transaction(self.vault):
                    fsutil.curator_write(self.vault, self.path, "first")
                    fsutil.curator_write(self.vault, self.path, "second")
                    raise RuntimeError("begin rollback")
        self.assertEqual(self.path.read_bytes(), b"first")
        result = recover_curation_transactions(self.vault)[0]
        self.assertEqual(result.state, "rolled-back")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(recover_curation_transactions(self.vault), [])

    def test_write_failure_before_replace_does_not_corrupt_existing_file(self):
        replace = os.replace

        def fail_target(source, destination):
            if Path(destination) == self.path:
                raise OSError("simulated failed replacement")
            return replace(source, destination)

        with mock.patch.object(fsutil.os, "replace", side_effect=fail_target):
            with self.assertRaises(OSError):
                with curation_transaction(self.vault):
                    fsutil.curator_write(self.vault, self.path, "failed")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(self.journals()[0]["state"], "rolled-back")

    def test_invalid_recovery_journal_fails_before_mutation(self):
        path = self.vault.path(JOURNAL_DIR) / ("0" * 32 + ".json")
        path.parent.mkdir(parents=True)
        path.write_text('{"version":1,"state":"active","operations": [', encoding="utf-8")
        with self.assertRaises(CurationRecoveryError):
            with curation_transaction(self.vault):
                self.fail("must not start with a broken recovery record")
        self.assertEqual(self.path.read_bytes(), b"original")

    def test_committed_git_transaction_is_not_rolled_back_after_crash(self):
        if not init_git(self.vault):
            self.skipTest("Git unavailable")
        child = self._child(
            "from memory_mesh import gitutil\n"
            "from memory_mesh.curator.transaction import CurationTransaction\n"
            "original=CurationTransaction.finish_git_commit\n"
            "def crash(self,*,committed,sha=None):\n"
            " if committed: os._exit(19)\n"
            " return original(self,committed=committed,sha=sha)\n"
            "CurationTransaction.finish_git_commit=crash\n"
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','committed')\n"
            " gitutil.commit_paths(v,['knowledge/patterns/transaction.md'],'fixture commit')\n"
        )
        out, err = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 19, (out, err))
        result = recover_curation_transactions(self.vault)[0]
        self.assertEqual(result.state, "committed")
        self.assertEqual(self.path.read_bytes(), b"committed")
        dirty = gitutil.dirty_paths(self.vault)
        self.assertNotIn(self.vault.rel(self.path), dirty)
        self.assertTrue(all(path.startswith("_meta/session-state/") for path in dirty), dirty)

    def test_completed_journal_does_not_block_later_path_reorganization(self):
        with curation_transaction(self.vault):
            fsutil.curator_write(self.vault, self.path, "committed")
        self.path.unlink()
        self.path.mkdir()
        with curation_transaction(self.vault):
            pass
        self.assertTrue(self.path.is_dir())

    def test_stale_decision_in_second_process_is_rejected_after_lock_releases(self):
        expected = fsutil.content_hash(b"original")
        first = self._child(
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','first process')\n"
        )
        out, err = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, (out, err))
        second = self._child(
            "from memory_mesh.curator.transaction import CurationConflict\n"
            "try:\n"
            " with curation_transaction(v):\n"
            "  fsutil.curator_write(v,'knowledge/patterns/transaction.md','second decision',expected_hash=sys.argv[2])\n"
            "except CurationConflict:\n"
            " sys.exit(23)\n", expected,
        )
        out, err = second.communicate(timeout=10)
        self.assertEqual(second.returncode, 23, (out, err))
        self.assertEqual(self.path.read_bytes(), b"first process")
        self.assertTrue(any(journal["state"] == "conflict" for journal in self.journals()))

    def test_process_death_before_replacement_recovers_original_and_intent(self):
        child = self._child(
            "raw=fsutil._atomic_write_bytes\n"
            "def crash(path,data,**kw):\n"
            " if Path(path)==v.path('knowledge/patterns/transaction.md'): os._exit(24)\n"
            " return raw(path,data,**kw)\n"
            "fsutil._atomic_write_bytes=crash\n"
            "with curation_transaction(v):\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','not yet applied')\n"
        )
        out, err = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 24, (out, err))
        self.assertEqual(self.path.read_bytes(), b"original")
        journal = self.journals()[0]
        self.assertEqual(base64.b64decode(journal["operations"][0]["after"]), b"not yet applied")
        self.assertEqual(recover_curation_transactions(self.vault)[0].state, "rolled-back")

    def test_late_manual_edit_during_rollback_is_reported_and_never_replaced(self):
        raw = fsutil._atomic_write_bytes

        def edit_before_restore(path, data, **kwargs):
            if Path(path) == self.path and data == b"original":
                self.path.write_bytes(b"late manual edit")
            return raw(path, data, **kwargs)

        with mock.patch.object(fsutil, "_atomic_write_bytes", side_effect=edit_before_restore):
            with self.assertRaises(CurationConflict):
                with curation_transaction(self.vault):
                    fsutil.curator_write(self.vault, self.path, "ours")
                    raise RuntimeError("other failed step")
        self.assertEqual(self.path.read_bytes(), b"late manual edit")
        self.assertEqual(self.journals()[0]["state"], "conflict")

    def test_low_level_write_preserves_existing_v2_lock_contract(self):
        with exclusive_lock(self.vault, "curator"):
            fsutil.curator_write(
                self.vault, self.path, "existing locked writer",
                expected_hash=fsutil.content_hash(b"original"),
            )
        self.assertEqual(self.path.read_bytes(), b"existing locked writer")
        self.assertFalse(self.vault.path(JOURNAL_DIR).exists())

    def test_git_failure_rolls_back_canonical_and_keeps_approved_review_pending(self):
        review = self.vault.path("_meta/review/pending.md")
        archive = self.vault.path("_meta/review/archive/pending.md")
        review.write_bytes(b"original approved decision")
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        head = gitutil.head_commit(self.vault)
        real_git = gitutil._git

        def rejected(vault, *args):
            if "commit" in args:
                return subprocess.CompletedProcess(args, 1, "", "fixture pre-commit rejection")
            return real_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=rejected):
            with self.assertRaises(CurationPublicationError):
                with curation_transaction(self.vault):
                    fsutil.curator_write(self.vault, self.path, "proposed admission")
                    fsutil.curator_rename(self.vault, review, archive)
                    result = gitutil.commit_paths(
                        self.vault,
                        [self.vault.rel(path) for path in (self.path, review, archive)],
                        "fixture publication attempt",
                    )
                    self.assertFalse(result.committed)
                    self.assertTrue(result.failed)
        self.assertEqual(gitutil.head_commit(self.vault), head)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(review.read_bytes(), b"original approved decision")
        self.assertFalse(archive.exists())
        self.assertEqual(self.journals()[0]["state"], "rolled-back")

    def test_no_git_retains_local_writes_without_claiming_publication(self):
        with mock.patch.object(gitutil, "available", return_value=False):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "local-only")
                result = gitutil.commit_paths(self.vault, [self.vault.rel(self.path)], "local change")
                self.assertFalse(result.committed)
                self.assertFalse(result.failed)
                self.assertTrue(result.manual_commit_required)
                self.assertIn("manual commit required", result.message)
        self.assertEqual(self.path.read_bytes(), b"local-only")
        self.assertEqual(self.journals()[0]["publication"], "manual-commit-required")

    def test_git_inspection_failure_before_staging_aborts_transaction(self):
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        before_index = gitutil._git(self.vault, "ls-files", "--stage").stdout
        real_git = gitutil._git

        def failed_status(vault, *args):
            if args and args[0] == "status":
                raise OSError("fixture Git inspection unavailable")
            return real_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=failed_status):
            with self.assertRaises(CurationPublicationError):
                with curation_transaction(self.vault):
                    fsutil.curator_write(self.vault, self.path, "not published")
                    result = gitutil.commit_paths(self.vault, [self.vault.rel(self.path)], "fail")
                    self.assertTrue(result.failed)
                    self.assertIn("git execution failed", result.message)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, before_index)

    def test_observe_registers_bounded_reads_without_reading_again(self):
        with curation_transaction(self.vault, inputs=()) as tx:
            with mock.patch("memory_mesh.curator.transaction._read", side_effect=AssertionError("extra read")):
                digest = tx.observe(self.path, b"original")
            self.assertEqual(digest, fsutil.content_hash(b"original"))
            self.assertEqual(tx.read_bytes(self.path), b"original")

    def test_observe_never_rebases_an_existing_input(self):
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault) as tx:
                self.path.write_bytes(b"changed")
                tx.observe(self.path, b"changed")
        self.assertEqual(self.path.read_bytes(), b"changed")

    def test_observed_absent_record_conflicts_with_later_creation(self):
        store = RecordStore(self.vault)
        path = store.record_path("tasks", "new-ledger")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault) as tx:
                tx.observe(path, None)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(store._document("tasks", "new-ledger", {"counter": 2}).encode())
                with store.transaction():
                    store.save("tasks", "new-ledger", {"counter": 1})
        self.assertEqual(store.load("tasks", "new-ledger"), {"counter": 2})

    def test_actual_records_and_both_receipt_kinds_roll_back_together(self):
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.save("tasks", "ledger", {"counter": 0})
        before = record.read_bytes()
        receipts = [attestations.attestation_path(self.vault, kind, "receipt-1")
                    for kind in ("admission", "execution")]
        with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
            with curation_transaction(self.vault) as tx:
                with store.transaction():
                    tx.observe(record, record.read_bytes())
                    store.save("tasks", "ledger", {"counter": 1})
                    for kind, path in zip(("admission", "execution"), receipts):
                        tx.observe(path, None)
                        attestations.write_attestation(self.vault, kind, "receipt-1", {"result": "passed"})
                    fsutil.curator_write(self.vault, self.path, "provisional")
                self.assertEqual(tx.publishable_paths, {
                    self.vault.rel(path) for path in [self.path, record, *receipts]
                })
                raise RuntimeError("fixture interruption")
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertTrue(all(not path.exists() for path in receipts))

    def test_record_rollback_holds_existing_experience_lock(self):
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.save("tasks", "ledger", {"counter": 0})
        before = record.read_bytes()
        raw_write = fsutil._atomic_write_bytes
        checked = []

        def guarded_write(path, data, **kwargs):
            if Path(path) == record and data == before:
                self.assertIsNone(store._owner)
                with self.assertRaises(ExperienceBusy):
                    with exclusive_lock(self.vault, "experience", timeout=0):
                        self.fail("rollback must exclude record writers")
                checked.append(True)
            return raw_write(path, data, **kwargs)

        with mock.patch.object(fsutil, "_atomic_write_bytes", side_effect=guarded_write):
            with self.assertRaises(RuntimeError):
                with curation_transaction(self.vault):
                    with store.transaction():
                        store.save("tasks", "ledger", {"counter": 1})
                    raise RuntimeError("abort")
        self.assertEqual(checked, [True])
        self.assertEqual(store.load("tasks", "ledger"), {"counter": 0})

    def test_publication_holds_record_lock_through_git_commit(self):
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.save("tasks", "ledger", {"counter": 0})
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        run_git = gitutil._git
        checked = []

        def guarded_git(vault, *args):
            if "commit" in args:
                with self.assertRaises(ExperienceBusy):
                    with exclusive_lock(vault, "experience", timeout=0):
                        self.fail("Git publication must exclude record writers")
                checked.append(True)
            return run_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=guarded_git):
            with curation_transaction(self.vault) as tx:
                with store.transaction():
                    store.save("tasks", "ledger", {"counter": 1})
                result = gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "record change")
                self.assertTrue(result.committed, result.message)
        self.assertEqual(checked, [True])
        self.assertNotIn(self.vault.rel(record), gitutil.dirty_paths(self.vault))

    def test_noop_immutable_receipts_are_not_removed_on_rollback(self):
        with RecordStore(self.vault).transaction():
            path = attestations.write_attestation(
                self.vault, "execution", "existing", {"result": "passed"},
            )
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            with curation_transaction(self.vault) as tx:
                tx.observe(path, before)
                with RecordStore(self.vault).transaction():
                    same = attestations.write_attestation(
                        self.vault, "execution", "existing", {"result": "passed"},
                    )
                self.assertEqual(same, path)
                raise RuntimeError("abort")
        self.assertEqual(path.read_bytes(), before)

    def test_swallowed_atomic_failure_still_aborts_the_run(self):
        raw_write = fsutil._atomic_write_bytes

        def fail_target(path, data, **kwargs):
            if Path(path) == self.path:
                raise OSError("fixture failure")
            return raw_write(path, data, **kwargs)

        with self.assertRaisesRegex(CurationRecoveryError, "mutation failed"):
            with curation_transaction(self.vault):
                with mock.patch.object(fsutil, "_atomic_write_bytes", side_effect=fail_target):
                    try:
                        fsutil.curator_write(self.vault, self.path, "failed")
                    except OSError:
                        pass
        self.assertEqual(self.path.read_bytes(), b"original")

    def test_publishable_paths_exclude_generated_packs_but_not_records(self):
        store = RecordStore(self.vault)
        with curation_transaction(self.vault) as tx:
            with store.transaction():
                record = store.save("tasks", "ledger", {"counter": 1})
            pack = fsutil.curator_write(self.vault, "outputs/context/test.md", "derived")
            self.assertIn(self.vault.rel(pack), tx.changed_paths)
            self.assertNotIn(self.vault.rel(pack), tx.publishable_paths)
            self.assertEqual(tx.publishable_paths, {self.vault.rel(record)})

    def test_git_refuses_to_publish_only_part_of_a_durable_transaction(self):
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        second = self.vault.path("knowledge/patterns/second.md")
        with self.assertRaises(CurationPublicationError):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "first")
                fsutil.curator_write(self.vault, second, "second")
                result = gitutil.commit_paths(self.vault, [self.vault.rel(self.path)], "partial")
                self.assertTrue(result.failed)
                self.assertIn("omits transaction-owned paths", result.message)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertFalse(second.exists())

    def _snapshot_read_count(self, *, no_op):
        paths = [self.path.with_name(f"scale-{number:03d}.md") for number in range(64)]
        for path in paths:
            path.write_bytes(b"baseline")
        tracked = set(paths)
        real_read = fsutil.read_regular_bytes
        reads = []

        def counted_read(path):
            if path in tracked:
                reads.append(path)
            return real_read(path)

        with mock.patch.object(fsutil, "read_regular_bytes", counted_read):
            with curation_transaction(self.vault, inputs=paths):
                for path in paths[:8]:
                    fsutil.curator_write(self.vault, path, "baseline" if no_op else "updated")
        return len(paths), 8, len(reads)

    def test_snapshot_read_budget_is_linear_in_files_plus_writes(self):
        count, writes, reads = self._snapshot_read_count(no_op=False)
        # Initial/first-write/final snapshots plus bounded atomic-replace retries.
        self.assertLessEqual(reads, 3 * count + 8 * writes)
        self.assertGreaterEqual(reads, 3 * count)

    def test_noop_writes_do_not_rescan_every_other_input(self):
        count, writes, reads = self._snapshot_read_count(no_op=True)
        self.assertLessEqual(reads, 2 * count + writes)

    def test_non_target_drift_rolls_back_provisional_visible_writes_at_exit(self):
        source = self.vault.path("00-inbox/source.md")
        source.write_bytes(b"source input")
        second = self.path.with_name("provisional.md")
        visible = []
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "first provisional write")
                source.write_bytes(b"concurrent input")
                fsutil.curator_write(self.vault, second, "second provisional write")
                visible.append(second.read_bytes())
        self.assertEqual(visible, [b"second provisional write"])
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertFalse(second.exists())
        self.assertEqual(source.read_bytes(), b"concurrent input")

    def test_non_target_drift_is_rejected_before_git_stages_provisional_writes(self):
        source = self.vault.path("00-inbox/source.md")
        source.write_bytes(b"source input")
        second = self.path.with_name("provisional.md")
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        before_index = gitutil._git(self.vault, "ls-files", "--stage").stdout
        reached_git = []
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault) as tx:
                fsutil.curator_write(self.vault, self.path, "first")
                source.write_bytes(b"concurrent input")
                fsutil.curator_write(self.vault, second, "second")
                reached_git.append(True)
                gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "must abort")
        self.assertEqual(reached_git, [True])
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, before_index)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertFalse(second.exists())

    def test_noop_does_not_skip_complete_validation_before_first_real_mutation(self):
        source = self.vault.path("00-inbox/source.md")
        source.write_bytes(b"source input")
        second = self.path.with_name("not-created.md")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, self.path, "original")
                source.write_bytes(b"concurrent input")
                fsutil.curator_write(self.vault, second, "invalid decision")
        self.assertFalse(second.exists())

    def test_process_death_recovers_actual_records_and_immutable_receipts(self):
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.save("tasks", "ledger", {"counter": 0})
        receipt = attestations.attestation_path(self.vault, "execution", "crashed")
        child = self._child(
            "from memory_mesh import attestations\n"
            "from memory_mesh.experience_store import RecordStore\n"
            "with curation_transaction(v):\n"
            " with RecordStore(v).transaction() as store:\n"
            "  store.save('tasks','ledger',{'counter':1})\n"
            "  attestations.write_attestation(v,'execution','crashed',{'result':'passed'})\n"
            "  fsutil.curator_write(v,'knowledge/patterns/transaction.md','provisional')\n"
            "  os._exit(31)\n"
        )
        out, err = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 31, (out, err))
        self.assertTrue(receipt.exists())
        self.assertEqual(store.load("tasks", "ledger"), {"counter": 1})
        result = recover_curation_transactions(self.vault)[0]
        self.assertEqual(result.state, "rolled-back")
        self.assertEqual(store.load("tasks", "ledger"), {"counter": 0})
        self.assertFalse(receipt.exists())
        self.assertEqual(self.path.read_bytes(), b"original")
        with store.transaction():
            self.assertTrue(record.exists())

    def test_crash_recovery_preserves_later_cooperating_record_update(self):
        store = RecordStore(self.vault)
        with store.transaction():
            store.save("tasks", "ledger", {"counter": 0})
        child = self._child(
            "from memory_mesh.experience_store import RecordStore\n"
            "with curation_transaction(v):\n"
            " with RecordStore(v).transaction() as store:\n"
            "  store.save('tasks','ledger',{'counter':1})\n"
            "  os._exit(32)\n"
        )
        out, err = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 32, (out, err))
        with store.transaction():
            store.save("tasks", "ledger", {"counter": 2})
        result = recover_curation_transactions(self.vault)[0]
        self.assertEqual(result.state, "conflict")
        self.assertEqual(store.load("tasks", "ledger"), {"counter": 2})

    def test_death_after_private_staging_leaves_real_index_clean(self):
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        before_index = self.vault.path(".git/index").read_bytes()
        child = self._child(
            "from memory_mesh import gitutil\n"
            "native=gitutil._git\n"
            "def crash(vault,*args):\n"
            " result=native(vault,*args)\n"
            " if args and args[0]=='add': os._exit(41)\n"
            " return result\n"
            "gitutil._git=crash\n"
            "with curation_transaction(v) as tx:\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','proposed')\n"
            " gitutil.commit_paths(v,sorted(tx.publishable_paths),'interrupted preparation')\n"
        )
        out, err = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 41, (out, err))
        self.assertEqual(self.vault.path(".git/index").read_bytes(), before_index)
        self.assertEqual(self.path.read_bytes(), b"proposed")
        self.assertEqual(recover_curation_transactions(self.vault)[0].state, "rolled-back")
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(self.vault.path(".git/index").read_bytes(), before_index)

    def test_death_after_commit_recovers_index_without_reverting_publication(self):
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        unrelated = self.vault.path("unrelated.txt")
        unrelated.write_bytes(b"user stage\n")
        self.assertEqual(gitutil._git(self.vault, "add", "--", "unrelated.txt").returncode, 0)
        before_patch = gitutil._git(self.vault, "diff", "--cached", "--binary", "--", "unrelated.txt").stdout
        child = self._child(
            "from memory_mesh import gitutil\n"
            "def crash(*args): os._exit(42)\n"
            "gitutil.reconcile_index=crash\n"
            "with curation_transaction(v) as tx:\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','published')\n"
            " gitutil.commit_paths(v,sorted(tx.publishable_paths),'interrupted reconciliation')\n"
        )
        out, err = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 42, (out, err))
        self.assertEqual(self.path.read_bytes(), b"published")
        self.assertEqual(recover_curation_transactions(self.vault)[0].state, "committed")
        self.assertEqual(self.path.read_bytes(), b"published")
        self.assertEqual(gitutil._git(self.vault, "diff", "--cached", "--binary", "--", "unrelated.txt").stdout, before_patch)
        self.assertEqual(gitutil._git(self.vault, "diff", "--cached", "--name-only").stdout.strip(), "unrelated.txt")

    def test_uncertain_git_process_blocks_rollback_until_confirmed_stopped(self):
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        before_index = self.vault.path(".git/index").read_bytes()
        child = self._child(
            "with curation_transaction(v) as tx:\n"
            " fsutil.curator_write(v,'knowledge/patterns/transaction.md','uncertain')\n"
            " tx.prepare_git_commit(isolated_index=True)\n"
            " tx.git_commit_started()\n"
            " os._exit(43)\n"
        )
        out, err = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 43, (out, err))
        with self.assertRaisesRegex(CurationRecoveryError, "may still be running"):
            recover_curation_transactions(self.vault)
        self.assertEqual(self.path.read_bytes(), b"uncertain")
        self.assertEqual(self.vault.path(".git/index").read_bytes(), before_index)
        with exclusive_lock(self.vault, "curator", timeout=0):
            pass
        result = recover_curation_transactions(self.vault, confirmed_git_stopped=True)[0]
        self.assertEqual(result.state, "rolled-back")
        self.assertEqual(self.path.read_bytes(), b"original")
