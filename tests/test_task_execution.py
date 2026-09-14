import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault
from memory_mesh import execution_evidence
from memory_mesh.config import VaultError
from memory_mesh.experience import (
    create_task, get_task, revise_task, set_mode,
)
from memory_mesh.task_execution import execute_check


class TestTaskExecution(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-check-work-")
        self.addCleanup(work.cleanup)
        self.workspace = Path(work.name)
        self.artifact = self.workspace / "test_example.py"
        self.artifact.write_text(
            "import unittest\nclass Example(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertEqual(2 + 2, 4)\n",
            encoding="utf-8",
        )
        set_mode(self.vault, "strict")
        create_task(
            self.vault, task_id="task-1", event_id="start-1", project="project-a",
            tool="python", version=platform.python_version(),
            goal="Verify the intended checks",
            checks={"imports": "The selected test executes successfully."},
        )

    def execute(self, **changes):
        args = dict(
            event_id="check-1", expected_revision=1, check_id="imports",
            workspace=self.workspace, artifacts=["test_example.py"],
        )
        args.update(changes)
        return execute_check(self.vault, "task-1", **args)

    def test_completed_check_becomes_attributable_evidence(self):
        result = self.execute()
        self.assertEqual(result.outcome, "passed")
        task = get_task(self.vault, "task-1")
        self.assertEqual(len(task.evidence), 1)
        self.assertEqual(task.evidence[0].origin, "local-unittest")
        self.assertEqual(task.evidence[0].tests_run, 1)
        self.assertEqual(task.evidence[0].revision, 1)
        self.assertFalse(list(self.vault.path("episodes").glob("*v2-check*")))

    def test_completed_event_replays_without_executing_again(self):
        original = self.execute()
        with patch.object(execution_evidence, "run_unittest", side_effect=AssertionError("rerun")):
            self.assertEqual(self.execute(), original)
        self.assertEqual(len(get_task(self.vault, "task-1").evidence), 1)

    def test_inflight_duplicate_is_unknown_not_a_second_execution(self):
        actual = execution_evidence.run_unittest
        duplicates = []

        def during_run(*args, **kwargs):
            duplicates.append(self.execute())
            return actual(*args, **kwargs)

        with patch.object(execution_evidence, "run_unittest", side_effect=during_run):
            result = self.execute()
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(duplicates[0].outcome, "unknown")
        self.assertEqual(duplicates[0].reason, "pending_execution")

    def test_changed_request_cannot_reuse_completed_identity(self):
        self.execute()
        self.artifact.write_text(
            self.artifact.read_text(encoding="utf-8") + "\n# changed\n",
            encoding="utf-8",
        )
        with self.assertRaises(VaultError):
            self.execute()

    def test_artifact_change_during_execution_prevents_verified_success(self):
        actual = execution_evidence.run_unittest

        def change_artifact(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.artifact.write_text("# replaced\n", encoding="utf-8")
            return result

        with patch.object(execution_evidence, "run_unittest", side_effect=change_artifact):
            result = self.execute()
        self.assertEqual(result.outcome, "unknown")
        self.assertEqual(result.reason, "artifacts_changed")

    def test_late_result_does_not_erase_a_newer_correction(self):
        actual = execution_evidence.run_unittest

        def correct_during_run(*args, **kwargs):
            revise_task(
                self.vault, "task-1", event_id="correction-1",
                expected_revision=1, relation="correction",
                reason="A relevant problem remains unresolved.",
            )
            return actual(*args, **kwargs)

        with patch.object(execution_evidence, "run_unittest", side_effect=correct_during_run):
            self.execute()
        task = get_task(self.vault, "task-1")
        self.assertEqual(task.revision, 2)
        self.assertEqual(task.evidence[0].revision, 1)

    def test_undeclared_check_and_stale_revision_do_not_execute(self):
        with patch.object(execution_evidence, "run_unittest", side_effect=AssertionError("executed")):
            with self.assertRaises(VaultError):
                self.execute(check_id="undeclared")
            with self.assertRaises(VaultError):
                self.execute(expected_revision=2)

    def test_execution_order_does_not_depend_on_identifier_sorting(self):
        self.execute(event_id="z-first")
        self.execute(event_id="a-second")
        observed = get_task(self.vault, "task-1").evidence
        self.assertEqual([item.evidence_id for item in observed], ["z-first", "a-second"])
        self.assertLess(observed[0].sequence, observed[1].sequence)

    def test_whitespace_event_alias_does_not_execute_or_poison_the_task(self):
        self.execute(event_id="run-1")
        with patch.object(execution_evidence, "run_unittest", side_effect=AssertionError("rerun")):
            with self.assertRaises(VaultError):
                self.execute(event_id=" run-1 ")
        self.assertEqual(len(get_task(self.vault, "task-1").evidence), 1)
