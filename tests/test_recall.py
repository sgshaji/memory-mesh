import unittest

from helpers import make_vault

from memory_mesh import config, recall
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.router import load_domains, match


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_domain_matching(self):
        domains = load_domains(self.vault)
        self.assertEqual(match("Build a Copilot Studio validation agent", domains), ["copilot-studio"])
        self.assertIn("coding-agents", match("refactor this repo with claude code", domains))

    def test_multi_domain_matching_capped_at_two(self):
        domains = load_domains(self.vault)
        got = match("copilot studio topic with a skill trigger over mcp stdio", domains)
        self.assertEqual(len(got), 2)

    def test_general_fallback_records_unclassified(self):
        res = recall.recall(self.vault, "vacation photo organiser in rust", log=False)
        self.assertTrue(res.unclassified)
        self.assertEqual(res.domains, ["unclassified"])
        self.assertTrue(any(di.path.name == "_general.md" for di in res.indexes))

    def test_recall_serves_validated_notes_within_budget(self):
        res = recall.recall(self.vault, "Build a Copilot Studio validation agent", log=False)
        refs = [n.ref.split("/")[-1] for n in res.notes]
        self.assertIn("validation-order", refs)
        self.assertIn("cs-optional-properties", refs)
        self.assertLessEqual(len(res.notes), config.RECALL_MAX_NOTES)
        self.assertLessEqual(res.token_total, config.TOKEN_BUDGET_RECALL)

    def test_note_budget_ceiling(self):
        # add many validated notes to one index to exceed six
        di_path = self.vault.path("knowledge/_index/copilot-studio.md")
        text = di_path.read_text(encoding="utf-8")
        extra = []
        for i in range(10):
            rel = f"knowledge/patterns/filler-{i}.md"
            self.vault.path(rel).write_text(
                compose(
                    {"type": "pattern", "title": f"filler {i}", "domains": ["copilot-studio"], "status": "validated",
                     "trust": "first-party", "evidence": ["episodes/2026-08-14-claude-code-api-change"]},
                    f"## Observations\n- [behaviour] filler fact {i}\n",
                ),
                encoding="utf-8",
            )
            extra.append(f"- [[filler-{i}]] — filler")
        text = text.replace("## Known failures", "\n".join(extra) + "\n\n## Known failures")
        di_path.write_text(text, encoding="utf-8")
        res = recall.recall(self.vault, "copilot studio work", log=False)
        self.assertLessEqual(len(res.notes), config.RECALL_MAX_NOTES)
        self.assertTrue(any("note budget" in s for s in res.skipped))

    def test_stale_notes_excluded(self):
        p = self.vault.path("knowledge/patterns/validation-order.md")
        note = load_note(p, self.vault)
        meta = dict(note.meta)
        meta["status"] = "stale"
        p.write_text(compose(meta, note.body), encoding="utf-8")
        res = recall.recall(self.vault, "copilot studio work", log=False)
        refs = [n.ref.split("/")[-1] for n in res.notes]
        self.assertNotIn("validation-order", refs)
        self.assertTrue(any("validation-order (stale)" in s for s in res.skipped))

    def test_recall_log_written_and_disposable(self):
        recall.recall(self.vault, "copilot studio work", tool="test")
        log = self.vault.path(config.RECALL_LOG)
        self.assertTrue(log.exists())
        line = log.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(len(line.split("\t")), 4)  # timestamp, tool, domain, note
        # deleting it must not affect a later recall (derived telemetry, P1)
        log.unlink()
        res = recall.recall(self.vault, "copilot studio work", tool="test")
        self.assertTrue(res.notes)
        self.assertTrue(log.exists())

    def test_session_state_accumulates_retrieved(self):
        recall.recall(self.vault, "copilot studio work", session_id="s1", log=False)
        state = recall.load_session_state(self.vault, "s1")
        self.assertTrue(state.get("recalled"))
        self.assertTrue(any("validation-order" in r for r in state.get("retrieved", [])))

    def test_unresolved_link_skipped_not_fatal(self):
        di_path = self.vault.path("knowledge/_index/copilot-studio.md")
        text = di_path.read_text(encoding="utf-8").replace(
            "## Known failures", "- [[ghost-note]] — missing\n\n## Known failures"
        )
        di_path.write_text(text, encoding="utf-8")
        res = recall.recall(self.vault, "copilot studio work", log=False)
        self.assertTrue(any("ghost-note (unresolved)" in s for s in res.skipped))


if __name__ == "__main__":
    unittest.main()
