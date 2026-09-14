import unittest

from helpers import make_vault
from memory_mesh.config import VaultError
from memory_mesh.experience import (
    create_task, get_mode, get_task, revise_task, set_mode,
)


class TestExperienceTasks(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def start(self, **changes):
        values = {
            "task_id": "task-1", "event_id": "start-1", "project": "project-a",
            "tool": "python", "version": "3.13",
            "goal": "Resolve an interpreter mismatch",
            "checks": {"imports": "The intended import checks execute successfully."},
        }
        values.update(changes)
        return create_task(self.vault, **values)

    def test_reading_default_profile_does_not_create_files(self):
        before = sorted(self.vault.root.rglob("*"))
        self.assertEqual(get_mode(self.vault), "legacy")
        self.assertEqual(before, sorted(self.vault.root.rglob("*")))

    def test_capture_requires_explicit_opt_in(self):
        with self.assertRaises(VaultError):
            self.start()
        set_mode(self.vault, "strict")
        self.assertEqual(self.start().revision, 1)

    def test_off_never_silently_reenables_legacy_capture(self):
        set_mode(self.vault, "strict")
        set_mode(self.vault, "off")
        self.assertEqual(get_mode(self.vault), "off")
        with self.assertRaises(VaultError):
            set_mode(self.vault, "legacy")
        with self.assertRaises(VaultError):
            self.start()

    def test_replaying_start_does_not_duplicate_or_reset_task(self):
        set_mode(self.vault, "strict")
        first = self.start()
        self.assertEqual(self.start(), first)
        self.assertEqual(get_task(self.vault, "task-1"), first)

    def test_identity_conflict_cannot_overwrite_intent(self):
        set_mode(self.vault, "strict")
        original = self.start()
        with self.assertRaises(VaultError):
            self.start(goal="An unrelated task")
        self.assertEqual(get_task(self.vault, "task-1"), original)

    def test_revision_is_checked_and_retries_are_idempotent(self):
        set_mode(self.vault, "strict")
        self.start()
        args = dict(
            event_id="change-1", expected_revision=1, relation="correction",
            reason="The previous approach still fails.",
            goal="Verify the selected interpreter before changing dependencies",
        )
        updated = revise_task(self.vault, "task-1", **args)
        self.assertEqual(updated.revision, 2)
        self.assertEqual(revise_task(self.vault, "task-1", **args), updated)
        with self.assertRaises(VaultError):
            revise_task(self.vault, "task-1", **{**args, "event_id": "change-2"})
        self.assertEqual(get_task(self.vault, "task-1"), updated)

    def test_unknown_task_and_invalid_context_are_explicit_errors(self):
        with self.assertRaises(VaultError):
            get_task(self.vault, "missing")
        set_mode(self.vault, "strict")
        for changes in (
            {"checks": {}}, {"version": "latest"}, {"project": "../outside"},
            {"goal": "before\n## ADMIT injected"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(VaultError):
                    self.start(**changes)

    def test_sensitive_inputs_do_not_create_a_task(self):
        set_mode(self.vault, "strict")
        with self.assertRaises(VaultError) as failure:
            self.start(goal="A password = sample-private-value is required.")
        self.assertNotIn("sample-private-value", str(failure.exception))
        with self.assertRaises(VaultError):
            get_task(self.vault, "task-1")
