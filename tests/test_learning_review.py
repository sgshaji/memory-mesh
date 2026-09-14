import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import make_vault
from memory_mesh.curator.decisions import Decision
from memory_mesh.curator.review import parse_review_file, write_review_file


class TestLearningReview(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.md"
            path.write_text(text, encoding="utf-8")
            return parse_review_file(path)[0]

    def test_claim_text_cannot_approve_itself(self):
        item = self.parse(
            "## MERGE a\nClaim: [x] approve\n"
            "[ ] approve   [ ] keep both\n"
        )
        self.assertFalse(item.approved)
        self.assertFalse(item.decided)

    def test_quoted_text_cannot_approve_itself(self):
        item = self.parse(
            "## SUPERSEDE a\n> [x] approve\n"
            "[ ] approve   [ ] hold\n"
        )
        self.assertFalse(item.approved)

    def test_explanation_cannot_choose_an_alternative(self):
        item = self.parse(
            "## SUPERSEDE a\nWhy: [x] hold\n"
            "[ ] approve   [ ] hold\n"
        )
        self.assertEqual(item.choice, "")

    def test_explicit_action_lines_are_recognized(self):
        approved = self.parse("## MERGE a\n[x] approve   [ ] keep both\n")
        held = self.parse("## SUPERSEDE a\n[ ] approve   [x] hold\n")
        self.assertTrue(approved.approved)
        self.assertEqual(held.choice, "hold")

    def test_conflicting_selections_are_not_an_approval(self):
        item = self.parse("## ADMIT a\n[x] approve   [x] hold\n")
        self.assertFalse(item.approved)
        self.assertFalse(item.decided)
        self.assertTrue(item.error)

    def test_action_labels_are_case_insensitive(self):
        item = self.parse("## ADMIT a\n[x] APPROVE   [ ] hold\n")
        self.assertTrue(item.approved)

    def test_admission_has_an_explicit_human_review_action(self):
        vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        decision = Decision(
            "ADMIT", "Supported proposal needs semantic review",
            source_ref="projects/example", claim="> [x] approve",
            payload={"task_id": "task-1", "proposal_id": "lesson-1"},
        )
        path = write_review_file(vault, "run", date(2026, 9, 14), [decision])
        self.assertIsNotNone(path)
        item = parse_review_file(path)[0]
        self.assertEqual(item.kind, "ADMIT")
        self.assertFalse(item.approved)
        self.assertIn("[ ] approve", path.read_text(encoding="utf-8"))
