import unittest

from helpers import make_vault

from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.schema import validate_note
from memory_mesh.recall import recall
from memory_mesh.routing_diagnostics import read_attempts


class FeedbackSchemaTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def validate(self, path, meta, body=""):
        target = self.vault.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(compose(meta, body), encoding="utf-8")
        return [
            issue.message for issue in validate_note(load_note(target, self.vault), self.vault)
            if issue.severity == "error"
        ]

    def candidate(self, **values):
        return dict(
            type="candidate", title="An observation", source="cli",
            captured="2026-09-14T12:00:00Z", trust="first-party",
            sensitivity="checked", **values,
        )

    def test_legacy_candidate_and_optional_signal(self):
        for signal in (None, "low", "normal", "high"):
            meta = self.candidate()
            if signal is not None:
                meta["signal"] = signal
            self.assertEqual(self.validate("00-inbox/a.md", meta), [])
        self.assertTrue(self.validate("00-inbox/a.md", self.candidate(signal="urgent")))

    def test_gap_is_a_need_not_factual_knowledge(self):
        meta = self.candidate(need="Connector import authentication")
        meta["type"] = "gap"
        self.assertEqual(self.validate("00-inbox/gap.md", meta), [])
        meta["confidence"] = "high"
        self.assertTrue(any("factual knowledge" in error for error in self.validate("00-inbox/gap.md", meta)))

    def test_partial_summarised_episode_requires_no_fabricated_sections(self):
        meta = dict(
            type="episode", tool="cli", captured="2026-09-14T12:00:00Z",
            trust="first-party", sensitivity="checked", status="summarised",
            recall_quality="off-target",
        )
        body = "## Knowledge used\n- [[validation-order]] held: checked\n\n## Candidate learnings\n- Validate before reasoning.\n"
        self.assertEqual(self.validate("episodes/partial.md", meta, body), [])
        meta["recall_quality"] = "invalid"
        self.assertTrue(self.validate("episodes/partial.md", meta, body))

    def test_calendar_timestamp_errors_are_reported(self):
        meta = self.candidate()
        meta["captured"] = "2026-02-30T12:00:00Z"
        self.assertTrue(self.validate("00-inbox/a.md", meta))

    def test_legacy_skill_and_structured_dependencies(self):
        meta = {"type": "skill", "title": "Validation"}
        self.assertEqual(self.validate("skills/validate.md", meta), [])
        meta["depends_on"] = ["knowledge/patterns/validation-order"]
        meta["applies_to"] = {"product": "copilot-studio", "version": ">=2026-01"}
        self.assertEqual(self.validate("skills/validate.md", meta), [])
        meta["depends_on"] = "not-a-list"
        self.assertTrue(self.validate("skills/validate.md", meta))

    def test_named_skill_descriptors_need_no_type_migration(self):
        meta = {"name": "validate", "description": "Run a validation procedure"}
        self.assertEqual(self.validate("skills/validate/SKILL.md", meta), [])
        meta["applies_to"] = {"tool": False}
        self.assertTrue(self.validate("skills/validate/SKILL.md", meta))

    def test_early_attempt_without_full_task_hash_remains_readable_without_rewrite(self):
        recall(self.vault, "copilot studio validation", session_id="early-attempt")
        path = next(self.vault.path("episodes/_recalls").glob("*.md"))
        note = load_note(path, self.vault)
        note.meta.pop("task_fingerprint")
        path.write_bytes(compose(note.meta, note.body).encode("utf-8"))
        before = path.read_bytes()
        issues = validate_note(load_note(path, self.vault), self.vault)
        self.assertEqual([item for item in issues if item.severity == "error"], [])
        attempt = read_attempts(self.vault, session_id="early-attempt")[0]
        self.assertIsNone(attempt.task_fingerprint)
        self.assertEqual(path.read_bytes(), before)
        note.meta["task_fingerprint"] = "not-a-digest"
        path.write_bytes(compose(note.meta, note.body).encode("utf-8"))
        self.assertTrue([
            item for item in validate_note(load_note(path, self.vault), self.vault)
            if item.severity == "error"
        ])


if __name__ == "__main__":
    unittest.main()
