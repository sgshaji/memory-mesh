import json
import unittest
from datetime import datetime, timezone

from helpers import make_vault

from memory_mesh import capture, cli, config
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

    def test_structured_learning_is_validated_classified_and_written(self):
        res = capture.learn_structured(self.vault, {
            "title": "Validate Copilot Studio grounding before publishing",
            "observations": [
                {"kind": "scenario", "text": "A Copilot Studio agent uses document grounding."},
                {"kind": "procedure", "text": "Validate every grounding source before publishing."},
                {"kind": "outcome", "text": "The validation rejected an unavailable source in the test run."},
            ],
            "trust": "first-party",
        }, source_tool="github-copilot", now=datetime(2026, 9, 2, tzinfo=timezone.utc))

        meta, body = fm_parse(res.path.read_text(encoding="utf-8"))
        self.assertEqual(meta["domains"], ["copilot-studio"])
        self.assertEqual(meta["source"], "automatic capture via github-copilot, 2026-09-02")
        self.assertIn("- [scenario]", body)
        self.assertIn("- [procedure]", body)
        self.assertIn("- [outcome]", body)

    def test_structured_learning_requires_action_and_verification(self):
        with self.assertRaisesRegex(ValueError, "actionable"):
            capture.learn_structured(self.vault, {
                "title": "An unsupported observation",
                "observations": [
                    {"kind": "scenario", "text": "A scenario occurred."},
                    {"kind": "outcome", "text": "Something was observed."},
                ],
            })
        with self.assertRaisesRegex(ValueError, "outcome or reproducible evidence"):
            capture.learn_structured(self.vault, {
                "title": "An unverified procedure",
                "observations": [
                    {"kind": "scenario", "text": "A scenario occurred."},
                    {"kind": "procedure", "text": "Try this procedure."},
                ],
            })

    def test_structured_learning_redacts_every_field_before_writing(self):
        res = capture.learn_structured(self.vault, {
            "title": "Contoso grounding workaround",
            "project": "Contoso rollout",
            "observations": [
                {"kind": "workaround", "text": "Use api_key = sk-abcdef1234567890abcdef."},
                {"kind": "evidence", "text": "Contoso verified the result."},
            ],
        })
        text = res.path.read_text(encoding="utf-8")
        self.assertNotIn("Contoso", text)
        self.assertNotIn("sk-abcdef1234567890abcdef", text)
        self.assertIn("[customer]", text)
        self.assertIn("[redacted-secret]", text)
        self.assertTrue(res.redacted)

    def test_structured_learning_rejects_multiline_fields(self):
        base = {
            "title": "Single line",
            "observations": [
                {"kind": "procedure", "text": "Perform the validated procedure."},
                {"kind": "evidence", "text": "The test passed."},
            ],
        }
        for field, value in (
            ("title", "line one\nline two"),
            ("project", "line one\nline two"),
        ):
            data = {**base, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "single line"):
                capture.learn_structured(self.vault, data)
        data = {
            **base,
            "observations": [
                {"kind": "procedure", "text": "line one\nline two"},
                {"kind": "evidence", "text": "The test passed."},
            ],
        }
        with self.assertRaisesRegex(ValueError, "single line"):
            capture.learn_structured(self.vault, data)

    def test_plain_learning_keeps_legacy_content_hash(self):
        first = capture.learn(self.vault, "the same exact insight", source_tool="x")
        meta, _ = fm_parse(first.path.read_text(encoding="utf-8"))
        self.assertEqual(meta["content_hash"], capture._content_hash("the same exact insight"))

    def test_structured_cli_applies_metadata_flags(self):
        payload = json.dumps({
            "title": "A reusable capture procedure",
            "observations": [
                {"kind": "procedure", "text": "Run the reusable procedure."},
                {"kind": "evidence", "text": "The command completed successfully."},
            ],
        })
        rc = cli.main([
            "--root", str(self.vault.root),
            "learn", payload,
            "--structured",
            "--tool", "github-copilot",
            "--domain", "coding-agents",
            "--project", "memory-mesh",
            "--trust", "third-party",
        ])
        self.assertEqual(rc, 0)
        note = next(self.vault.path(config.INBOX).glob("*reusable-capture-procedure.md"))
        meta, _ = fm_parse(note.read_text(encoding="utf-8"))
        self.assertEqual(meta["domains"], ["coding-agents"])
        self.assertEqual(meta["project"], "memory-mesh")
        self.assertEqual(meta["trust"], "third-party")


if __name__ == "__main__":
    unittest.main()
