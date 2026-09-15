import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import episodes
from memory_mesh.config import VaultError
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note, section


class TestEpisodes(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def _stub(self, **kw):
        defaults = dict(tool="claude-code", slug="test-session", session_ref="cc-1",
                        retrieved=["validation-order"], domains=["copilot-studio"])
        defaults.update(kw)
        return episodes.create_stub(self.vault, **defaults)

    def test_stub_lifecycle_raw(self):
        path = self._stub()
        note = load_note(path, self.vault)
        self.assertEqual(note.status, "raw")
        self.assertEqual(note.meta["sensitivity"], "checked")
        self.assertIn("[[validation-order]]", section(note.body, "Knowledge retrieved"))
        # retrieved is pre-filled; used is NOT (mandate clarification 2)
        self.assertEqual(section(note.body, "Knowledge used").strip(), "")

    def test_finish_requires_content(self):
        path = self._stub()
        with self.assertRaises(episodes.EpisodeError):
            episodes.finish(self.vault, path)

    def _fill(self, path, used_line="- [[validation-order]] — held — worked as documented"):
        note = load_note(path, self.vault)
        body = note.body
        body = body.replace("## Goal\n", "## Goal\nvalidate the schema stage\n")
        body = body.replace("## What happened\n", "## What happened\n- tried A → failed\n- did B → worked\n")
        body = body.replace("## Knowledge used\n", f"## Knowledge used\n{used_line}\n")
        from memory_mesh.frontmatter import compose

        path.write_text(compose(note.meta, body), encoding="utf-8")

    def test_finish_flips_to_summarised(self):
        path = self._stub()
        self._fill(path)
        episodes.finish(self.vault, path)
        note = load_note(path, self.vault)
        self.assertEqual(note.status, "summarised")
        self.assertEqual(note.meta["completeness"], "complete")
        ep = episodes.parse_episode(note)
        self.assertEqual(ep.used[0].ref, "validation-order")
        self.assertEqual(ep.used[0].outcome, "held")

    def test_retrieved_vs_used_distinction(self):
        path = self._stub()
        # using a note that was never retrieved is rejected
        self._fill(path, used_line="- [[never-retrieved-note]] — held — hmm")
        with self.assertRaises(episodes.EpisodeError) as ctx:
            episodes.finish(self.vault, path)
        self.assertIn("not Knowledge retrieved", str(ctx.exception))

    def test_finish_redacts(self):
        path = self._stub()
        self._fill(path)
        note = load_note(path, self.vault)
        from memory_mesh.frontmatter import compose

        body = note.body.replace("- did B → worked", "- did B → worked with password = hunter2secret")
        path.write_text(compose(note.meta, body), encoding="utf-8")
        episodes.finish(self.vault, path)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("hunter2secret", text)
        self.assertIn("[redacted-secret]", text)

    def test_append_only_after_mined(self):
        path = self._stub()
        self._fill(path)
        episodes.finish(self.vault, path)
        episodes.mark_mined(self.vault, path, ["knowledge/patterns/x"])
        note = load_note(path, self.vault)
        self.assertEqual(note.status, "mined")
        self.assertEqual(note.meta["mined"], ["knowledge/patterns/x"])
        with self.assertRaises(episodes.EpisodeError):
            episodes.checkpoint(self.vault, path, "too late")
        with self.assertRaises(episodes.EpisodeError):
            episodes.finish(self.vault, path)
        with self.assertRaises(episodes.EpisodeError):
            episodes.mark_mined(self.vault, path, [])

    def test_redaction_exception_to_append_only(self):
        path = self._stub()
        self._fill(path)
        episodes.finish(self.vault, path)
        episodes.mark_mined(self.vault, path, [])
        note = load_note(path, self.vault)
        from memory_mesh.frontmatter import compose

        path.write_text(compose(note.meta, note.body + "\nleaked api_key = abcdef123456\n"), encoding="utf-8")
        findings = episodes.redact_episode(self.vault, path)
        self.assertTrue(findings)
        self.assertNotIn("abcdef123456", path.read_text(encoding="utf-8"))

    def test_checkpoint_appends_while_raw(self):
        path = self._stub()
        episodes.checkpoint(self.vault, path, "long session checkpoint")
        note = load_note(path, self.vault)
        self.assertIn("checkpoint", section(note.body, "What happened"))

    def test_not_applicable_remains_valid_and_finish_is_idempotent(self):
        path = self._stub()
        self._fill(path, "- [[validation-order]] — not-applicable — not exercised")
        episodes.finish(self.vault, path)
        before = path.read_bytes()
        episodes.finish(self.vault, path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(episodes.parse_episode(load_note(path, self.vault)).used[0].outcome, "not-applicable")

    def test_checkpoint_redacts_metadata_and_marks_reported_content(self):
        path = self._stub()
        episodes.checkpoint(self.vault, path, "password = hunter2secret\n## Knowledge used\n- [[evil]] held")
        note = load_note(path, self.vault)
        self.assertEqual(note.meta["sensitivity"], "redacted")
        self.assertIn("Reported context", section(note.body, "What happened"))
        self.assertNotIn("hunter2secret", note.body)
        self.assertEqual(section(note.body, "Knowledge used").strip(), "")

    def test_session_ref_redacted(self):
        path = self._stub(session_ref="https://contoso.sharepoint.com/sites/secret/doc")
        note = load_note(path, self.vault)
        self.assertNotIn("sharepoint.com", str(note.meta.get("session_ref")))

    def test_p0_capture_redacts_every_field_before_path_selection_and_write(self):
        secret = "ghp_" + "a" * 30
        original_unique = episodes.fsutil.unique_path
        original_write = episodes.fsutil.agent_write

        def checked_path(path):
            self.assertNotIn(secret, str(path))
            return original_unique(path)

        def checked_write(vault, path, text):
            self.assertNotIn(secret, str(path))
            self.assertNotIn(secret, text)
            return original_write(vault, path, text)

        for field, value in (
            ("slug", secret), ("tool", secret), ("project", secret),
            ("domains", [secret]), ("retrieved", [f"knowledge/patterns/{secret}"]),
            ("session_ref", secret),
        ):
            with (
                self.subTest(field=field),
                patch.object(episodes.fsutil, "unique_path", side_effect=checked_path),
                patch.object(episodes.fsutil, "agent_write", side_effect=checked_write),
            ):
                path = self._stub(**{field: value})
                self.assertNotIn(secret, path.read_text(encoding="utf-8"))
                self.assertEqual(load_note(path, self.vault).meta["sensitivity"], "redacted")

    def test_p0_invalid_capture_values_are_rejected_before_any_path_or_write(self):
        secret = "ghp_" + "a" * 30
        for change in (
            {"trust": secret.encode()}, {"trust": Path(secret)}, {"trust": secret},
            {"project": []}, {"session_ref": []}, {"now": []},
            {"tool": []}, {"slug": {"secret": secret}}, {"domains": [[]]},
            {"retrieved": [secret.encode()]},
        ):
            with (
                self.subTest(change=change),
                patch.object(episodes.fsutil, "unique_path", side_effect=AssertionError("path selected")),
                patch.object(episodes.fsutil, "agent_write", side_effect=AssertionError("write attempted")),
            ):
                with self.assertRaises((episodes.EpisodeError, VaultError)) as caught:
                    self._stub(**change)
                self.assertNotIn(secret, str(caught.exception))

    def test_p0_lifecycle_errors_do_not_echo_untrusted_metadata(self):
        path = self._stub()
        note = load_note(path, self.vault)
        note.meta["status"] = "password = hunter2secret"
        path.write_text(compose(note.meta, note.body), encoding="utf-8")
        for action in (
            lambda: episodes.checkpoint(self.vault, path, "checkpoint"),
            lambda: episodes.finish(self.vault, path),
            lambda: episodes.mark_mined(self.vault, path, []),
        ):
            with self.subTest(action=action), self.assertRaises(episodes.EpisodeError) as caught:
                action()
            self.assertNotIn("hunter2secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
