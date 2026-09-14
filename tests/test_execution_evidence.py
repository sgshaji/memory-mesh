import json
import os
import platform
import py_compile
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from helpers import directory_link

from memory_mesh.config import VaultError
from memory_mesh.execution_evidence import fingerprint, run_unittest


class TestExecutionEvidence(unittest.TestCase):
    def setUp(self):
        self.holder = tempfile.TemporaryDirectory(prefix="mm-execution-")
        self.addCleanup(self.holder.cleanup)
        self.root = Path(self.holder.name)

    def suite(self, body):
        path = self.root / "test_example.py"
        path.write_text(
            "import unittest\n\nclass Example(unittest.TestCase):\n" + body,
            encoding="utf-8",
        )
        return path

    def test_real_pass_has_counts_and_runtime_but_no_test_output(self):
        self.suite(
            "    def test_ok(self):\n"
            "        print('DO_NOT_PERSIST_TEST_OUTPUT')\n"
            "        self.assertEqual(2 + 2, 4)\n"
        )
        result = run_unittest(self.root)
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(result.tests_run, 1)
        self.assertEqual(result.tests_skipped, 0)
        self.assertNotIn("DO_NOT_PERSIST", json.dumps(asdict(result)))
        self.assertTrue(result.tool_version.startswith("3."))

    def test_real_failure_is_not_rewritten_as_success(self):
        self.suite("    def test_failure(self):\n        self.fail('private output')\n")
        result = run_unittest(self.root)
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.failures, 1)
        self.assertNotIn("private output", json.dumps(asdict(result)))

    def test_no_tests_and_all_skipped_remain_unverified(self):
        self.assertEqual(run_unittest(self.root).outcome, "unknown")
        self.suite(
            "    @unittest.skip('not exercised')\n"
            "    def test_skip(self):\n        pass\n"
        )
        result = run_unittest(self.root)
        self.assertEqual(result.outcome, "unknown")
        self.assertEqual(result.tests_skipped, 1)

    def test_expected_failure_alone_is_not_a_verified_fix(self):
        self.suite(
            "    @unittest.expectedFailure\n"
            "    def test_expected_failure(self):\n        self.fail()\n"
        )
        result = run_unittest(self.root)
        self.assertEqual(result.outcome, "unknown")
        self.assertEqual(result.expected_failures, 1)

    def test_timeout_is_explicitly_unknown(self):
        self.suite("    def test_slow(self):\n        import time\n        time.sleep(2)\n")
        result = run_unittest(self.root, timeout=0.05)
        self.assertEqual(result.outcome, "unknown")
        self.assertEqual(result.reason, "timeout")

    def test_current_artifacts_are_hashed_without_returning_contents(self):
        path = self.suite("    def test_ok(self):\n        self.assertTrue(True)\n")
        original = fingerprint(self.root, ["test_example.py"])
        self.assertEqual(len(original), 64)
        self.assertEqual(original, fingerprint(self.root, ["test_example.py"]))
        path.write_text(path.read_text(encoding="utf-8") + "\n# change\n", encoding="utf-8")
        self.assertNotEqual(original, fingerprint(self.root, ["test_example.py"]))

    def test_artifact_and_discovery_paths_cannot_escape_workspace(self):
        for paths in ([], ["../outside.py"], [str(self.root.parent / "outside.py")]):
            with self.subTest(paths=paths):
                with self.assertRaises(VaultError):
                    fingerprint(self.root, paths)
        with self.assertRaises(VaultError):
            run_unittest(self.root, start="../")
        with self.assertRaises(VaultError):
            run_unittest(self.root, pattern="../test_*.py")

    def test_nonfinite_timeout_is_rejected(self):
        with self.assertRaises(VaultError):
            run_unittest(self.root, timeout=float("nan"))

    def test_class_setup_skip_does_not_erase_an_observed_failure(self):
        self.suite(
            "    def test_failure(self):\n        self.fail()\n\n"
            "class Skipped(unittest.TestCase):\n"
            "    @classmethod\n    def setUpClass(cls):\n        raise unittest.SkipTest('skip')\n"
            "    def test_unreached(self):\n        pass\n"
        )
        result = run_unittest(self.root)
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.failures, 1)

    def test_subtest_skip_does_not_erase_an_observed_failure(self):
        self.suite(
            "    def test_partial(self):\n"
            "        with self.subTest():\n            self.skipTest('skip')\n"
            "        self.fail()\n"
        )
        self.assertEqual(run_unittest(self.root).outcome, "failed")

    def test_equal_size_source_edit_cannot_reuse_stale_bytecode(self):
        path = self.suite("    def test_ok(self):\n        self.assertEqual(1, 1)\n")
        py_compile.compile(str(path), doraise=True)
        before = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace("(1, 1)", "(1, 2)"), encoding="utf-8")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(run_unittest(self.root).outcome, "failed")

    def test_recursive_discovery_cannot_import_an_outside_package(self):
        with tempfile.TemporaryDirectory(prefix="mm-outside-tests-") as outside:
            package = Path(outside)
            marker = package / "imported.txt"
            (package / "__init__.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            (package / "test_outside.py").write_text(
                "import unittest\nclass Outside(unittest.TestCase):\n"
                "    def test_outside(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            directory_link(self.root / "linked_package", package)
            result = run_unittest(self.root)
            self.assertEqual(result.outcome, "unknown")
            self.assertFalse(marker.exists())

    def test_inconsistent_worker_metadata_is_unverified_not_persistable(self):
        base = {
            "protocol": 1, "tests_run": 1, "tests_skipped": 0,
            "expected_failures": 0, "failures": 0, "errors": 0,
            "successful": True, "tool_version": platform.python_version(),
            "checks_executed": 1, "boundary_violation": False,
        }
        for changes in ({"failures": 1}, {"tool_version": ""}, {"protocol": True}):
            with self.subTest(changes=changes):
                response = subprocess.CompletedProcess(
                    [], 0, json.dumps({**base, **changes}).encode("utf-8"), b"",
                )
                with patch("memory_mesh.execution_evidence.subprocess.run", return_value=response):
                    result = run_unittest(self.root)
                self.assertEqual(result.outcome, "unknown")
                self.assertEqual(result.reason, "invalid_runner_result")
