import json
import re
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import config, fsutil, gitutil
from memory_mesh.config import VaultError
from memory_mesh.curator import engine, review
from memory_mesh.curator.decisions import Decision
from memory_mesh.curator.transaction import (
    CurationConflict,
    CurationPublicationError,
    curation_transaction,
    current_transaction,
)
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.experience import set_mode


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class TestCuratorIntegration(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.target = self.vault.path("knowledge/patterns/validation-order.md")

    def snapshot(self):
        return {path.relative_to(self.vault.root): path.read_bytes() for path in self.vault.root.rglob("*.md")}

    def pending(self, *, kind="REJECT", other=None, source=None):
        payload = {"target": self.vault.rel(self.target)}
        if other is not None:
            payload["other"] = self.vault.rel(other)
        decision = Decision(
            kind, "Fixture human decision", target_ref=self.vault.rel(self.target)[:-3],
            source_ref=self.vault.rel(source)[:-3] if source is not None else "",
            payload=payload,
        )
        path = review.write_review_file(self.vault, "fixture-review", NOW.date(), [decision])
        assert path is not None
        path.write_text(path.read_text(encoding="utf-8").replace("[ ] approve", "[x] approve"), encoding="utf-8")
        return path

    def replace_payload(self, path, payload):
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"<!--\s*mm:payload\s+.*?\s*-->",
            lambda _: "<!-- mm:payload " + json.dumps(payload) + " -->", text,
        )
        path.write_text(text, encoding="utf-8")

    def test_compile_failure_restores_notes_and_pending_review(self):
        pending = self.pending()
        before = self.snapshot()
        with patch.object(engine, "_promotion_pass", side_effect=RuntimeError("fixture interrupted compile")):
            with self.assertRaisesRegex(RuntimeError, "interrupted compile"):
                engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(pending.exists())
        self.assertFalse(list(self.vault.path(config.REVIEW_ARCHIVE).glob("*.md")))

    def test_profile_change_while_waiting_never_enters_legacy_mutation(self):
        original_boundary = engine.curation_transaction
        for run_name, implementation in (
            ("run_compile", "_run_legacy_compile"),
            ("run_lint", "_run_legacy_lint"),
        ):
            with self.subTest(command=run_name):
                vault, holder = make_vault()
                self.addCleanup(holder.cleanup)

                @contextmanager
                def changed_profile(*args, **kwargs):
                    set_mode(vault, "strict")
                    with original_boundary(*args, **kwargs) as transaction:
                        yield transaction

                with patch.object(engine, "curation_transaction", changed_profile):
                    with patch.object(engine, implementation) as legacy:
                        with self.assertRaisesRegex(VaultError, "profile changed"):
                            getattr(engine, run_name)(vault, now=NOW)
                        legacy.assert_not_called()

    def test_finalizer_includes_unreported_durable_transaction_writes(self):
        path = self.vault.path("knowledge/patterns/nested-write.md")
        report = engine.RunReport("nested-write")
        result = gitutil.CommitResult(False, None, "manual commit required", manual_commit_required=True)
        with curation_transaction(self.vault):
            fsutil.curator_write(self.vault, path, self.target.read_text(encoding="utf-8"))
            with patch.object(gitutil, "commit_paths", return_value=result) as commit:
                engine._finalise_run(self.vault, report, NOW.date(), "fixture finalization")
            self.assertIn(self.vault.rel(path), report.touched)
            self.assertIn(self.vault.rel(path), commit.call_args.args[1])

    def test_strict_profile_change_while_waiting_aborts_before_review(self):
        from memory_mesh.curator import v2

        set_mode(self.vault, "strict")
        original_boundary = v2.curation_transaction

        @contextmanager
        def changed_profile(*args, **kwargs):
            set_mode(self.vault, "off")
            with original_boundary(*args, **kwargs) as transaction:
                yield transaction

        with patch.object(v2, "curation_transaction", changed_profile):
            with patch.object(v2, "review_decisions") as decisions:
                with self.assertRaisesRegex(VaultError, "profile changed"):
                    engine.run_compile(self.vault, now=NOW)
                decisions.assert_not_called()

    def test_task_bound_indexing_requires_a_valid_reviewed_binding(self):
        note = load_note(self.target, self.vault)
        with self.assertRaises(VaultError):
            engine._index_add_note(
                self.vault, note, engine.RunReport("not-reviewed"), NOW.date(), task_bound=True,
            )

    def test_lint_failure_restores_parked_inbox_and_metadata(self):
        old = self.vault.path("00-inbox/ancient-integration-candidate.md")
        old.write_text(compose({
            "type": "candidate", "title": "Old attention item", "source": "fixture",
            "captured": "2020-01-01T12:00:00Z", "trust": "first-party", "sensitivity": "checked",
        }, "## Observations\n- [observation] An old unreviewed observation."), encoding="utf-8")
        before = self.snapshot()
        with patch.object(engine, "_graduation_pass", side_effect=RuntimeError("fixture interrupted lint")):
            with self.assertRaisesRegex(RuntimeError, "interrupted lint"):
                engine.run_lint(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(old.exists())
        self.assertFalse(self.vault.path(config.EPISODE_UNREVIEWED).joinpath(old.name).exists())

    def test_successful_review_reuses_outer_transaction_and_journals_archive(self):
        pending = self.pending()
        with curation_transaction(self.vault) as tx:
            report = engine.run_compile(self.vault, now=NOW)
            self.assertIs(current_transaction(self.vault), tx)
            tx.validate()
        self.assertFalse(pending.exists())
        self.assertTrue(self.vault.path(config.REVIEW_ARCHIVE).joinpath(pending.name).exists())
        self.assertEqual(load_note(self.target, self.vault).status, "rejected")
        self.assertIsNotNone(report.commit)

    def test_review_payload_records_exact_source_and_target_hashes(self):
        source = self.vault.path("00-inbox/2026-09-01-claude-code-dependents-first.md")
        pending = self.pending(source=source)
        payload = review.parse_review_file(pending)[0].payload
        self.assertEqual(payload["expected_hashes"], {
            self.vault.rel(self.target): fsutil.file_hash(self.target),
            self.vault.rel(source): fsutil.file_hash(source),
        })
        self.assertEqual(payload["source_ref"], self.vault.rel(source)[:-3])

    def test_hash_binding_uses_post_run_source_bytes_without_rebasing_existing_proposals(self):
        source = self.vault.path("00-inbox/2026-09-01-claude-code-dependents-first.md")
        decision = Decision(
            "REJECT", "Fixture decision", source_ref=self.vault.rel(source)[:-3],
            target_ref=self.vault.rel(self.target)[:-3], payload={"target": self.vault.rel(self.target)},
        )
        with curation_transaction(self.vault):
            fsutil.curator_write(self.vault, source, source.read_text(encoding="utf-8") + "\nCurator checkpoint.\n")
            pending = review.write_review_file(self.vault, "fixture", NOW.date(), [decision])
        assert pending is not None
        before = pending.read_bytes()
        expected = review.parse_review_file(pending)[0].payload["expected_hashes"]
        self.assertEqual(expected[self.vault.rel(source)], fsutil.file_hash(source))
        source.write_bytes(source.read_bytes() + b"\nLater human edit.\n")
        review.write_review_file(self.vault, "retry", NOW.date(), [decision])
        self.assertEqual(pending.read_bytes(), before)
        self.assertEqual(decision.payload["expected_hashes"], expected)

    def test_replacement_destination_creation_invalidates_approved_supersede(self):
        new_path = self.vault.path("knowledge/patterns/reviewed-replacement.md")
        decision = Decision(
            "SUPERSEDE", "Fixture replacement", target_ref=self.vault.rel(self.target)[:-3],
            payload={
                "target": self.vault.rel(self.target),
                "new_ref": self.vault.rel(new_path)[:-3],
                "new_content": self.target.read_text(encoding="utf-8"),
                "close_to": "2026-09-14",
            },
        )
        pending = review.write_review_file(self.vault, "fixture", NOW.date(), [decision])
        assert pending is not None
        expected = review.parse_review_file(pending)[0].payload["expected_hashes"]
        self.assertIn(self.vault.rel(new_path), expected)
        self.assertIsNone(expected[self.vault.rel(new_path)])
        pending.write_text(pending.read_text(encoding="utf-8").replace("[ ] approve", "[x] approve"), encoding="utf-8")
        new_path.write_text("An independently created note must survive.", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(CurationConflict):
            engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(pending.exists())

    def test_source_or_target_edits_refuse_stale_approval_without_overwriting(self):
        for field in ("source", "target"):
            with self.subTest(field=field):
                vault, holder = make_vault()
                try:
                    target = vault.path("knowledge/patterns/validation-order.md")
                    source = vault.path("00-inbox/2026-09-01-claude-code-dependents-first.md")
                    decision = Decision(
                        "REJECT", "Fixture decision", source_ref=vault.rel(source)[:-3],
                        target_ref=vault.rel(target)[:-3], payload={"target": vault.rel(target)},
                    )
                    pending = review.write_review_file(vault, "fixture", NOW.date(), [decision])
                    assert pending is not None
                    pending.write_text(pending.read_text(encoding="utf-8").replace("[ ] approve", "[x] approve"), encoding="utf-8")
                    changed = source if field == "source" else target
                    changed.write_bytes(changed.read_bytes() + b"\nExternal human edit.\n")
                    before = changed.read_bytes()
                    target_before = target.read_bytes()
                    with self.assertRaises(CurationConflict):
                        engine.run_compile(vault, now=NOW)
                    self.assertEqual(changed.read_bytes(), before)
                    self.assertEqual(target.read_bytes(), target_before)
                    self.assertTrue(pending.exists())
                    self.assertFalse(list(vault.path(config.REVIEW_ARCHIVE).glob("*.md")))
                finally:
                    holder.cleanup()

    def test_partial_merge_failure_rolls_back_and_can_be_retried(self):
        other = self.vault.path("knowledge/patterns/merge-other.md")
        other.write_bytes(self.target.read_bytes())
        pending = self.pending(kind="MERGE", other=other)
        before = self.snapshot()
        real_write = fsutil.curator_write

        def fail_second_write(vault, path, text, **kwargs):
            if path == other:
                raise OSError("fixture second merge write failed")
            return real_write(vault, path, text, **kwargs)

        with patch.object(fsutil, "curator_write", side_effect=fail_second_write):
            with self.assertRaisesRegex(VaultError, "review item failed"):
                engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(pending.exists())
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(other, self.vault).status, "superseded")
        self.assertFalse(pending.exists())

    def test_malformed_review_payload_stays_pending_without_application(self):
        pending = self.pending()
        text = pending.read_text(encoding="utf-8")
        pending.write_text(re.sub(r"<!-- mm:payload .*? -->", "<!-- mm:payload {broken} -->", text), encoding="utf-8")
        before = self.target.read_bytes()
        report = engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertTrue(pending.exists())
        self.assertTrue(any("payload" in warning for warning in report.warnings))
        self.assertFalse(review.is_fully_decided(review.parse_review_file(pending)))

    def test_unbound_legacy_approval_and_missing_hash_stay_pending(self):
        for hashes in (None, {}):
            with self.subTest(hashes=hashes):
                pending = self.pending()
                payload = review.parse_review_file(pending)[0].payload
                if hashes is None:
                    payload.pop("expected_hashes", None)
                else:
                    payload["expected_hashes"] = hashes
                self.replace_payload(pending, payload)
                before = self.target.read_bytes()
                report = engine.run_compile(self.vault, now=NOW)
                self.assertEqual(self.target.read_bytes(), before)
                self.assertTrue(pending.exists())
                self.assertTrue(any("expected_hashes" in warning for warning in report.warnings))

    def test_failed_publication_result_rolls_back_approved_review(self):
        pending = self.pending()
        before = self.snapshot()
        with patch.object(gitutil, "commit_paths", return_value=gitutil.CommitResult(
            False, None, "fixture rejected publication", failed=True,
        )):
            with self.assertRaises(CurationPublicationError):
                engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(pending.exists())

    def test_applied_factual_item_retires_without_waiting_for_attention_acknowledgement(self):
        pending = self.pending()
        review.write_review_file(self.vault, "attention", NOW.date(), [Decision(
            "HOLD", "Non-factual attention still needs acknowledgement",
            target_ref=self.vault.rel(self.target)[:-3],
            payload={
                "review_only": True, "review_key": "fixture-attention",
                "attention_kind": "knowledge", "subject_ref": self.vault.rel(self.target)[:-3],
            },
        )])
        before = self.snapshot()
        with patch.object(engine, "_promotion_pass", side_effect=RuntimeError("after partial review")):
            with self.assertRaisesRegex(RuntimeError, "after partial review"):
                engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.snapshot(), before)
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(self.target, self.vault).status, "rejected")
        self.assertTrue(pending.exists())
        self.assertTrue(all(item.kind == "HOLD" for item in review.parse_review_file(pending)))
        replay = engine.run_compile(self.vault, now=NOW)
        self.assertFalse(any(line.startswith("REJECT") for line in replay.log_lines))


if __name__ == "__main__":
    unittest.main()
