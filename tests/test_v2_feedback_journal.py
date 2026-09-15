import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import test_reuse_feedback as fixtures

from memory_mesh.config import VaultError
from memory_mesh.experience_store import RecordStore
from memory_mesh.outcomes import read_events
from memory_mesh.curator import engine
from memory_mesh.learning_flow import submit_proposal
from test_v2_curation import approve_pending, v2_notes
from v2_helpers import ready_task


class V2FeedbackJournalTests(unittest.TestCase):
    def setUp(self):
        fixtures.TestReuseFeedback.setUp(self)

    def record(self, **changes):
        return fixtures.TestReuseFeedback.record(self, **changes)

    def test_distinct_outcomes_preserve_full_history_and_one_task_summary(self):
        before = self.note.path.read_bytes()
        self.record()
        self.record(event_id="use-2", outcome="failed", evidence_ids=[], reason="behaviour_changed")
        entry = RecordStore(self.vault).load("tasks", "task-1")["proposals"]["lesson-1"]
        self.assertEqual(len(entry["feedback"]), 1)
        self.assertEqual(len(entry["feedback_history"]), 2)
        events = read_events(self.vault, session_id="target")
        self.assertEqual({event.outcome for event in events}, {"held", "failed"})
        self.assertTrue(all(event.source == "v2-reuse" for event in events))
        self.assertEqual(self.note.path.read_bytes(), before)

    def test_retry_repairs_failed_projection_using_original_timestamp(self):
        with patch("memory_mesh.outcomes.record_outcome", side_effect=VaultError("fixture write failure")):
            with self.assertRaisesRegex(VaultError, "receipt was saved"):
                self.record()
        store = RecordStore(self.vault)
        entry = store.load("tasks", "task-1")["proposals"]["lesson-1"]
        original = next(iter(entry["feedback_history"].values()))
        self.record(event_id="use-2", outcome="failed", evidence_ids=[], reason="unknown")
        replay = self.record()
        self.assertTrue(replay["replayed"])
        events = read_events(self.vault, session_id="target")
        held = next(event for event in events if event.outcome == "held")
        self.assertEqual(held.timestamp, original["timestamp"])
        self.record()
        self.assertEqual(len(read_events(self.vault, session_id="target")), 2)

    def test_unverified_success_does_not_create_a_shared_outcome(self):
        result = self.record(evidence_ids=[])
        self.assertFalse(result["recorded"])
        self.assertEqual(read_events(self.vault, session_id="target"), [])

    def test_legacy_replay_does_not_fabricate_missing_history(self):
        with patch("memory_mesh.learning_flow._publish_feedback_projection"):
            self.record()
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.load("tasks", "task-1")
            record["proposals"]["lesson-1"].pop("feedback_history")
            store.save("tasks", "task-1", record)
        replay = self.record()
        self.assertTrue(replay["recorded"])
        self.assertEqual(replay["feedback_journal"], "legacy-receipt-only")
        self.assertEqual(read_events(self.vault, session_id="target"), [])

    def test_replay_rejects_history_context_that_does_not_match_the_request(self):
        with patch("memory_mesh.outcomes.record_outcome", side_effect=VaultError("fixture write failure")):
            with self.assertRaises(VaultError):
                self.record(outcome="failed", reason="misapplied", evidence_ids=[])
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.load("tasks", "task-1")
            history = next(iter(record["proposals"]["lesson-1"]["feedback_history"].values()))
            history["context"]["project"] = "project-a"
            store.save("tasks", "task-1", record)
        with self.assertRaisesRegex(VaultError, "does not match"):
            self.record(outcome="failed", reason="misapplied", evidence_ids=[])
        self.assertEqual(read_events(self.vault, session_id="target"), [])

    def test_two_origins_can_reuse_the_same_local_proposal_and_event_labels(self):
        workspace = tempfile.TemporaryDirectory(prefix="mm-second-feedback-origin-")
        self.addCleanup(workspace.cleanup)
        proposal = ready_task(self.vault, Path(workspace.name), task_id="second-origin")
        submit_proposal(self.vault, "second-origin", proposal)
        engine.run_compile(self.vault)
        approve_pending(self.vault)
        engine.run_compile(self.vault)
        second = next(
            note for note in v2_notes(self.vault)
            if note.meta["v2_admission"]["task_id"] == "second-origin"
        )
        first_result = self.record(event_id="shared-use")
        second_args = {
            "event_id": "shared-use", "note_ref": second.ref,
            "lesson_revision": second.meta["v2_admission"]["proposal_hash"],
        }
        second_result = self.record(**second_args)
        self.assertNotEqual(first_result["feedback_event"], second_result["feedback_event"])
        self.assertEqual(
            {event.subject_id for event in read_events(self.vault, session_id="target")},
            {self.note.ref, second.ref},
        )
        self.assertTrue(self.record(event_id="shared-use")["replayed"])
        self.assertTrue(self.record(**second_args)["replayed"])
        self.assertEqual(len(read_events(self.vault, session_id="target")), 2)

    def test_preexisting_legacy_projection_ids_are_not_renamed_on_replay(self):
        with patch("memory_mesh.learning_flow._publish_feedback_projection"):
            self.record()
        store = RecordStore(self.vault)
        with store.transaction():
            record = store.load("tasks", "task-1")
            history = record["proposals"]["lesson-1"]["feedback_history"]
            key = next(iter(history))
            legacy_id = "v2-" + key.removeprefix("reuse-")
            history[key]["event_id"] = legacy_id
            store.save("tasks", "task-1", record)
        result = self.record()
        self.assertEqual(result["feedback_event"], legacy_id)
        self.assertEqual(read_events(self.vault, session_id="target")[0].event_id, legacy_id)
        self.assertTrue(self.record()["replayed"])
        self.assertEqual(len(read_events(self.vault, session_id="target")), 1)


if __name__ == "__main__":
    unittest.main()
