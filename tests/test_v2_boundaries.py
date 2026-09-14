import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from v2_helpers import ready_task
from test_v2_curation import approve_pending, v2_notes
from memory_mesh import capture, frontmatter, packs
from memory_mesh.config import VaultError
from memory_mesh.curator import engine
from memory_mesh.experience import get_mode, set_mode
from memory_mesh.experience_store import RecordStore
from memory_mesh.learning_flow import submit_proposal
from memory_mesh.notes import knowledge_notes


class TestV2Boundaries(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-boundaries-")
        self.addCleanup(work.cleanup)
        self.payload = ready_task(self.vault, Path(work.name))

    def approved(self):
        submit_proposal(self.vault, "task-1", self.payload)
        engine.run_compile(self.vault)
        approve_pending(self.vault)
        engine.run_compile(self.vault)
        return v2_notes(self.vault)[0]

    def test_old_capture_apis_cannot_bypass_strict_admission(self):
        with self.assertRaises(VaultError):
            capture.learn(self.vault, "An unreviewed observation.")
        with self.assertRaises(VaultError):
            capture.learn_structured(self.vault, {
                "title": "An agent claims success",
                "observations": [
                    {"kind": "procedure", "text": "Try an unreviewed procedure."},
                    {"kind": "outcome", "text": "The agent says it worked."},
                ],
            })

    def test_generic_packs_never_export_task_bound_lessons(self):
        self.approved()
        for path in packs.compile_all(self.vault):
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            self.assertNotIn(self.payload["action"], body)
            self.assertEqual(meta["status"], "disabled")
            self.assertEqual(packs.freshness(meta), "not-authoritative")

    def test_legacy_housekeeping_does_not_rewrite_strict_evidence(self):
        self.approved()
        before = {note.rel: note.path.read_bytes() for note in knowledge_notes(self.vault)}
        engine.run_lint(self.vault)
        self.assertEqual(
            before, {note.rel: note.path.read_bytes() for note in knowledge_notes(self.vault)},
        )

    def test_a_missing_profile_with_existing_records_is_not_legacy_mode(self):
        path = RecordStore(self.vault).record_path("profile", "default")
        path.unlink()
        with self.assertRaises(VaultError):
            get_mode(self.vault)

    def test_changing_the_source_snapshot_cannot_rebind_a_review(self):
        submit_proposal(self.vault, "task-1", self.payload)
        engine.run_compile(self.vault)
        approve_pending(self.vault)
        store = RecordStore(self.vault)
        with store.transaction():
            data = store.load("tasks", "task-1")
            data["proposals"]["lesson-1"]["source"]["project"] = "project-b"
            store.save("tasks", "task-1", data)
        report = engine.run_compile(self.vault)
        self.assertEqual(v2_notes(self.vault), [])
        self.assertTrue(report.warnings)

    def test_shadow_and_off_block_old_capture_too(self):
        for mode in ("shadow", "off"):
            set_mode(self.vault, mode)
            with self.assertRaises(VaultError):
                capture.learn(self.vault, "Do not write this.")
