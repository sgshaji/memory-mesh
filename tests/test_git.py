import subprocess
import os
import unittest
from unittest import mock
from datetime import datetime, timezone

from helpers import init_git, make_vault

from memory_mesh import gitutil, fsutil
from memory_mesh.config import Vault
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
        result = self._external_git("log", *args)
        result.check_returncode()
        return result.stdout

    def _external_git(self, *args, data=None):
        env = os.environ.copy()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            env.pop(name, None)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        return subprocess.run(
            ["git", "--no-pager", "-C", str(self.vault.root), *args],
            input=data, capture_output=True, text=True, env=env,
        )

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

    def test_head_commit_preserves_legacy_abbreviated_sha_format(self):
        expected = gitutil._git(self.vault, "rev-parse", "--short", "HEAD").stdout.strip()
        self.assertEqual(gitutil.head_commit(self.vault), expected)

    def test_broken_existing_repository_is_failure_not_local_only_mode(self):
        with mock.patch.object(gitutil, "available", return_value=False):
            result = gitutil.commit_paths(
                self.vault, ["knowledge/patterns/validation-order.md"], "must fail",
            )
        self.assertFalse(result.committed)
        self.assertTrue(result.failed)
        self.assertFalse(result.manual_commit_required)

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
        self._external_git("add", "-A").check_returncode()
        self._external_git("commit", "-q", "-m", "episode").check_returncode()
        report = engine.run_compile(self.vault, now=NOW)
        self.assertIsNotNone(report.commit)
        self.assertTrue(report.commit.committed, report.commit.message)
        show = self._log("-1", "--stat")
        self.assertIn("curator compile", show)

    def test_unrelated_staged_file_remains_staged_and_uncommitted(self):
        unrelated = "projects/copilot-studio-skills.md"
        path = self.vault.path(unrelated)
        path.write_bytes(path.read_bytes() + b"\nuser staged data\n")
        gitutil._git(self.vault, "add", "--", unrelated)
        previous = gitutil._git(self.vault, "ls-files", "--stage", "--", unrelated).stdout
        target = "knowledge/patterns/exact-commit.md"
        self.vault.path(target).write_bytes(b"curator")
        result = gitutil.commit_paths(self.vault, [target], "one file only")
        self.assertTrue(result.committed, result.message)
        self.assertEqual(
            gitutil._git(self.vault, "ls-files", "--stage", "--", unrelated).stdout, previous
        )
        changed = gitutil._git(self.vault, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout
        self.assertEqual(changed.strip(), target)
        self.assertIn(unrelated, gitutil.dirty_paths(self.vault))

    def test_staged_requested_file_is_refused_without_index_changes(self):
        target = "knowledge/patterns/validation-order.md"
        path = self.vault.path(target)
        path.write_bytes(b"user staged version")
        gitutil._git(self.vault, "add", "--", target)
        path.write_bytes(b"different worktree version")
        before = gitutil._git(self.vault, "ls-files", "--stage").stdout
        result = gitutil.commit_paths(self.vault, [target], "must not clobber")
        self.assertTrue(result.failed)
        self.assertFalse(result.committed)
        self.assertIn("staged user changes", result.message)
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, before)
        self.assertEqual(path.read_bytes(), b"different worktree version")

    def test_commit_failure_preserves_unrelated_staging_and_reports_failure(self):
        unrelated = "projects/copilot-studio-skills.md"
        self.vault.path(unrelated).write_bytes(b"staged user work")
        gitutil._git(self.vault, "add", "--", unrelated)
        before = gitutil._git(self.vault, "ls-files", "--stage", "--", unrelated).stdout
        target = "knowledge/patterns/failure.md"
        self.vault.path(target).write_bytes(b"curator proposed bytes")
        real_git = gitutil._git

        def failing(vault, *args):
            if "commit" in args:
                return subprocess.CompletedProcess(args, 1, "", "fixture hook rejected commit")
            return real_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=failing):
            result = gitutil.commit_paths(self.vault, [target], "must fail")
        self.assertFalse(result.committed)
        self.assertTrue(result.failed)
        self.assertIn("git commit failed", result.message)
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage", "--", unrelated).stdout, before)
        self.assertEqual(self.vault.path(target).read_bytes(), b"curator proposed bytes")

    def test_deleted_named_path_is_committed(self):
        target = "knowledge/patterns/validation-order.md"
        self.vault.path(target).unlink()
        result = gitutil.commit_paths(self.vault, [target], "delete exact path")
        self.assertTrue(result.committed, result.message)
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--", target).stdout, "")

    def test_deleted_path_staging_failure_is_reported(self):
        target = "knowledge/patterns/validation-order.md"
        self.vault.path(target).unlink()
        real_git = gitutil._git

        def failing(vault, *args):
            if args and args[0] == "add":
                return subprocess.CompletedProcess(args, 1, "", "fixture index is locked")
            return real_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=failing):
            result = gitutil.commit_paths(self.vault, [target], "cannot stage deletion")
        self.assertTrue(result.failed)
        self.assertIn("git add failed", result.message)

    def test_noop_does_not_commit_unrelated_index(self):
        unrelated = "projects/copilot-studio-skills.md"
        self.vault.path(unrelated).write_bytes(b"staged user work")
        gitutil._git(self.vault, "add", "--", unrelated)
        head = gitutil.head_commit(self.vault)
        result = gitutil.commit_paths(self.vault, ["knowledge/patterns/validation-order.md"], "noop")
        self.assertFalse(result.committed)
        self.assertFalse(result.failed)
        self.assertEqual(gitutil.head_commit(self.vault), head)
        self.assertIn(unrelated, gitutil.dirty_paths(self.vault))

    def test_commit_refuses_directory_and_escape_pathspecs(self):
        for path in ("knowledge", "../outer.md", "C:\\outside.md", ":(top)**", ".git/config"):
            with self.subTest(path=path):
                result = gitutil.commit_paths(self.vault, [path], "unsafe path")
                self.assertTrue(result.failed)

    def test_missing_nested_repository_never_uses_outer_git(self):
        nested = self.vault.root / "nested-vault"
        nested.mkdir()
        nested_vault = Vault(nested)
        head = gitutil.head_commit(self.vault)
        self.assertFalse(gitutil.available(nested_vault))
        self.assertIsNone(gitutil.head_commit(nested_vault))
        self.assertEqual(gitutil.dirty_paths(nested_vault), [])
        result = gitutil.commit_paths(nested_vault, ["anything.md"], "must not commit outer repository")
        self.assertFalse(result.committed)
        self.assertFalse(result.failed)
        self.assertTrue(result.manual_commit_required)
        self.assertIn("manual commit required", result.message)
        self.assertEqual(gitutil.head_commit(self.vault), head)

    def test_dirty_path_with_spaces_is_not_stripped_or_quoted(self):
        target = "00-inbox/with spaces.md"
        self.vault.path(target).write_bytes(b"new")
        self.assertIn(target, gitutil.dirty_paths(self.vault))
        result = gitutil.commit_paths(self.vault, [target], "literal spaces")
        self.assertTrue(result.committed, result.message)

    def test_transaction_checks_input_before_git_mutates_index(self):
        from memory_mesh.curator.transaction import CurationConflict, curation_transaction

        target = "knowledge/patterns/validation-order.md"
        before = gitutil._git(self.vault, "ls-files", "--stage").stdout
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                fsutil.curator_write(self.vault, target, "curator")
                self.vault.path(target).write_bytes(b"manual later")
                gitutil.commit_paths(self.vault, [target], "must conflict")
        self.assertEqual(self.vault.path(target).read_bytes(), b"manual later")
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, before)

    def test_transaction_excludes_untouched_dirty_paths_even_if_requested(self):
        from memory_mesh.curator.transaction import curation_transaction

        unrelated = "knowledge/patterns/validation-order.md"
        self.vault.path(unrelated).write_bytes(b"pre-existing user edit")
        target = "knowledge/patterns/curator-only.md"
        with curation_transaction(self.vault):
            fsutil.curator_write(self.vault, target, "curator")
            result = gitutil.commit_paths(self.vault, [target, unrelated], "curator only")
        self.assertTrue(result.committed, result.message)
        self.assertIn(unrelated, gitutil.dirty_paths(self.vault))
        changed = gitutil._git(self.vault, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout
        self.assertEqual(changed.strip(), target)

    def test_real_failing_hook_restores_files_and_index_then_retry_succeeds(self):
        from memory_mesh.curator.transaction import CurationPublicationError, curation_transaction

        target = self.vault.path("knowledge/patterns/validation-order.md")
        review = self.vault.path("_meta/review/approved.md")
        archive = self.vault.path("_meta/review/archive/approved.md")
        original = target.read_bytes()
        review.write_bytes(b"approved fixture decision")
        self.assertEqual(gitutil._git(self.vault, "add", "--", self.vault.rel(review)).returncode, 0)
        self.assertEqual(gitutil._git(self.vault, "commit", "-q", "-m", "fixture review").returncode, 0)
        unrelated = self.vault.path("unrelated.txt")
        unrelated.write_bytes(b"user staged content\n")
        self.assertEqual(gitutil._git(self.vault, "add", "--", "unrelated.txt").returncode, 0)
        before_patch = gitutil._git(self.vault, "diff", "--cached", "--binary").stdout
        before_entries = gitutil._git(self.vault, "ls-files", "--stage").stdout
        before_index_bytes = self.vault.path(".git/index").read_bytes()
        before_head = gitutil.head_commit(self.vault)
        hook = self.vault.path(".git/hooks/pre-commit")
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o700)
        try:
            with self.assertRaises(CurationPublicationError):
                with curation_transaction(self.vault) as tx:
                    fsutil.curator_write(self.vault, target, "proposed fixture publication\n")
                    fsutil.curator_rename(self.vault, review, archive)
                    result = gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "fixture attempt")
                    self.assertTrue(result.failed)
                    self.assertFalse(result.committed)
        finally:
            hook.unlink()
        self.assertEqual(gitutil.head_commit(self.vault), before_head)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(review.read_bytes(), b"approved fixture decision")
        self.assertFalse(archive.exists())
        self.assertEqual(gitutil._git(self.vault, "diff", "--cached", "--binary").stdout, before_patch)
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, before_entries)
        self.assertEqual(self.vault.path(".git/index").read_bytes(), before_index_bytes)
        with curation_transaction(self.vault) as tx:
            fsutil.curator_write(self.vault, target, "proposed fixture publication\n")
            fsutil.curator_rename(self.vault, review, archive)
            result = gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "fixture retry")
            self.assertTrue(result.committed, result.message)
        self.assertEqual(target.read_bytes(), b"proposed fixture publication\n")
        self.assertFalse(review.exists())
        self.assertEqual(archive.read_bytes(), b"approved fixture decision")
        self.assertEqual(gitutil._git(self.vault, "diff", "--cached", "--binary").stdout, before_patch)

    def test_failed_hook_preserves_a_concurrently_staged_user_change(self):
        from memory_mesh.curator.transaction import CurationPublicationError, curation_transaction

        target = self.vault.path("knowledge/patterns/validation-order.md")
        before = target.read_bytes()
        user = self.vault.path("unrelated.txt")
        user.write_bytes(b"initial user stage\n")
        self.assertEqual(self._external_git("add", "--", "unrelated.txt").returncode, 0)
        hook = self.vault.path(".git/hooks/pre-commit")
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o700)
        native_git = gitutil._git

        def concurrent(vault, *args):
            if "commit" in args:
                user.write_bytes(b"latest user stage\n")
                self.assertEqual(self._external_git("add", "--", "unrelated.txt").returncode, 0)
            return native_git(vault, *args)

        try:
            with mock.patch.object(gitutil, "_git", side_effect=concurrent):
                with self.assertRaises(CurationPublicationError):
                    with curation_transaction(self.vault) as tx:
                        fsutil.curator_write(self.vault, target, "rejected proposal\n")
                        result = gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "reject")
                        self.assertTrue(result.failed)
        finally:
            hook.unlink()
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self._external_git("show", ":unrelated.txt").stdout, "latest user stage\n")
        self.assertEqual(self._external_git("diff", "--cached", "--name-only", "--", self.vault.rel(target)).stdout, "")

    def test_success_preserves_user_staging_added_at_index_reconciliation(self):
        target = "knowledge/patterns/validation-order.md"
        self.vault.path(target).write_bytes(b"curator publication\n")
        native_git = gitutil._git
        staged = []

        def concurrent(vault, *args):
            if args and args[0] == "read-tree" and "-m" in args and not staged:
                self.vault.path("unrelated.txt").write_bytes(b"late user stage\n")
                self.assertEqual(self._external_git("add", "--", "unrelated.txt").returncode, 0)
                staged.append(True)
            return native_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=concurrent):
            result = gitutil.commit_paths(self.vault, [target], "index-only merge")
        self.assertTrue(result.committed, result.message)
        self.assertFalse(result.failed)
        self.assertEqual(staged, [True])
        self.assertEqual(self._external_git("show", ":unrelated.txt").stdout, "late user stage\n")
        self.assertEqual(self._external_git("diff", "--cached", "--name-only").stdout.strip(), "unrelated.txt")

    def test_overlapping_user_stage_is_preserved_and_recovery_remains_explicit(self):
        from memory_mesh.curator.transaction import (
            CurationRecoveryError, curation_transaction, recover_curation_transactions,
        )

        target = "knowledge/patterns/validation-order.md"
        native_git = gitutil._git
        user_blob = self._external_git("hash-object", "-w", "--stdin", data="user staged alternative\n").stdout.strip()
        staged = []

        def concurrent(vault, *args):
            if args and args[0] == "read-tree" and "-m" in args and not staged:
                result = self._external_git("update-index", "--cacheinfo", f"100644,{user_blob},{target}")
                self.assertEqual(result.returncode, 0, result.stderr)
                staged.append(True)
            return native_git(vault, *args)

        with mock.patch.object(gitutil, "_git", side_effect=concurrent):
            with self.assertRaisesRegex(CurationRecoveryError, "index needs review"):
                with curation_transaction(self.vault) as tx:
                    fsutil.curator_write(self.vault, target, "published value\n")
                    result = gitutil.commit_paths(self.vault, sorted(tx.publishable_paths), "conflicting stage")
                    self.assertTrue(result.committed)
                    self.assertTrue(result.failed)
        self.assertEqual(self._external_git("show", f":{target}").stdout, "user staged alternative\n")
        self.assertEqual(self._external_git("show", f"HEAD:{target}").stdout, "published value\n")
        self.assertEqual(recover_curation_transactions(self.vault)[0].state, "conflict")
        self.assertEqual(self._external_git("show", f":{target}").stdout, "user staged alternative\n")
        self.assertEqual(self._external_git("add", "--", target).returncode, 0)
        self.assertEqual(recover_curation_transactions(self.vault)[0].state, "committed")
        self.assertEqual(self._external_git("diff", "--cached", "--name-only").stdout, "")

    def test_first_commit_preserves_unrelated_staging_in_unborn_repository(self):
        fresh = Vault(self.vault.root.parent / "unborn")
        fresh.scaffold()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "fixture"),
            ("config", "user.email", "fixture@example.test"),
            ("config", "commit.gpgsign", "false"),
        ):
            self.assertEqual(gitutil._git(fresh, *args).returncode, 0)
        fresh.path("user.txt").write_bytes(b"user stage\n")
        self.assertEqual(gitutil._git(fresh, "add", "--", "user.txt").returncode, 0)
        target = "knowledge/patterns/first.md"
        fresh.path(target).write_bytes(b"first publication\n")
        result = gitutil.commit_paths(fresh, [target], "first curator commit")
        self.assertTrue(result.committed, result.message)
        self.assertFalse(result.failed)
        self.assertEqual(gitutil._git(fresh, "diff", "--cached", "--name-only").stdout.strip(), "user.txt")


if __name__ == "__main__":
    unittest.main()
