import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import config, redact


class RedactionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.rules = self.vault.path(config.REDACT_FILE)
        self.rules.write_text("literal:SnapshotNeedle\n", encoding="utf-8")

    def test_one_operation_reads_custom_rules_once_without_skipping_redaction(self):
        original = Path.read_text
        reads = []

        def counted(path, *args, **kwargs):
            if path == self.rules:
                reads.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", counted):
            with redact.redaction_snapshot(self.vault):
                for _ in range(20):
                    clean, findings = redact.redact("SnapshotNeedle", self.vault)
                    self.assertEqual(clean, "[customer]")
                    self.assertTrue(findings)
            self.assertEqual(len(reads), 1)
            redact.redact("SnapshotNeedle", self.vault)
            self.assertEqual(len(reads), 2)

    def test_rules_are_refreshed_between_operations(self):
        with redact.redaction_snapshot(self.vault):
            self.rules.write_text("literal:NextNeedle\n", encoding="utf-8")
            self.assertEqual(redact.redact("SnapshotNeedle", self.vault)[0], "[customer]")
        with redact.redaction_snapshot(self.vault):
            self.assertEqual(redact.redact("NextNeedle", self.vault)[0], "[customer]")
            self.assertEqual(redact.redact("SnapshotNeedle", self.vault)[0], "SnapshotNeedle")

    def test_nested_vaults_never_share_rule_snapshots(self):
        other, holder = make_vault()
        self.addCleanup(holder.cleanup)
        other.path(config.REDACT_FILE).write_text("literal:OtherNeedle\n", encoding="utf-8")
        with redact.redaction_snapshot(self.vault):
            with redact.redaction_snapshot(other):
                self.assertEqual(redact.redact("OtherNeedle", other)[0], "[customer]")
                self.assertEqual(redact.redact("SnapshotNeedle", other)[0], "SnapshotNeedle")
            self.assertEqual(redact.redact("SnapshotNeedle", self.vault)[0], "[customer]")


if __name__ == "__main__":
    unittest.main()
