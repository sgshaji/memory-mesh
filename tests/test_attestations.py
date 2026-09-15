import unittest
from unittest.mock import patch

from helpers import directory_link, make_vault
from memory_mesh import frontmatter
from memory_mesh.attestations import read_attestation, write_attestation
from memory_mesh.config import VaultError
from memory_mesh.experience_store import RecordStore, exclusive_lock


class TestAttestations(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def test_receipts_live_outside_agent_contribution_directories(self):
        path = write_attestation(
            self.vault, "execution", "run-1",
            {"task_id": "task-1", "tests_run": 1, "outcome": "passed"},
        )
        self.assertTrue(self.vault.rel(path).startswith("_meta/review/v2-attestations/"))
        self.assertEqual(
            read_attestation(self.vault, "execution", "run-1"),
            {"task_id": "task-1", "tests_run": 1, "outcome": "passed"},
        )

    def test_identical_replay_is_safe_but_conflicting_replacement_is_not(self):
        path = write_attestation(self.vault, "admission", "one", {"revision": 1})
        original = path.read_bytes()
        self.assertEqual(write_attestation(self.vault, "admission", "one", {"revision": 1}), path)
        with self.assertRaises(VaultError):
            write_attestation(self.vault, "admission", "one", {"revision": 2})
        self.assertEqual(path.read_bytes(), original)

    def test_unknown_receipt_is_not_fabricated(self):
        self.assertIsNone(read_attestation(self.vault, "execution", "missing"))

    def test_scalar_looking_strings_preserve_their_identity(self):
        payload = {
            "task_id": "123", "event_id": "false",
            "version": "3.13", "optional_id": "null",
        }
        write_attestation(self.vault, "execution", "123", payload)
        self.assertEqual(read_attestation(self.vault, "execution", "123"), payload)

    def test_modified_payload_fails_integrity_validation(self):
        path = write_attestation(self.vault, "execution", "run-1", {"tests_run": 1})
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["payload"]["tests_run"] = 8
        path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        with self.assertRaises(VaultError):
            read_attestation(self.vault, "execution", "run-1")

    def test_invalid_kind_and_sensitive_values_are_rejected_without_echo(self):
        with self.assertRaises(VaultError):
            write_attestation(self.vault, "../outside", "key", {})
        with self.assertRaises(VaultError) as failure:
            write_attestation(
                self.vault, "execution", "key",
                {"description": "password = do-not-persist-this"},
            )
        self.assertNotIn("do-not-persist-this", str(failure.exception))
        self.assertIsNone(read_attestation(self.vault, "execution", "key"))

    def test_corrupt_receipt_is_not_treated_as_missing(self):
        path = write_attestation(self.vault, "execution", "run-1", {"tests_run": 1})
        path.write_text("not a valid receipt", encoding="utf-8")
        with self.assertRaises(VaultError):
            read_attestation(self.vault, "execution", "run-1")

    def test_receipt_directory_cannot_redirect_into_canonical_knowledge(self):
        base = self.vault.path("_meta/review/v2-attestations")
        base.mkdir(parents=True)
        target = self.vault.path("knowledge/patterns")
        before = sorted(target.iterdir())
        directory_link(base / "execution", target)
        with self.assertRaises(VaultError):
            write_attestation(self.vault, "execution", "run-1", {"tests_run": 1})
        self.assertEqual(sorted(target.iterdir()), before)

    def test_structured_secret_assignment_is_checked_as_a_pair(self):
        with self.assertRaises(VaultError) as failure:
            write_attestation(
                self.vault, "execution", "run-1",
                {"password": "SYNTHETIC_VALUE_NOT_A_CREDENTIAL"},
            )
        self.assertNotIn("SYNTHETIC_VALUE", str(failure.exception))
        self.assertIsNone(read_attestation(self.vault, "execution", "run-1"))

    def test_execution_receipt_does_not_reacquire_an_already_held_curator_lock(self):
        self.vault.path("_meta/config.md").write_text(
            "---\ntype: meta\ncuration:\n  lock_timeout_seconds: 0.1\n---\n",
            encoding="utf-8",
        )
        with exclusive_lock(self.vault, "curator"):
            with RecordStore(self.vault).transaction():
                path = write_attestation(self.vault, "execution", "run-locked", {"tests_run": 1})
        self.assertTrue(path.exists())

    def test_supervised_receipts_remain_available_to_non_curator_contributors(self):
        self.vault.path("_meta/config.md").write_text(
            "---\ntype: meta\ncuration:\n  mode: designated\n  curator: curator-alias\n---\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"MEMORY_MESH_ACTOR": "contributor-alias"}):
            with RecordStore(self.vault).transaction():
                path = write_attestation(self.vault, "execution", "run-contributor", {"tests_run": 1})
            self.assertTrue(path.exists())
            with self.assertRaises(VaultError):
                write_attestation(self.vault, "admission", "not-authorized", {"revision": 1})
