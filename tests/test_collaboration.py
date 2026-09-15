import os
import unittest
from unittest import mock

from helpers import init_git, make_vault
from memory_mesh import collaboration, fsutil, gitutil
from memory_mesh.experience_store import ExperienceBusy, exclusive_lock


class TestCollaboration(unittest.TestCase):
    def setUp(self):
        self.vault, self.holder = make_vault()
        self.saved_actor = os.environ.pop(collaboration.ACTOR_ENV, None)

    def tearDown(self):
        if self.saved_actor is None:
            os.environ.pop(collaboration.ACTOR_ENV, None)
        else:
            os.environ[collaboration.ACTOR_ENV] = self.saved_actor
        self.holder.cleanup()

    def policy(self, curator="curator@example.test"):
        self.vault.path("_meta/config.md").write_text(
            "---\ntype: meta\nversion: 1\ncuration:\n  mode: designated\n"
            f"  curator: {curator}\n  lock_timeout_seconds: 0.1\n---\n", encoding="utf-8"
        )

    def test_single_user_works_without_configuration_or_git(self):
        with mock.patch.object(gitutil, "available", return_value=False):
            self.assertIsNone(collaboration.require_curator(self.vault))
            fsutil.curator_write(self.vault, "knowledge/patterns/single.md", "works")

    def test_designated_actor_can_curate_with_environment_identity(self):
        self.policy()
        os.environ[collaboration.ACTOR_ENV] = "CURATOR@example.test"
        fsutil.curator_write(self.vault, "knowledge/patterns/designated.md", "permitted")
        self.assertTrue(self.vault.exists("knowledge/patterns/designated.md"))

    def test_other_contributor_capture_remains_available(self):
        self.policy()
        os.environ[collaboration.ACTOR_ENV] = "contributor@example.test"
        for path in ("00-inbox/contribution.md", "episodes/episode.md", "episodes/_outcomes/event.md"):
            fsutil.agent_write(self.vault, path, "contributor data")
            self.assertTrue(self.vault.exists(path))
        with self.assertRaises(collaboration.CuratorPermissionError):
            fsutil.curator_write(self.vault, "knowledge/patterns/denied.md", "not permitted")
        self.assertFalse(self.vault.exists("knowledge/patterns/denied.md"))

    def test_missing_designated_identity_fails_explicitly(self):
        self.policy()
        with mock.patch.object(gitutil, "available", return_value=False):
            with self.assertRaisesRegex(collaboration.CuratorPermissionError, "designated"):
                collaboration.require_curator(self.vault)

    def test_identity_is_local_git_email_not_inherited_global(self):
        if not init_git(self.vault):
            self.skipTest("Git unavailable")
        self.policy("test@example.com")
        self.assertEqual(collaboration.current_actor(self.vault), "test@example.com")
        self.assertEqual(collaboration.require_curator(self.vault), "test@example.com")
        gitutil._git(self.vault, "config", "--local", "--unset", "user.email")
        self.assertEqual(collaboration.current_actor(self.vault), "test")

    def test_environment_identity_has_explicit_precedence(self):
        self.policy()
        os.environ[collaboration.ACTOR_ENV] = "curator@example.test"
        with mock.patch.object(gitutil, "available", side_effect=AssertionError("must not read Git")):
            self.assertEqual(collaboration.require_curator(self.vault), "curator@example.test")

    def test_malformed_environment_identity_fails_closed(self):
        self.policy()
        for identity in ("", " \t", "one\ntwo"):
            os.environ[collaboration.ACTOR_ENV] = identity
            with self.assertRaises(collaboration.CuratorPermissionError):
                collaboration.require_curator(self.vault)

    def test_curator_context_uses_same_nonreentrant_os_lock(self):
        self.policy()
        os.environ[collaboration.ACTOR_ENV] = "curator@example.test"
        with exclusive_lock(self.vault, "curator"):
            with self.assertRaises(ExperienceBusy):
                with collaboration.curator_lock(self.vault):
                    self.fail("must not acquire a second curator lock")
            with collaboration.curator_lock(self.vault, existing_lock=True):
                pass
        with collaboration.curator_lock(self.vault):
            pass
