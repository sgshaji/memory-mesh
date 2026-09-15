import unittest
from datetime import datetime, timezone

from helpers import make_vault

from memory_mesh import config
from memory_mesh.curator import engine
from memory_mesh.frontmatter import compose
from memory_mesh.indexes import load_index, parse_index, render_index, validate_index

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class TestIndexes(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_parse_and_render_roundtrip(self):
        di = load_index(self.vault, "copilot-studio")
        self.assertEqual(di.domain, "copilot-studio")
        self.assertEqual(di.link_count(), 5)
        rendered = render_index(di, "2026-09-02")
        di2_path = self.vault.path("knowledge/_index/copilot-studio.md")
        di2_path.write_text(rendered, encoding="utf-8")
        di2 = parse_index(di2_path, self.vault)
        self.assertEqual(di.link_count(), di2.link_count())
        self.assertEqual(di2.meta["links"], 5)  # derived count

    def test_more_than_twelve_links_is_error(self):
        di = load_index(self.vault, "copilot-studio")
        for i in range(13):
            di.add("Read first", f"filler-{i}", "x")
        p = self.vault.path("knowledge/_index/copilot-studio.md")
        p.write_text(render_index(di, "2026-09-02"), encoding="utf-8")
        issues = validate_index(parse_index(p, self.vault), self.vault)
        self.assertTrue(any("one must leave" in i.message for i in issues))

    def test_missing_link_target_is_error(self):
        di = load_index(self.vault, "copilot-studio")
        di.add("Read first", "does-not-exist", "gone")
        p = self.vault.path("knowledge/_index/copilot-studio.md")
        p.write_text(render_index(di, "2026-09-02"), encoding="utf-8")
        issues = validate_index(parse_index(p, self.vault), self.vault)
        self.assertTrue(any("does not resolve" in i.message for i in issues))

    def test_stale_note_under_read_first_is_error_and_lint_moves_it(self):
        note_path = self.vault.path("knowledge/patterns/validation-order.md")
        from memory_mesh.notes import load_note

        note = load_note(note_path, self.vault)
        meta = dict(note.meta)
        meta["status"] = "stale"
        note_path.write_text(compose(meta, note.body), encoding="utf-8")
        p = self.vault.path("knowledge/_index/copilot-studio.md")
        issues = validate_index(parse_index(p, self.vault), self.vault)
        self.assertTrue(any("only validated notes belong" in i.message for i in issues))
        engine.run_lint(self.vault, now=NOW)
        di = parse_index(p, self.vault)
        ref = "knowledge/patterns/validation-order"
        self.assertFalse(any(e.ref in ("validation-order", ref) for e in di.sections["Read first"]))
        self.assertFalse(any(e.ref in ("validation-order", ref) for e in di.sections["Recently verified (30 days)"]))
        self.assertTrue(any(e.ref == ref for e in di.sections["Recently changed"]))

    def test_missing_section_is_error_and_lint_fixes(self):
        p = self.vault.path("knowledge/_index/coding-agents.md")
        text = p.read_text(encoding="utf-8").replace("## Recently changed\n", "")
        p.write_text(text.rstrip() + "\n", encoding="utf-8")
        issues = validate_index(parse_index(p, self.vault), self.vault)
        self.assertTrue(any("missing fixed section" in i.message for i in issues))
        engine.run_lint(self.vault, now=NOW)
        issues = validate_index(parse_index(p, self.vault), self.vault)
        self.assertFalse(any("missing fixed section" in i.message for i in issues))

    def test_orphan_added_to_index(self):
        p = self.vault.path("knowledge/patterns/orphan-note.md")
        p.write_text(compose(
            {"type": "pattern", "title": "an orphan validated note", "domains": ["coding-agents"],
             "status": "validated", "trust": "first-party",
             "evidence": ["episodes/2026-08-14-claude-code-api-change"]},
            "## Observations\n- [behaviour] orphan behaviour\n"), encoding="utf-8")
        engine.run_lint(self.vault, now=NOW)
        di = load_index(self.vault, "coding-agents")
        self.assertTrue(di.find("orphan-note"))

    def test_links_count_drift_fixed_by_lint(self):
        p = self.vault.path("knowledge/_index/copilot-studio.md")
        p.write_text(p.read_text(encoding="utf-8").replace("links: 5", "links: 99"), encoding="utf-8")
        engine.run_lint(self.vault, now=NOW)
        di = parse_index(p, self.vault)
        self.assertEqual(di.meta["links"], di.link_count())

    def test_recently_verified_updated_from_tally(self):
        engine.run_lint(self.vault, now=NOW)
        di = load_index(self.vault, "copilot-studio")
        rv = {e.ref for e in di.sections["Recently verified (30 days)"]}
        self.assertIn("knowledge/patterns/validation-order", rv)  # held within 30 days
        self.assertIn("knowledge/tools/cs-optional-properties", rv)


if __name__ == "__main__":
    unittest.main()
