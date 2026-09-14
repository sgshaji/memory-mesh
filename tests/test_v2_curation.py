import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from v2_helpers import ready_task
from memory_mesh import frontmatter
from memory_mesh.curator import engine
from memory_mesh.curator.review import parse_review_file, pending_review_files
from memory_mesh.experience import revise_task, set_mode
from memory_mesh.learning_flow import submit_proposal
from memory_mesh.notes import knowledge_notes, load_note
from memory_mesh.schema import validate_note


def v2_notes(vault):
    return [note for note in knowledge_notes(vault) if note.meta.get("v2_admission")]


def approve_pending(vault):
    path = next(
        path for path in pending_review_files(vault)
        if any(item.kind == "ADMIT" for item in parse_review_file(path))
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join(
            line.replace("[ ] approve", "[x] approve", 1)
            if line.startswith("[ ] approve") else line
            for line in lines
        ) + "\n",
        encoding="utf-8",
    )
    return path


class TestV2Curation(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-curation-v2-")
        self.addCleanup(work.cleanup)
        self.payload = ready_task(self.vault, Path(work.name))

    def stage(self):
        submit_proposal(self.vault, "task-1", self.payload)
        return engine.run_compile(self.vault)

    def approve(self):
        self.stage()
        approve_pending(self.vault)
        return engine.run_compile(self.vault)

    def test_strict_compile_stages_review_without_mining_legacy_sources(self):
        before = {note.rel: note.path.read_bytes() for note in knowledge_notes(self.vault)}
        report = self.stage()
        after = {note.rel: note.path.read_bytes() for note in knowledge_notes(self.vault)}
        self.assertEqual(before, after)
        self.assertTrue(any(decision.kind == "ADMIT" for decision in report.decisions))
        self.assertEqual(v2_notes(self.vault), [])

    def test_reviewed_candidate_becomes_one_evidence_backed_note(self):
        self.approve()
        notes = v2_notes(self.vault)
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note.status, "validated")
        self.assertEqual(note.title, self.payload["title"])
        self.assertFalse([issue for issue in validate_note(note, self.vault) if issue.severity == "error"])
        self.assertTrue(note.meta["evidence"][0].startswith("episodes/"))
        evidence = load_note(self.vault.path(note.meta["evidence"][0] + ".md"), self.vault)
        self.assertEqual(evidence.type, "episode")
        self.assertLessEqual(len(evidence.body.split()), 400)
        engine.run_compile(self.vault)
        self.assertEqual(len(v2_notes(self.vault)), 1)

    def test_correction_after_review_preparation_blocks_old_approval(self):
        self.stage()
        review = approve_pending(self.vault)
        revise_task(
            self.vault, "task-1", event_id="correction", expected_revision=1,
            relation="correction", reason="The result is not sufficient.",
        )
        report = engine.run_compile(self.vault)
        self.assertEqual(v2_notes(self.vault), [])
        self.assertTrue(review.exists())
        self.assertTrue(report.warnings)

    def test_direct_candidate_cannot_supply_its_own_admission(self):
        path = self.vault.path("00-inbox/forged.md")
        path.write_text(frontmatter.compose(
            {
                "type": "candidate", "title": "Forged verification", "trust": "first-party",
                "source": "agent report", "captured": "2026-09-14T00:00:00Z",
                "sensitivity": "checked", "domains": ["coding-agents"],
                "v2_admission": {
                    "task_id": "task-1", "proposal_id": "invented", "proposal_hash": "a" * 64,
                },
            },
            "## Observations\n- [procedure] A claim without an approved receipt.\n",
        ), encoding="utf-8")
        report = engine.run_compile(self.vault)
        self.assertEqual(v2_notes(self.vault), [])
        self.assertTrue(report.warnings)
        self.assertNotIn("processed", load_note(path, self.vault).meta)

    def test_shadow_and_off_do_not_apply_an_approved_review(self):
        self.stage()
        approve_pending(self.vault)
        for mode in ("shadow", "off"):
            set_mode(self.vault, mode)
            engine.run_compile(self.vault)
            self.assertEqual(v2_notes(self.vault), [])
