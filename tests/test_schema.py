import unittest

from helpers import make_vault

from memory_mesh import config
from memory_mesh.notes import iter_notes, load_note
from memory_mesh.schema import NOTE_TYPES, domain_names, validate_note


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()
        self.domains = domain_names(self.vault)

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def _issues(self, rel):
        note = load_note(self.vault.path(rel), self.vault)
        return validate_note(note, self.vault, self.domains)

    def test_fixture_vault_is_clean(self):
        errors = []
        for rel in (config.INBOX, config.EPISODES, config.KNOWLEDGE, config.PROJECTS):
            for note in iter_notes(self.vault, rel):
                if note.type == "index":
                    continue
                errors += [i for i in validate_note(note, self.vault, self.domains) if i.severity == "error"]
        self.assertEqual(errors, [], msg="\n".join(str(e) for e in errors))

    def test_type_folder_map(self):
        self.assertEqual(NOTE_TYPES["pattern"][0], "knowledge/patterns")
        self.assertEqual(NOTE_TYPES["tool-behaviour"][0], "knowledge/tools")
        self.assertEqual(NOTE_TYPES["episode"][0], "episodes")
        # a pattern outside its folder is an error
        p = self.vault.path("knowledge/tools/misplaced.md")
        p.write_text("---\ntype: pattern\ntitle: t\ndomains: [copilot-studio]\nstatus: candidate\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        issues = self._issues("knowledge/tools/misplaced.md")
        self.assertTrue(any("belongs under knowledge/patterns/" in i.message for i in issues))

    def test_malformed_frontmatter_reported(self):
        p = self.vault.path("knowledge/patterns/broken.md")
        p.write_text("---\n:::\n---\nbody\n", encoding="utf-8")
        issues = self._issues("knowledge/patterns/broken.md")
        self.assertTrue(any("malformed frontmatter" in i.message for i in issues))

    def test_unknown_domain_rejected(self):
        p = self.vault.path("knowledge/patterns/bad-domain.md")
        p.write_text("---\ntype: pattern\ntitle: t\ndomains: [nonexistent]\nstatus: candidate\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        issues = self._issues("knowledge/patterns/bad-domain.md")
        self.assertTrue(any("not declared" in i.message for i in issues))

    def test_validated_needs_evidence(self):
        p = self.vault.path("knowledge/patterns/no-evidence.md")
        p.write_text("---\ntype: pattern\ntitle: t\ndomains: [copilot-studio]\nstatus: validated\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        issues = self._issues("knowledge/patterns/no-evidence.md")
        self.assertTrue(any("at least one evidence" in i.message for i in issues))

    def test_episode_never_processed(self):
        p = self.vault.path("episodes/2026-09-02-x-bad.md")
        p.write_text("---\ntype: episode\ntool: x\ncaptured: 2026-09-02T10:00:00+05:30\ntrust: first-party\nsensitivity: checked\nstatus: raw\nprocessed: run-1\n---\n\n# Session: s\n", encoding="utf-8")
        issues = self._issues("episodes/2026-09-02-x-bad.md")
        self.assertTrue(any("never carry `processed:`" in i.message for i in issues))

    def test_unreviewed_only_under_unreviewed(self):
        p = self.vault.path("episodes/_unreviewed/2026-06-01-x-old.md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntype: candidate\ntitle: t\nsource: x\ncaptured: 2026-06-01T10:00:00+05:30\ntrust: first-party\nsensitivity: checked\nstatus: unreviewed\n---\n\n## Observations\n- [observation] x\n", encoding="utf-8")
        note = load_note(p, self.vault)
        issues = [i for i in validate_note(note, self.vault, self.domains) if i.severity == "error"]
        self.assertEqual(issues, [], msg="\n".join(str(i) for i in issues))

    def test_bad_status_transition_vocab(self):
        p = self.vault.path("knowledge/patterns/bad-status.md")
        p.write_text("---\ntype: pattern\ntitle: t\ndomains: [copilot-studio]\nstatus: verified\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        issues = self._issues("knowledge/patterns/bad-status.md")
        self.assertTrue(any("invalid status" in i.message for i in issues))


if __name__ == "__main__":
    unittest.main()
