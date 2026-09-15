import unittest
from datetime import datetime, timedelta, timezone

from helpers import make_vault

from memory_mesh import config, packs
from memory_mesh.frontmatter import compose, parse as fm_parse
from memory_mesh.notes import load_note

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class TestPacks(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_deterministic_generation(self):
        p1 = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        text1 = p1.read_text(encoding="utf-8")
        p2 = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        self.assertEqual(text1, p2.read_text(encoding="utf-8"))

    def test_frontmatter_contract(self):
        p = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        meta, body = fm_parse(p.read_text(encoding="utf-8"))
        for f in ("type", "domain", "generated_at", "valid_until", "source_commit", "source_index", "token_estimate", "status"):
            self.assertIn(f, meta)
        self.assertEqual(meta["type"], "context-pack")
        self.assertEqual(meta["source_index"], "knowledge/_index/copilot-studio.md")
        self.assertLessEqual(meta["token_estimate"], config.TOKEN_BUDGET_PACK)
        # body inlines observations, not full notes
        self.assertIn("## Read first", body)
        self.assertIn("- [behaviour]", body)

    def test_token_ceiling_with_recorded_drops(self):
        # inflate the vault with big validated notes linked from the index
        di_path = self.vault.path("knowledge/_index/copilot-studio.md")
        text = di_path.read_text(encoding="utf-8")
        extra = []
        for i in range(8):
            rel = f"knowledge/patterns/big-{i}.md"
            obs = "\n".join(f"- [behaviour] very long filler observation number {j} with plenty of words to consume budget" for j in range(40))
            self.vault.path(rel).write_text(compose(
                {"type": "pattern", "title": f"big {i}", "domains": ["copilot-studio"], "status": "validated",
                 "trust": "first-party", "evidence": ["episodes/2026-08-14-claude-code-api-change"]},
                "## Observations\n" + obs + "\n"), encoding="utf-8")
            extra.append(f"- [[big-{i}]] — big filler")
        di_path.write_text(text.replace("## Known failures", "\n".join(extra) + "\n\n## Known failures"), encoding="utf-8")
        p = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        meta, body = fm_parse(p.read_text(encoding="utf-8"))
        self.assertLessEqual(meta["token_estimate"], config.TOKEN_BUDGET_PACK)
        self.assertIn("## Omitted for budget", body)  # no silent caps

    def test_freshness_rule(self):
        gen = NOW
        meta = {"generated_at": gen.isoformat(), "valid_until": (gen + timedelta(days=7)).isoformat()}
        self.assertEqual(packs.freshness(meta, gen + timedelta(days=3)), "current")
        self.assertEqual(packs.freshness(meta, gen + timedelta(days=10)), "stale")
        # "expired by more than twice the window" (7d window → expired >14d)
        self.assertEqual(packs.freshness(meta, gen + timedelta(days=20)), "stale")
        self.assertEqual(packs.freshness(meta, gen + timedelta(days=22)), "not-authoritative")
        self.assertEqual(packs.freshness({}, NOW), "not-authoritative")

    def test_rebuild_after_deletion(self):
        p = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        canonical_before = sorted(str(x) for x in self.vault.path("knowledge").rglob("*.md"))
        p.unlink()
        p2 = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        self.assertTrue(p2.exists())
        canonical_after = sorted(str(x) for x in self.vault.path("knowledge").rglob("*.md"))
        self.assertEqual(canonical_before, canonical_after)

    def test_source_commit_recorded(self):
        from helpers import init_git

        if not init_git(self.vault):
            self.skipTest("git unavailable")
        p = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        meta, _ = fm_parse(p.read_text(encoding="utf-8"))
        self.assertNotEqual(meta["source_commit"], "uncommitted")

    def test_compile_all_skips_router_and_general(self):
        out = packs.compile_all(self.vault, now=NOW)
        names = {p.name for p in out}
        self.assertIn("copilot-studio-current.md", names)
        self.assertNotIn("_domains-current.md", names)
        self.assertNotIn("_general-current.md", names)

    def test_applicability_and_inactive_notes_do_not_leak_into_packs(self):
        path = self.vault.path("knowledge/patterns/validation-order.md")
        note = load_note(path, self.vault)
        for applies_to, context, status, included in (
            ({"to": "2026-08"}, None, "validated", False),
            ({"version": ">=2"}, {"version": "1"}, "validated", False),
            ({"version": ">=2"}, None, "validated", True),
            (None, None, "validated", True),
            (None, None, "stale", False),
        ):
            with self.subTest(applies_to=applies_to, context=context, status=status):
                note.meta.update(applies_to=applies_to, status=status)
                path.write_text(compose(note.meta, note.body), encoding="utf-8")
                pack = packs.compile_pack(self.vault, "copilot-studio", now=NOW, context=context)
                self.assertEqual(
                    f"### {note.title}" in pack.read_text(encoding="utf-8"), included,
                )
        self.assertFalse(self.vault.path(config.RECALL_ATTEMPTS).exists())
        self.assertFalse(self.vault.path(config.RECALL_LOG).exists())

    def test_invalid_index_ref_is_an_explicit_pack_error_and_preserves_prior_output(self):
        output = packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        before = output.read_bytes()
        index = self.vault.path("knowledge/_index/copilot-studio.md")
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "## Read first", "## Read first\n- [[../outside]]",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(packs.PackError, "invalid note reference"):
            packs.compile_pack(self.vault, "copilot-studio", now=NOW)
        self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
