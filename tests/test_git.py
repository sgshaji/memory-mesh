import subprocess
import unittest
from datetime import datetime, timezone

from helpers import init_git, make_vault

from memory_mesh import gitutil
from memory_mesh.curator import engine

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class TestGit(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()
        if not init_git(self.vault):
            self.skipTest("git unavailable")

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def _log(self, *args):
        return subprocess.run(["git", "-C", str(self.vault.root), "log", *args],
                              capture_output=True, text=True).stdout

    def test_commit_only_named_paths(self):
        # unrelated user change must NOT be swallowed
        user_file = self.vault.path("projects/copilot-studio-skills.md")
        user_file.write_text(user_file.read_text(encoding="utf-8") + "\nuser edit in flight\n", encoding="utf-8")
        target = self.vault.path("knowledge/patterns/new-note.md")
        target.write_text("---\ntype: pattern\ntitle: t\ndomains: [copilot-studio]\nstatus: candidate\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        res = gitutil.commit_paths(self.vault, ["knowledge/patterns/new-note.md"], "curator test")
        self.assertTrue(res.committed)
        dirty = gitutil.dirty_paths(self.vault)
        self.assertIn("projects/copilot-studio-skills.md", dirty)
        self.assertNotIn("knowledge/patterns/new-note.md", dirty)

    def test_curator_author(self):
        target = self.vault.path("knowledge/patterns/author-check.md")
        target.write_text("---\ntype: pattern\ntitle: t\ndomains: [copilot-studio]\nstatus: candidate\ntrust: first-party\n---\n\n## Observations\n- [behaviour] x\n", encoding="utf-8")
        gitutil.commit_paths(self.vault, ["knowledge/patterns/author-check.md"], "curator test")
        out = self._log("-1", "--format=%an <%ae>")
        self.assertIn("curator <curator@memory-mesh.local>", out)

    def test_git_unavailable_reports_manual_commit(self):
        from memory_mesh.config import Vault
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            bare = Vault(td)
            res = gitutil.commit_paths(bare, ["x.md"], "msg")
            self.assertFalse(res.committed)
            self.assertIn("manual commit required", res.message + "nothing to commit")

    def test_revert_shows_canonical_change(self):
        # a curator run is one commit; git revert restores the prior state
        p = self.vault.path("episodes/2026-09-02-claude-code-tg.md")
        p.write_text("""---
type: episode
tool: claude-code
domains: [copilot-studio]
captured: 2026-09-02T10:00:00+05:30
trust: first-party
sensitivity: checked
status: summarised
session_ref: g-1
---

# Session: git test

## Goal
g

## What happened
- worked

## Decisions

## Problems

## Knowledge retrieved

## Knowledge used

## Candidate learnings
- agent flows cap at two minutes runtime (copilot-studio, 2026-09)
""", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.vault.root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(self.vault.root), "commit", "-q", "-m", "episode"], capture_output=True)
        report = engine.run_compile(self.vault, now=NOW)
        self.assertIsNotNone(report.commit)
        self.assertTrue(report.commit.committed, report.commit.message)
        show = self._log("-1", "--stat")
        self.assertIn("curator compile", show)


if __name__ == "__main__":
    unittest.main()
