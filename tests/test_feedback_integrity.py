import os
import unittest
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import capture, frontmatter, fsutil, outcomes
from memory_mesh.notes import iter_notes, load_note


class FeedbackIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def test_duplicate_keys_are_rejected_at_every_mapping_level(self):
        for text in (
            "type: episode\ntype: candidate",
            "context:\n  tool: cli\n  tool: another",
            "context: {tool: cli, tool: another}",
            "context: {tool: cli, 'tool': another}",
        ):
            with self.subTest(text=text), self.assertRaises(frontmatter.FrontmatterError):
                frontmatter.parse("---\n" + text + "\n---\n")

    def test_transient_publication_link_is_retried_but_never_accepted_as_linked(self):
        event = outcomes.record_outcome(
            self.vault, session_id="transient", subject_type="knowledge",
            subject_id="validation-order", outcome="held", event_id="transient-event",
        )
        path = next(self.vault.path("episodes/_outcomes").glob("*.md"))
        stage = path.with_name(".outcome-test.pending")
        os.link(path, stage)
        real_read = fsutil.read_regular_bytes
        observations = []

        def finish_publication(target, **kwargs):
            observations.append(target.stat().st_nlink)
            try:
                return real_read(target, **kwargs)
            except fsutil.PathTraversalError:
                stage.unlink()
                raise

        with patch.object(fsutil, "read_regular_bytes", side_effect=finish_publication):
            self.assertEqual(outcomes.read_events(self.vault), [event])
        self.assertEqual(observations, [2, 1])
        self.assertFalse(stage.exists())

    def test_shared_reader_enforces_its_opened_file_byte_limit(self):
        path = self.vault.path("projects/read-limit.bin")
        path.write_bytes(b"1234")
        with self.assertRaises(fsutil.WriteBoundaryError):
            fsutil.read_regular_bytes(path, max_bytes=3)
        self.assertEqual(fsutil.read_regular_bytes(path, max_bytes=4), b"1234")

    def test_forward_episode_link_remains_supported(self):
        result = capture.learn(
            self.vault, "A forward source fixture.", source_episode="episodes/future-session",
        )
        meta, _ = frontmatter.parse(result.path.read_text(encoding="utf-8"))
        self.assertEqual(meta["source_episode"], "episodes/future-session")

    def test_preloaded_episode_evidence_matches_fresh_reads_without_reopening_notes(self):
        expected = outcomes.collect_evidence(self.vault)
        episodes = list(iter_notes(self.vault, "episodes"))
        original = outcomes.load_note

        def no_episode_reopen(path, vault):
            if path.is_relative_to(self.vault.path("episodes")):
                raise AssertionError("episode reopened")
            return original(path, vault)

        with patch.object(outcomes, "load_note", side_effect=no_episode_reopen):
            self.assertEqual(outcomes.collect_evidence(self.vault, episodes=episodes), expected)

    def test_preloaded_episode_from_another_vault_is_rejected(self):
        other, holder = make_vault()
        self.addCleanup(holder.cleanup)
        episodes = list(iter_notes(other, "episodes"))
        with self.assertRaises(outcomes.OutcomeError):
            outcomes.collect_evidence(self.vault, episodes=episodes)

    def test_loaded_note_identity_is_resolved_once_but_invalidates_on_path_change(self):
        note = load_note(self.vault.path("knowledge/patterns/validation-order.md"), self.vault)
        with patch.object(self.vault, "rel", wraps=self.vault.rel) as relative:
            for _ in range(20):
                self.assertEqual(note.ref, "knowledge/patterns/validation-order")
            self.assertEqual(relative.call_count, 1)
            note.path = self.vault.path("knowledge/patterns/another.md")
            self.assertEqual(note.ref, "knowledge/patterns/another")
            self.assertEqual(relative.call_count, 2)
        other, holder = make_vault()
        self.addCleanup(holder.cleanup)
        note.vault = other
        with self.assertRaises(ValueError):
            _ = note.ref

    def test_cached_identity_never_bypasses_filesystem_access_guards(self):
        path = self.vault.path("knowledge/patterns/validation-order.md")
        note = load_note(path, self.vault)
        self.assertEqual(note.ref, "knowledge/patterns/validation-order")
        alias = self.vault.root.parent / "outside-identity-alias.md"
        original = path.read_bytes()
        os.link(path, alias)
        with self.assertRaises(fsutil.PathTraversalError):
            load_note(path, self.vault)
        from memory_mesh.curator.transaction import curation_transaction

        with self.assertRaises(fsutil.PathTraversalError):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, path, "must not read linked input")
        fsutil.curator_write(self.vault, path, "replacement at the owned path")
        self.assertEqual(alias.read_bytes(), original)
        self.assertEqual(path.read_text(encoding="utf-8"), "replacement at the owned path")


if __name__ == "__main__":
    unittest.main()
