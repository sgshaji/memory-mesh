import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from helpers import make_vault
from memory_mesh import cli


def evaluation_row():
    return {
        "case_id": "case-1", "family": "imports", "trial_id": "trial-1",
        "arm": "v2", "accepted": True, "active_ms": 100,
        "model_cost": None, "memory_cost": None, "review_seconds": None,
        "currency": None, "cost_source": None,
    }


class TestV2CLI(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def command(self, args, text=""):
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(text)), redirect_stdout(output), redirect_stderr(output):
            rc = cli.main(["--root", str(self.vault.root), "v2", *args])
        return rc, output.getvalue()

    def test_evaluation_reads_stdin_without_writing_memory(self):
        before = sorted(self.vault.root.rglob("*"))
        rc, text = self.command(["evaluate"], json.dumps([evaluation_row()]))
        report = json.loads(text)
        self.assertEqual(rc, 0)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["design"], "observational")
        self.assertFalse(report["causal_claims_supported"])
        self.assertEqual(report["arms"]["v2"]["run_count"], 1)
        self.assertEqual(before, sorted(self.vault.root.rglob("*")))

    def test_evaluation_accepts_an_explicit_file(self):
        path = self.vault.root / "measurements.json"
        path.write_text(json.dumps([evaluation_row()]), encoding="utf-8")
        rc, text = self.command(["evaluate", str(path)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(text)["arms"]["v2"]["run_count"], 1)

    def test_invalid_input_has_safe_explicit_errors(self):
        for text in ('{"secret-data":', '{"a":1,"a":2}', "x" * 1_048_577):
            with self.subTest(length=len(text)):
                rc, output = self.command(["evaluate"], text)
                self.assertEqual(rc, 1)
                self.assertIn("error:", output)
                self.assertNotIn("secret-data", output)

    def test_measurement_validation_is_not_a_success_shaped_fallback(self):
        row = evaluation_row()
        row["accepted"] = "PRIVATE_INPUT_VALUE"
        rc, output = self.command(["evaluate"], json.dumps([row]))
        self.assertEqual(rc, 1)
        self.assertNotIn("PRIVATE_INPUT_VALUE", output)
