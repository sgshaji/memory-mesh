import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from test_v2_curation import approve_pending, v2_notes
from v2_helpers import ready_task
from memory_mesh import recall
from memory_mesh.config import VaultError
from memory_mesh.curator import engine
from memory_mesh.experience import create_task, get_task
from memory_mesh.experience_store import RecordStore
from memory_mesh.learning_flow import record_feedback, submit_proposal


class TestReuseFeedback(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        source = tempfile.TemporaryDirectory(prefix="mm-feedback-source-")
        target = tempfile.TemporaryDirectory(prefix="mm-feedback-target-")
        self.addCleanup(source.cleanup)
        self.addCleanup(target.cleanup)
        payload = ready_task(self.vault, Path(source.name))
        submit_proposal(self.vault, "task-1", payload)
        engine.run_compile(self.vault)
        approve_pending(self.vault)
        engine.run_compile(self.vault)
        self.note = v2_notes(self.vault)[0]
        ready_task(self.vault, Path(target.name), task_id="target", project="project-b")
        self.revision = self.note.meta["v2_admission"]["proposal_hash"]

    def record(self, **changes):
        args = {
            "task_id": "target", "event_id": "use-1", "note_ref": self.note.ref,
            "lesson_revision": self.revision, "outcome": "held",
            "reason": "The declared check was exercised with this lesson in use.",
            "evidence_ids": ["check-1"],
        }
        args.update(changes)
        return record_feedback(self.vault, **args)

    def test_supported_use_is_recorded_without_claiming_causal_savings(self):
        before = self.note.path.read_bytes()
        result = self.record()
        self.assertTrue(result["recorded"])
        self.assertFalse(result["causal_claims_supported"])
        self.assertEqual(result["verification"], "execution-observed")
        self.assertEqual(self.note.path.read_bytes(), before)

    def test_retries_and_retellings_do_not_create_independent_confirmations(self):
        self.record()
        replay = self.record()
        self.assertTrue(replay["replayed"])
        again = self.record(event_id="use-2")
        self.assertEqual(again["distinct_task_records"], 1)
        data = RecordStore(self.vault).load("tasks", "task-1")
        self.assertEqual(len(data["proposals"]["lesson-1"]["feedback"]), 1)

    def test_conflicting_feedback_identity_is_rejected(self):
        self.record()
        with self.assertRaises(VaultError):
            self.record(reason="Changed content for the same event")

    def test_success_without_check_evidence_remains_unverified(self):
        result = self.record(evidence_ids=[])
        self.assertFalse(result["recorded"])
        self.assertEqual(result["outcome"], "defer")

    def test_reported_failure_holds_future_recall_without_rewriting_history(self):
        before = self.note.path.read_bytes()
        result = self.record(
            outcome="failed", evidence_ids=[],
            reason="The prior conclusion does not resolve the current case.",
        )
        self.assertTrue(result["recorded"])
        self.assertEqual(result["verification"], "reported")
        self.assertEqual(self.note.path.read_bytes(), before)
        recalled = recall.recall(self.vault, "repo runtime", task_id="target", log=False)
        self.assertEqual(recalled.notes, [])

    def test_feedback_cannot_attach_to_another_lesson_revision(self):
        with self.assertRaises(VaultError):
            self.record(lesson_revision="b" * 64)
