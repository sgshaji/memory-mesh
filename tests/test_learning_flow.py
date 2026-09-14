import copy
import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from v2_helpers import ready_task
from memory_mesh.config import VaultError
from memory_mesh.experience import revise_task, set_mode
from memory_mesh.experience_store import RecordStore
from memory_mesh.learning_flow import review_decisions, submit_proposal


class TestLearningFlow(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-learning-")
        self.addCleanup(work.cleanup)
        self.payload = ready_task(self.vault, Path(work.name))
        self.store = RecordStore(self.vault)
        self.inbox_before = sorted(self.vault.path("00-inbox").glob("*.md"))

    def proposals(self):
        return self.store.load("tasks", "task-1")["proposals"]

    def test_no_proposal_and_unverified_claim_do_not_create_records(self):
        self.assertEqual(submit_proposal(self.vault, "task-1", None)["outcome"], "ignore")
        payload = {**self.payload, "evidence_ids": ["nonexistent"]}
        self.assertEqual(submit_proposal(self.vault, "task-1", payload)["outcome"], "defer")
        self.assertEqual(self.proposals(), {})
        self.assertEqual(sorted(self.vault.path("00-inbox").glob("*.md")), self.inbox_before)

    def test_supported_proposal_waits_for_review_before_candidate_capture(self):
        result = submit_proposal(self.vault, "task-1", self.payload)
        self.assertEqual(result["outcome"], "review")
        self.assertEqual(len(self.proposals()), 1)
        self.assertEqual(sorted(self.vault.path("00-inbox").glob("*.md")), self.inbox_before)
        decisions = review_decisions(self.vault)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].kind, "ADMIT")
        self.assertTrue(decisions[0].gated)

    def test_shadow_only_previews_without_persisting_a_proposal(self):
        set_mode(self.vault, "shadow")
        result = submit_proposal(self.vault, "task-1", self.payload)
        self.assertEqual(result["outcome"], "review")
        self.assertTrue(result["shadow"])
        self.assertEqual(self.proposals(), {})

    def test_duplicate_proposal_does_not_create_more_support(self):
        first = submit_proposal(self.vault, "task-1", self.payload)
        self.assertEqual(submit_proposal(self.vault, "task-1", self.payload), first)
        alias = {**self.payload, "proposal_id": "renamed-proposal"}
        result = submit_proposal(self.vault, "task-1", alias)
        self.assertEqual(result["outcome"], "ignore")
        self.assertEqual(len(self.proposals()), 1)

    def test_conflicting_reuse_of_proposal_identity_is_rejected(self):
        submit_proposal(self.vault, "task-1", self.payload)
        with self.assertRaises(VaultError):
            submit_proposal(self.vault, "task-1", {**self.payload, "action": "A different claim."})
        self.assertEqual(len(self.proposals()), 1)

    def test_correction_invalidates_pending_review(self):
        submit_proposal(self.vault, "task-1", self.payload)
        revise_task(
            self.vault, "task-1", event_id="correction", expected_revision=1,
            relation="correction", reason="The intended behavior still needs investigation.",
        )
        self.assertEqual(review_decisions(self.vault), [])
        result = submit_proposal(self.vault, "task-1", {**self.payload, "proposal_id": "old-context"})
        self.assertEqual(result["outcome"], "defer")

    def test_sensitive_proposal_is_not_persisted_or_echoed(self):
        payload = copy.deepcopy(self.payload)
        payload["action"] = "Use password = do-not-store-this to fix it."
        with self.assertRaises(VaultError) as failure:
            submit_proposal(self.vault, "task-1", payload)
        self.assertNotIn("do-not-store-this", str(failure.exception))
        self.assertEqual(self.proposals(), {})

    def test_unknown_domain_is_not_silently_classified(self):
        with self.assertRaises(VaultError):
            submit_proposal(self.vault, "task-1", {**self.payload, "domain": "not-declared"})
