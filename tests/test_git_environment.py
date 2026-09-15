import os
import subprocess
import unittest
from unittest.mock import patch

from helpers import init_git, make_vault


class GitFixtureEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def test_git_fixture_passes_empty_environment_values_explicitly(self):
        with patch.dict(os.environ, {"MEMORY_MESH_TEST_EMPTY": ""}):
            result = subprocess.CompletedProcess([], 0, "", "")
            with patch("helpers.subprocess.run", return_value=result) as run:
                self.assertTrue(init_git(self.vault))
            for call in run.call_args_list:
                self.assertEqual(call.kwargs["env"]["MEMORY_MESH_TEST_EMPTY"], "")
                self.assertIsNot(call.kwargs["env"], os.environ)

    def test_git_errors_are_not_misreported_as_missing_git(self):
        result = subprocess.CompletedProcess([], 128, "", "fixture configuration error")
        with patch("helpers.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Git fixture init failed.*configuration error"):
                init_git(self.vault)

    def test_an_actually_missing_git_executable_retains_legacy_skip_signal(self):
        with patch("helpers.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(init_git(self.vault))


if __name__ == "__main__":
    unittest.main()
