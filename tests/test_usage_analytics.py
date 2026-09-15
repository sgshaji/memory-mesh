import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import config, frontmatter
from memory_mesh.curator import analytics
from memory_mesh.routing_diagnostics import RecallAttempt


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class TestUsageAnalytics(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.ref = "knowledge/patterns/usage-observation"
        self.note(self.ref)

    def note(self, ref, **meta):
        path = self.vault.path(ref + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.compose({
            "type": "pattern", "title": ref.rsplit("/", 1)[-1], "status": "validated",
            "trust": "first-party", "domains": ["coding-agents"], "confidence": "high",
            "last_verified": "2026-09-14", "first_observed": "2026-01-01",
            "evidence": ["episodes/2026-08-14-claude-code-api-change"], **meta,
        }, "## Observations\n- [procedure] Inspect the recorded evidence before a change."), encoding="utf-8")
        return path

    def attempt(self, name, *, ref=None, days=0, fingerprint="f" * 64, domain="coding-agents"):
        return RecallAttempt(
            attempt_id=name, timestamp=(NOW - timedelta(days=days)).isoformat(),
            session_id="session-" + name, task_text="Inspect a recorded observation",
            task_fingerprint=fingerprint, route="coding-agents", domains=("coding-agents",),
            note_refs=(ref or self.ref,), note_domains=(domain,), note_revisions=("a" * 64,),
            total_count=1, usable_count=1, target_minimum=1, potential_gap=False, tool="test-host",
        )

    def row(self, attempt):
        return "\t".join((
            attempt.timestamp, attempt.tool, attempt.note_domains[0],
            attempt.note_refs[0].rsplit("/", 1)[-1],
        ))

    def log(self, *rows):
        self.vault.path(config.RECALL_LOG).write_text("\n".join(rows) + "\n", encoding="utf-8")

    def test_exact_mirror_rows_are_subtracted_with_multiplicity(self):
        first = self.attempt("first")
        second = self.attempt("second")
        self.log(self.row(first), self.row(first), self.row(first))
        result = analytics.recall_usage(self.vault, now=NOW, attempts=[first, first, second])
        usage = result.by_ref[self.ref]
        self.assertEqual(result.mirrored_rows, 2)
        self.assertEqual(usage.total, 3)
        self.assertEqual(usage.attempt_count, 2)
        self.assertEqual(usage.legacy_count, 1)
        self.assertEqual(usage.last_30_days, 3)

    def test_windows_are_inclusive_and_last_recalled_is_derived(self):
        attempts = [self.attempt(f"day-{day}", days=day) for day in (0, 30, 31, 90, 91)]
        self.log(*(self.row(attempt) for attempt in attempts))
        usage = analytics.recall_usage(self.vault, now=NOW, attempts=attempts).by_ref[self.ref]
        self.assertEqual(usage.total, 5)
        self.assertEqual(usage.last_30_days, 2)
        self.assertEqual(usage.last_90_days, 4)
        self.assertEqual(usage.last_recalled, NOW.isoformat())

    def test_early_attempt_fingerprint_stays_unknown(self):
        early = self.attempt("early", fingerprint=None, domain="_general")
        self.log(self.row(early))
        result = analytics.recall_usage(self.vault, now=NOW, attempts=[early])
        usage = result.by_ref[self.ref]
        self.assertEqual(usage.total, 1)
        self.assertEqual(usage.task_fingerprints, (None,))
        self.assertEqual(usage.unknown_task_count, 1)
        self.assertIsNone(usage.as_dict()["task_fingerprints"][0])
        self.assertEqual(result.mirrored_rows, 1)

    def test_legacy_rows_do_not_require_attempt_records(self):
        row = self.row(self.attempt("legacy", days=45))
        self.log(row, row)
        usage = analytics.recall_usage(self.vault, now=NOW, attempts=[]).by_ref[self.ref]
        self.assertEqual(usage.total, 2)
        self.assertEqual(usage.legacy_count, 2)
        self.assertEqual(usage.last_30_days, 0)
        self.assertEqual(usage.last_90_days, 2)
        self.assertEqual(usage.task_fingerprints, ())

    def test_ambiguous_legacy_basename_is_not_assigned_to_both_notes(self):
        other = "knowledge/tools/usage-observation"
        self.note(other, type="tool-behaviour")
        attempt = self.attempt("qualified", ref=other, domain="_general")
        self.log(self.row(attempt), self.row(attempt))
        result = analytics.recall_usage(self.vault, now=NOW, attempts=[attempt])
        self.assertEqual(result.by_ref[other].total, 1)
        self.assertEqual(result.by_ref.get(self.ref).total if self.ref in result.by_ref else 0, 0)
        self.assertTrue(any("ambiguous" in warning for warning in result.warnings))

    def test_malformed_and_future_rows_are_diagnosed_without_negative_ages(self):
        future = self.attempt("future", days=-2)
        self.log(self.row(future), "invalid\trow", "nonsense\ttest-host\tcoding-agents\tusage-observation")
        result = analytics.recall_usage(self.vault, now=NOW, attempts=[future])
        self.assertEqual(sum(item.total for item in result.notes), 0)
        self.assertTrue(any("future" in warning for warning in result.warnings))
        self.assertTrue(any("timestamp" in warning for warning in result.warnings))
        self.assertGreaterEqual(result.ignored_rows, 2)

    def test_usage_and_suggestions_are_read_only_and_json_serializable(self):
        attempts = [self.attempt(f"serve-{index}") for index in range(5)]
        self.log(*(self.row(attempt) for attempt in attempts))
        before = {path: path.read_bytes() for path in self.vault.root.rglob("*.md")}
        usage = analytics.recall_usage(self.vault, now=NOW, attempts=attempts)
        suggestions = analytics.index_suggestions(self.vault, now=NOW, usage=usage)
        promotion = [item for item in suggestions if item.subject_id == self.ref and item.action == "promote"]
        self.assertEqual(len(promotion), 1)
        self.assertTrue(any("5" in reason and "30" in reason for reason in promotion[0].reasons))
        self.assertEqual(json.loads(json.dumps(usage.as_dict()))["mirrored_rows"], 5)
        self.assertEqual(promotion[0].as_dict()["domain"], "coding-agents")
        self.assertEqual(before, {path: path.read_bytes() for path in self.vault.root.rglob("*.md")})

    def test_candidate_and_third_party_usage_never_justify_promotion(self):
        self.note(self.ref, status="candidate")
        other = "knowledge/patterns/third-party-usage"
        self.note(other, trust="third-party")
        attempts = [self.attempt(f"candidate-{index}") for index in range(6)]
        attempts += [self.attempt(f"third-{index}", ref=other) for index in range(6)]
        usage = analytics.recall_usage(self.vault, now=NOW, attempts=attempts)
        self.assertFalse(any(
            item.subject_id in (self.ref, other)
            for item in analytics.index_suggestions(self.vault, now=NOW, usage=usage)
        ))

    def test_demotion_requires_known_history_not_an_assumption_of_nonuse(self):
        index = self.vault.path("knowledge/_index/coding-agents.md")
        text = index.read_text(encoding="utf-8").replace("## Read first", f"## Read first\n- [[{self.ref}]]")
        index.write_text(text, encoding="utf-8")
        empty = analytics.recall_usage(self.vault, now=NOW, attempts=[])
        self.assertFalse(any(item.subject_id == self.ref for item in analytics.index_suggestions(
            self.vault, now=NOW, usage=empty,
        )))
        old = analytics.recall_usage(self.vault, now=NOW, attempts=[self.attempt("old", days=181)])
        suggestions = analytics.index_suggestions(self.vault, now=NOW, usage=old)
        demotion = [item for item in suggestions if item.subject_id == self.ref]
        self.assertEqual([item.action for item in demotion], ["demote"])
        self.assertTrue(any("180" in reason for reason in demotion[0].reasons))

    def test_preloaded_inventory_preserves_results_without_knowledge_rescans(self):
        notes = analytics._read_notes(self.vault, config.KNOWLEDGE, [])
        assessments = analytics.assess_all_knowledge(self.vault, now=NOW, notes=notes, events=[])
        attempts = [self.attempt(f"cached-{index}") for index in range(5)]
        self.log(*(self.row(attempt) for attempt in attempts))
        expected_usage = analytics.recall_usage(self.vault, now=NOW, attempts=attempts)
        expected_suggestions = analytics.index_suggestions(
            self.vault, now=NOW, usage=expected_usage, assessments=assessments,
        )
        read = analytics._read_notes

        def reject_knowledge_scan(vault, folder, diagnostics):
            if folder == config.KNOWLEDGE:
                self.fail("preloaded knowledge inventory was scanned again")
            return read(vault, folder, diagnostics)

        with patch.object(analytics, "_read_notes", side_effect=reject_knowledge_scan):
            usage = analytics.recall_usage(self.vault, now=NOW, attempts=attempts, notes=iter(notes))
            suggestions = analytics.index_suggestions(
                self.vault, now=NOW, usage=usage, assessments=assessments, notes=iter(notes),
            )
            from_legacy_log = analytics.index_suggestions(
                self.vault, now=NOW, assessments=assessments, notes=iter(notes),
            )
        self.assertEqual(usage, expected_usage)
        self.assertEqual(suggestions, expected_suggestions)
        self.assertTrue(any(item.subject_id == self.ref for item in from_legacy_log))

    def test_empty_preloaded_inventory_does_not_fall_back_to_disk(self):
        assessments = analytics.assess_all_knowledge(self.vault, now=NOW, events=[])
        with patch.object(analytics, "_read_notes", return_value=[]) as read:
            usage = analytics.recall_usage(self.vault, now=NOW, attempts=[], notes=[])
            suggestions = analytics.index_suggestions(
                self.vault, now=NOW, usage=usage, assessments=assessments, notes=[],
            )
        self.assertFalse(any(call.args[1] == config.KNOWLEDGE for call in read.call_args_list))
        self.assertEqual(suggestions, [])


if __name__ == "__main__":
    unittest.main()
