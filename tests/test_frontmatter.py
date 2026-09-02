import unittest

from helpers import *  # noqa: F401,F403 — sys.path setup

from memory_mesh import frontmatter as fm


class TestFrontmatter(unittest.TestCase):
    def test_roundtrip_knowledge_shape(self):
        doc = (
            "---\n"
            "type: pattern\n"
            "title: Inspect dependents before API changes\n"
            "domains: [coding-agents]\n"
            "status: validated\n"
            "trust: first-party\n"
            "confidence: high\n"
            "applies_to:\n"
            "  tools: [claude-code]\n"
            "  from: 2026-08\n"
            "first_observed: 2026-08-14\n"
            "feedback: {served: 12, held: 10, failed: 1, unclear: 1}\n"
            "evidence: [episodes/2026-08-14-claude-code-api-change]\n"
            "superseded_by: null\n"
            "---\n\nbody text\n"
        )
        meta, body = fm.parse(doc)
        self.assertEqual(meta["type"], "pattern")
        self.assertEqual(meta["domains"], ["coding-agents"])
        self.assertEqual(meta["applies_to"], {"tools": ["claude-code"], "from": "2026-08"})
        self.assertEqual(meta["feedback"], {"served": 12, "held": 10, "failed": 1, "unclear": 1})
        self.assertIsNone(meta["superseded_by"])
        self.assertEqual(body.strip(), "body text")
        # round-trip preserves values
        meta2, body2 = fm.parse(fm.compose(meta, body))
        self.assertEqual(meta, meta2)
        self.assertEqual(body.strip(), body2.strip())

    def test_inline_comments_stripped(self):
        meta = fm.parse_yaml_subset('status: validated   # candidate | validated\nn: 3 # count')
        self.assertEqual(meta, {"status": "validated", "n": 3})

    def test_hash_in_quotes_kept(self):
        meta = fm.parse_yaml_subset('title: "issue #42"')
        self.assertEqual(meta["title"], "issue #42")

    def test_block_list(self):
        meta = fm.parse_yaml_subset("evidence:\n  - a\n  - b\n")
        self.assertEqual(meta["evidence"], ["a", "b"])

    def test_malformed_raises(self):
        with self.assertRaises(fm.FrontmatterError):
            fm.parse_yaml_subset("just some prose without a colon structure [")

    def test_unterminated_raises(self):
        with self.assertRaises(fm.FrontmatterError):
            fm.parse("---\ntype: x\nno closing delimiter")

    def test_no_frontmatter_is_ok(self):
        meta, body = fm.parse("# plain markdown\n")
        self.assertEqual(meta, {})
        self.assertIn("plain markdown", body)

    def test_dates_stay_strings(self):
        meta = fm.parse_yaml_subset("d: 2026-08-14\nm: 2026-08")
        self.assertEqual(meta["d"], "2026-08-14")
        self.assertEqual(meta["m"], "2026-08")

    def test_special_chars_quoted_on_dump(self):
        s = fm.dump_yaml_subset({"title": "a: b # c"})
        meta = fm.parse_yaml_subset(s)
        self.assertEqual(meta["title"], "a: b # c")


if __name__ == "__main__":
    unittest.main()
