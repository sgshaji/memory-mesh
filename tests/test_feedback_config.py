import tempfile
import unittest
from pathlib import Path

from memory_mesh.config import SETTINGS_FILE, Vault, VaultError
from memory_mesh.feedback_config import load_settings


class FeedbackConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Vault(Path(self.temp.name))
        self.path = self.vault.path(SETTINGS_FILE)
        self.path.parent.mkdir()

    def write(self, text):
        self.path.write_text("---\ntype: meta\n" + text + "\n---\n", encoding="utf-8")

    def test_absent_configuration_is_single_user_and_non_mutating(self):
        settings = load_settings(self.vault)
        self.assertEqual(settings.curation.mode, "single-user")
        self.assertEqual(settings.feedback.half_life_days, 90)
        self.assertFalse(self.path.exists())

    def test_policy_and_routing_vocabulary_are_additive(self):
        self.write("feedback:\n  half_life_days: 120\nrouting:\n  coding-agents:\n    aliases: [coding helper]\ncuration:\n  mode: designated\n  curator: curator-alias")
        settings = load_settings(self.vault)
        self.assertEqual(settings.feedback.half_life_days, 120)
        self.assertEqual(settings.routing["coding-agents"].aliases, ("coding helper",))
        self.assertEqual(settings.curation.curator, "curator-alias")

    def test_invalid_values_are_explicit_errors(self):
        for text in (
            "feedback:\n  half_life_days: 0",
            "feedback:\n  recent_days: true",
            "feedback:\n  unknown_context_weight: 2",
            "feedback:\n  recall_target_minimum: 7",
            "feedback:\n  misspelled: 1",
            "curation:\n  mode: designated",
            "curation:\n  mode: distributed",
            "routing:\n  coding-agents:\n    aliases: single",
            "version: 2",
        ):
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(VaultError):
                    load_settings(self.vault)

    def test_missing_frontmatter_never_silently_disables_curation_policy(self):
        self.path.write_text("curation:\n  mode: designated\n  curator: alias\n", encoding="utf-8")
        with self.assertRaisesRegex(VaultError, "requires YAML frontmatter"):
            load_settings(self.vault)

    def test_huge_number_is_a_validation_error_not_an_overflow(self):
        self.write("feedback:\n  recent_days: " + "9" * 1000)
        with self.assertRaises(VaultError):
            load_settings(self.vault)


if __name__ == "__main__":
    unittest.main()
