"""The Definition-of-Done loop, end to end (mandate final section):

RECALL → WORK → /learn → EPISODE (retrieved vs used) → CURATION →
PROMOTION → INDEX UPDATE → PACK → IMPROVED RECALL — with derived state
deletable throughout and Git showing the canonical change.
"""

import io
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from helpers import init_git, make_vault

from memory_mesh import capture, config, episodes, packs, recall
from memory_mesh.curator import engine
from memory_mesh.frontmatter import compose, parse as fm_parse
from memory_mesh.notes import load_note

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class TestFullLoop(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()
        self.git = init_git(self.vault)

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def _write_episode(self, name, learning, captured, retrieved="", used=""):
        p = self.vault.path(f"episodes/{name}.md")
        p.write_text(f"""---
type: episode
tool: claude-code
domains: [coding-agents]
captured: {captured}
trust: first-party
sensitivity: checked
status: summarised
session_ref: e2e
---

# Session: e2e

## Goal
build the thing

## What happened
- worked through it

## Decisions

## Problems

## Knowledge retrieved
{retrieved}

## Knowledge used
{used}

## Candidate learnings
- {learning}
""", encoding="utf-8")
        return p

    def test_full_loop(self):
        task = "use claude code to refactor the repo interface"

        # 1-3: recall for coding-agents starts empty (nothing known yet)
        r0 = recall.recall(self.vault, task, log=False)
        self.assertIn("coding-agents", r0.domains)
        self.assertEqual([n for n in r0.notes if n.domain == "coding-agents"], [])

        # 4-5: /learn lands a candidate in the inbox
        res = capture.learn(self.vault, "always enumerate dependent files before an interface change (claude-code, 2026-09)", source_tool="claude-code")
        self.assertTrue(self.vault.rel(res.path).startswith("00-inbox/"))

        # 6-7: two working sessions leave episodes with the same candidate learning
        self._write_episode("2026-09-02-claude-code-e2e-a",
                            "always enumerate dependent files before an interface change (claude-code, 2026-09)",
                            "2026-09-02T10:00:00+05:30")
        report1 = engine.run_compile(self.vault, now=NOW)
        created = [l for l in report1.log_lines if l.startswith("CREATE") and "always-enumerate" in l]
        self.assertTrue(created, "\n".join(report1.log_lines))
        ref = created[0].split()[1]
        stem = ref.split("/")[-1]

        self._write_episode("2026-09-03-claude-code-e2e-b",
                            "always enumerate dependent files before an interface change (claude-code, 2026-09)",
                            "2026-09-03T10:00:00+05:30",
                            retrieved=f"- [[{stem}]]",
                            used=f"- [[{stem}]] — held — enumeration prevented breakage")

        # 8-10: curation processes the evidence, promotes, updates the index
        report2 = engine.run_compile(self.vault, now=NOW)
        promoted = [l for l in report2.log_lines if l.startswith("PROMOTE")]
        self.assertTrue(promoted, "\n".join(report2.log_lines + report1.log_lines))
        note = load_note(self.vault.path(ref + ".md"), self.vault)
        self.assertEqual(note.status, "validated")
        idx = self.vault.path("knowledge/_index/coding-agents.md").read_text(encoding="utf-8")
        self.assertIn(stem, idx)

        # feedback closes the loop: lint derives served/held and confidence
        engine.run_lint(self.vault, now=NOW)
        meta, _ = fm_parse(self.vault.path(ref + ".md").read_text(encoding="utf-8"))
        self.assertGreaterEqual(meta["feedback"]["held"], 1)
        self.assertIn(meta["confidence"], ("low", "medium"))

        # 3 again: improved recall now serves the promoted note
        r1 = recall.recall(self.vault, task, log=False)
        self.assertIn(stem, [n.ref.split("/")[-1] for n in r1.notes])
        self.assertLessEqual(r1.token_total, config.TOKEN_BUDGET_RECALL)
        self.assertLessEqual(len(r1.notes), config.RECALL_MAX_NOTES)

        # 11: a fresh pack regenerates and stays inside the ceiling
        pack = packs.compile_pack(self.vault, "coding-agents", now=NOW)
        pmeta, pbody = fm_parse(pack.read_text(encoding="utf-8"))
        self.assertLessEqual(pmeta["token_estimate"], config.TOKEN_BUDGET_PACK)
        self.assertIn(stem.split("-")[0], pbody.lower())

        # 12: deleting derived logs/packs destroys nothing canonical
        rl = self.vault.path(config.RECALL_LOG)
        if rl.exists():
            rl.unlink()
        pack.unlink()
        note_again = load_note(self.vault.path(ref + ".md"), self.vault)
        self.assertEqual(note_again.status, "validated")
        pack2 = packs.compile_pack(self.vault, "coding-agents", now=NOW)
        self.assertTrue(pack2.exists())
        r2 = recall.recall(self.vault, task, log=False)
        self.assertIn(stem, [n.ref.split("/")[-1] for n in r2.notes])

        # 15: git shows the canonical change (when git is available)
        if self.git:
            log = subprocess.run(["git", "-C", str(self.vault.root), "log", "--format=%an %s"],
                                 capture_output=True, text=True, env=os.environ.copy(), check=True).stdout
            self.assertIn("curator", log)

        # 9: canonical changed only through the curator — the validated note
        # was written by curator_write paths; agents' surfaces cannot (see
        # test_safety.test_write_boundaries_agent)


if __name__ == "__main__":
    unittest.main()
