import json
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import capture, cli, config, frontmatter
from memory_mesh.experience import set_mode
from memory_mesh.frontmatter import parse as fm_parse
from memory_mesh.notes import load_note
from memory_mesh.schema import validate_note


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

    def test_signal_and_episode_link_are_optional_capture_metadata(self):
        result = capture.learn(
            self.vault, "A linked observation", signal="high",
            source_episode="episodes/linked-session.md",
        )
        note = load_note(result.path, self.vault)
        self.assertEqual(note.meta["signal"], "high")
        self.assertEqual(note.meta["source_episode"], "episodes/linked-session")
        self.assertEqual(note.meta["content_hash"], capture._content_hash("A linked observation"))
        self.assertFalse(result.updated)
        self.assertEqual(result.warnings, [])
        self.assertEqual(
            [issue.message for issue in validate_note(note, self.vault) if issue.severity == "error"], [],
        )
        for field in ("status", "confidence", "feedback", "last_verified"):
            self.assertNotIn(field, note.meta)

    def test_default_capture_retains_legacy_optional_field_omissions(self):
        result = capture.learn(self.vault, "Legacy metadata remains small")
        meta, _ = fm_parse(result.path.read_text(encoding="utf-8"))
        self.assertNotIn("signal", meta)
        self.assertNotIn("source_episode", meta)

    def test_structured_capture_metadata_does_not_change_identity(self):
        data = {
            "title": "A verified procedure",
            "observations": [
                {"kind": "procedure", "text": "Run deterministic checks."},
                {"kind": "evidence", "text": "The focused tests passed."},
            ],
        }
        first = capture.learn_structured(self.vault, data)
        before, body = fm_parse(first.path.read_text(encoding="utf-8"))
        duplicate = capture.learn_structured(
            self.vault, data, signal="high", source_episode="episodes/structured-session",
        )
        after, updated_body = fm_parse(duplicate.path.read_text(encoding="utf-8"))
        self.assertFalse(duplicate.created)
        self.assertTrue(duplicate.updated)
        self.assertEqual(first.path, duplicate.path)
        self.assertEqual(after["content_hash"], before["content_hash"])
        self.assertEqual(updated_body, body)
        self.assertEqual(after["signal"], "high")
        self.assertEqual(after["source_episode"], "episodes/structured-session")

    def test_high_duplicate_upgrades_attention_without_changing_claim(self):
        first = capture.learn(
            self.vault, "Keep this claim stable", signal="low",
            trust="third-party", now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        before, body = fm_parse(first.path.read_text(encoding="utf-8"))
        duplicate = capture.learn(
            self.vault, "KEEP this claim stable", signal="high",
            trust="first-party", now=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
        after, updated_body = fm_parse(duplicate.path.read_text(encoding="utf-8"))
        self.assertEqual(duplicate.path, first.path)
        self.assertFalse(duplicate.created)
        self.assertTrue(duplicate.updated)
        self.assertEqual(after, {**before, "signal": "high"})
        self.assertEqual(updated_body, body)

    def test_default_duplicate_never_overrides_low_and_replayed_high_is_noop(self):
        first = capture.learn(self.vault, "An intentionally low priority", signal="low")
        before = first.path.read_bytes()
        normal = capture.learn(self.vault, "An intentionally low priority")
        self.assertFalse(normal.updated)
        self.assertEqual(first.path.read_bytes(), before)
        capture.learn(self.vault, "An intentionally low priority", signal="high")
        elevated = first.path.read_bytes()
        with patch.object(capture.fsutil, "agent_write", wraps=capture.fsutil.agent_write) as write:
            for signal in ("normal", "low", "high"):
                duplicate = capture.learn(self.vault, "An intentionally low priority", signal=signal)
                self.assertFalse(duplicate.updated)
        write.assert_not_called()
        self.assertEqual(first.path.read_bytes(), elevated)

    def test_duplicate_keeps_original_source_episode_and_reports_conflict(self):
        first = capture.learn(self.vault, "A repeated observation", source_episode="episodes/first")
        duplicate = capture.learn(
            self.vault, "A repeated observation", signal="high", source_episode="episodes/second",
        )
        meta, _ = fm_parse(first.path.read_text(encoding="utf-8"))
        self.assertEqual(meta["source_episode"], "episodes/first")
        self.assertEqual(meta["signal"], "high")
        self.assertTrue(duplicate.updated)
        self.assertTrue(any("Candidate learnings" in warning for warning in duplicate.warnings))

    def test_high_duplicate_diagnoses_malformed_existing_signal_without_repairing_it(self):
        first = capture.learn(self.vault, "Malformed attention metadata")
        meta, body = fm_parse(first.path.read_text(encoding="utf-8"))
        meta["signal"] = ["high"]
        first.path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        before = first.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "signal"):
            capture.learn(self.vault, "Malformed attention metadata", signal="high")
        self.assertEqual(first.path.read_bytes(), before)

    def test_processed_duplicate_is_not_upgraded(self):
        first = capture.learn(self.vault, "Already reviewed")
        meta, body = fm_parse(first.path.read_text(encoding="utf-8"))
        meta["processed"] = "2026-09-10"
        first.path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        before = first.path.read_bytes()
        next_capture = capture.learn(self.vault, "Already reviewed", signal="high")
        self.assertTrue(next_capture.created)
        self.assertNotEqual(first.path, next_capture.path)
        self.assertEqual(first.path.read_bytes(), before)

    def test_duplicate_changed_after_lookup_is_not_overwritten(self):
        first = capture.learn(self.vault, "A concurrently reviewed candidate")
        meta, body = fm_parse(first.path.read_text(encoding="utf-8"))
        for changed in ({**meta, "processed": "2026-09-14"}, {**meta, "type": "gap"}, {}):
            first.path.write_text(frontmatter.compose(changed, body), encoding="utf-8")
            before = first.path.read_bytes()
            with self.subTest(changed=changed), patch.object(capture, "_existing_candidate", return_value=first.path):
                with self.assertRaises(config.VaultError):
                    capture.learn(self.vault, "A concurrently reviewed candidate", signal="high")
            self.assertEqual(first.path.read_bytes(), before)

    def test_duplicate_upgrade_still_enforces_agent_write_boundary(self):
        first = capture.learn(self.vault, "Boundary-protected metadata")
        canonical = self.vault.path("knowledge/patterns/candidate-shaped-note.md")
        canonical.write_bytes(first.path.read_bytes())
        before = canonical.read_bytes()
        with patch.object(capture, "_existing_candidate", return_value=canonical):
            with self.assertRaises(capture.fsutil.WriteBoundaryError):
                capture.learn(self.vault, "Boundary-protected metadata", signal="high")
        self.assertEqual(canonical.read_bytes(), before)

    def test_gap_hash_does_not_deduplicate_a_factual_observation(self):
        first = capture.learn(self.vault, "The same words describe a need")
        meta, _ = fm_parse(first.path.read_text(encoding="utf-8"))
        meta.update(type="gap", need="The same words describe a need")
        first.path.write_text(frontmatter.compose(meta, ""), encoding="utf-8")
        second = capture.learn(self.vault, "The same words describe a need", signal="high")
        self.assertTrue(second.created)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(load_note(first.path, self.vault).type, "gap")

    def test_signal_validation_is_explicit_and_writes_nothing(self):
        before = sorted(self.vault.path(config.INBOX).glob("*.md"))
        invalid_signals: tuple[Any, ...] = ("urgent", "", "HIGH", None, ["high"], True)
        for signal in invalid_signals:
            with self.subTest(signal=signal), self.assertRaisesRegex(ValueError, "signal"):
                capture.learn(self.vault, "Invalid signal", signal=signal)
        self.assertEqual(before, sorted(self.vault.path(config.INBOX).glob("*.md")))

    def test_episode_link_redaction_precedes_new_and_duplicate_writes(self):
        for duplicate in (False, True):
            observation = f"Redact episode metadata {duplicate}"
            if duplicate:
                capture.learn(self.vault, observation)
            result = capture.learn(
                self.vault, observation, source_episode="episodes/Contoso-investigation",
            )
            text = result.path.read_text(encoding="utf-8")
            meta, _ = fm_parse(text)
            self.assertNotIn("Contoso", text)
            self.assertIn("[customer]", meta["source_episode"])
            self.assertEqual(meta["sensitivity"], "redacted")
            self.assertTrue(result.redacted)

    def test_episode_link_validation_rejects_nonlocal_or_malformed_references(self):
        invalid_references: tuple[Any, ...] = (
            "", "   ", 42, ["episodes/a"], "../escape", "episodes/../escape",
            "knowledge/patterns/not-an-episode", "/episodes/absolute",
            "C:\\private\\episode.md", "https://example.com/episode",
            "episodes/a\nsignal: high", "episodes/a\x00", "episodes/a\u2028b",
            "episodes/a\u0085b",
        )
        for source_episode in invalid_references:
            with self.subTest(source_episode=source_episode), self.assertRaisesRegex(ValueError, "source_episode"):
                capture.learn(self.vault, "Invalid linkage", source_episode=source_episode)

    def test_episode_link_accepts_windows_paths_and_legacy_bare_slugs(self):
        for reference in ("episodes\\local.md", "local", "[[episodes/local.md|Session]]"):
            with self.subTest(reference=reference):
                result = capture.learn(self.vault, f"Reference spelling {reference}", source_episode=reference)
                meta, _ = fm_parse(result.path.read_text(encoding="utf-8"))
                self.assertEqual(meta["source_episode"], "episodes/local")

    def test_attention_metadata_cannot_bypass_v2_capture_boundaries(self):
        data = {
            "title": "Unreviewed procedure",
            "observations": [
                {"kind": "procedure", "text": "Try a procedure."},
                {"kind": "outcome", "text": "An agent reports success."},
            ],
        }
        for mode in ("strict", "shadow", "off"):
            set_mode(self.vault, mode)
            with self.subTest(mode=mode):
                with self.assertRaises(config.VaultError):
                    capture.learn(self.vault, "Unreviewed", signal="high", source_episode="episodes/source")
                with self.assertRaises(config.VaultError):
                    capture.learn_structured(self.vault, data, signal="high", source_episode="episodes/source")

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
