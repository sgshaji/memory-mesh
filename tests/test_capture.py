import unittest

from helpers import make_vault

from memory_mesh import capture, config
from memory_mesh.frontmatter import parse as fm_parse


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_candidate_creation_single_call(self):
        res = capture.learn(self.vault, "grounding sources must be validated before publishing", source_tool="claude-code")
        self.assertTrue(res.created)
        self.assertTrue(res.path.exists())
        rel = self.vault.rel(res.path)
        self.assertTrue(rel.startswith(config.INBOX + "/"))
        meta, body = fm_parse(res.path.read_text(encoding="utf-8"))
        self.assertEqual(meta["type"], "candidate")
        self.assertEqual(meta["trust"], "first-party")
        self.assertEqual(meta["sensitivity"], "checked")
        self.assertIn("source", meta)
        self.assertIn("captured", meta)
        self.assertIn("- [observation]", body)
        self.assertNotIn("status", meta)  # candidates carry no self-assigned status

    def test_safe_filename(self):
        res = capture.learn(self.vault, 'CON: weird/../"name"<>|?*  \\ trailing   ', source_tool="x")
        name = res.path.name
        self.assertNotIn("..", name)
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, name)

    def test_redaction_before_persistence(self):
        secret = "api_key = sk-abcdef1234567890abcdef"
        res = capture.learn(self.vault, f"the fix needs {secret} to work", source_tool="x")
        text = res.path.read_text(encoding="utf-8")
        self.assertNotIn("sk-abcdef1234567890abcdef", text)
        self.assertIn("[redacted-secret]", text)
        meta, _ = fm_parse(text)
        self.assertEqual(meta["sensitivity"], "redacted")
        self.assertTrue(res.redacted)

    def test_user_redact_rules_applied(self):
        res = capture.learn(self.vault, "Contoso reported the tenant issue", source_tool="x")
        text = res.path.read_text(encoding="utf-8")
        self.assertNotIn("Contoso", text)
        self.assertIn("[customer]", text)

    def test_duplicate_capture_idempotent(self):
        r1 = capture.learn(self.vault, "the same exact insight", source_tool="x")
        r2 = capture.learn(self.vault, "  The same   EXACT insight ", source_tool="y")
        self.assertTrue(r1.created)
        self.assertFalse(r2.created)
        self.assertEqual(r1.path, r2.path)

    def test_never_writes_canonical(self):
        before = sorted(p.as_posix() for p in self.vault.path("knowledge").rglob("*.md"))
        capture.learn(self.vault, "some new insight about copilot studio topics", source_tool="x")
        after = sorted(p.as_posix() for p in self.vault.path("knowledge").rglob("*.md"))
        self.assertEqual(before, after)

    def test_empty_capture_rejected(self):
        with self.assertRaises(ValueError):
            capture.learn(self.vault, "   ")


if __name__ == "__main__":
    unittest.main()
