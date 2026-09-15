import io
import tempfile
import unittest
from contextlib import redirect_stdout
from contextvars import Context
from pathlib import Path
from unittest.mock import patch

from helpers import init_git, make_vault
from test_v2_curation import approve_pending
from v2_helpers import ready_task

from memory_mesh.cli import _print_run
from memory_mesh.config import VaultError
from memory_mesh.curator import engine
from memory_mesh.curator.transaction import CurationConflict, curation_transaction
from memory_mesh.experience_store import RecordStore
from memory_mesh.gitutil import CommitResult, _git
from memory_mesh.learning_flow import submit_proposal
from memory_mesh import attestations, fsutil


class PublicationResultTests(unittest.TestCase):
    def test_failed_git_is_not_a_successful_cli_result(self):
        report = engine.RunReport("failed-publication")
        report.commit = CommitResult(False, None, "git commit failed: fixture rejection", True)
        with redirect_stdout(io.StringIO()) as output:
            result = _print_run(None, report)
        self.assertEqual(result, 1)
        self.assertIn("git commit failed", output.getvalue())


class RecordStoreCurationTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.store = RecordStore(self.vault)
        with self.store.transaction():
            self.path = self.store.save("tasks", "ledger", {"counter": 0})

    def test_record_store_writes_join_outer_curation_rollback(self):
        before = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
            with curation_transaction(self.vault):
                with self.store.transaction():
                    value = self.store.load("tasks", "ledger")
                    value["counter"] = 1
                    self.store.save("tasks", "ledger", value)
                raise RuntimeError("fixture interruption")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.load("tasks", "ledger"), {"counter": 0})

    def test_changed_record_is_preserved_instead_of_overwritten(self):
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                with self.store.transaction():
                    self.store.load("tasks", "ledger")
                    self.path.write_bytes(
                        self.store._document("tasks", "ledger", {"counter": 2}).encode("utf-8")
                    )
                    self.store.save("tasks", "ledger", {"counter": 1})
        self.assertEqual(self.store.load("tasks", "ledger"), {"counter": 2})

    def test_an_observed_missing_record_cannot_appear_unnoticed(self):
        missing = self.store.record_path("tasks", "missing")
        target = self.vault.path("knowledge/patterns/absence-decision.md")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                self.assertIsNone(self.store.load("tasks", "missing"))
                missing.write_bytes(
                    self.store._document("tasks", "missing", {"counter": 2}).encode("utf-8")
                )
                fsutil.curator_write(self.vault, target, "decision based on absence")
        self.assertFalse(target.exists())
        self.assertEqual(self.store.load("tasks", "missing"), {"counter": 2})

    def test_an_observed_missing_receipt_cannot_appear_unnoticed(self):
        target = self.vault.path("knowledge/patterns/receipt-absence-decision.md")

        def independent_producer():
            with RecordStore(self.vault).transaction():
                attestations.write_attestation(self.vault, "execution", "later", {"tests_run": 1})

        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                self.assertIsNone(attestations.read_attestation(self.vault, "execution", "later"))
                Context().run(independent_producer)
                fsutil.curator_write(self.vault, target, "decision based on missing receipt")
        self.assertFalse(target.exists())
        self.assertEqual(attestations.read_attestation(self.vault, "execution", "later"), {"tests_run": 1})


class StrictCurationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        workspace = tempfile.TemporaryDirectory(prefix="mm-v2-transaction-")
        self.addCleanup(workspace.cleanup)
        proposal = ready_task(self.vault, Path(workspace.name))
        submit_proposal(self.vault, "task-1", proposal)
        self.assertTrue(init_git(self.vault))
        engine.run_compile(self.vault)
        approve_pending(self.vault)

    def snapshot(self):
        roots = ("knowledge", "00-inbox", "episodes", "_meta/review", "projects")
        return {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for folder in roots for path in self.vault.path(folder).rglob("*.md")
        }

    def test_strict_admission_and_ledger_roll_back_together(self):
        before = self.snapshot()
        with patch("memory_mesh.curator.engine._finalise_run", side_effect=VaultError("fixture interruption")):
            with self.assertRaises(VaultError):
                engine.run_compile(self.vault)
        self.assertEqual(self.snapshot(), before)
        state = RecordStore(self.vault).load("tasks", "task-1")
        self.assertEqual(state["proposals"]["lesson-1"]["state"], "pending")

    def test_failed_git_preserves_approval_and_unrelated_stages_then_retries(self):
        unrelated = self.vault.path("unrelated.txt")
        unrelated.write_text("user-staged content\n", encoding="utf-8")
        self.assertEqual(_git(self.vault, "add", "--", "unrelated.txt").returncode, 0)
        before_stage = _git(self.vault, "diff", "--cached", "--binary").stdout
        before = self.snapshot()
        hook = self.vault.path(".git/hooks/pre-commit")
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o700)
        try:
            report = engine.run_compile(self.vault)
        except VaultError:
            pass
        else:
            self.assertIsNotNone(report.commit)
            self.assertTrue(report.commit.failed)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(_git(self.vault, "diff", "--cached", "--binary").stdout, before_stage)
        hook.unlink()
        report = engine.run_compile(self.vault)
        self.assertTrue(report.commit.committed)
        self.assertEqual(_git(self.vault, "diff", "--cached", "--name-only").stdout.strip(), "unrelated.txt")


if __name__ == "__main__":
    unittest.main()
