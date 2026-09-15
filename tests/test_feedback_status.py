import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from helpers import make_vault

from memory_mesh.cli import main
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.outcomes import collect_evidence, record_outcome
from memory_mesh.recall import recall
from memory_mesh.routing_diagnostics import create_gap_candidate


class FeedbackStatusTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def call(self, *args, expected=0):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--root", str(self.vault.root), *args])
        self.assertEqual(result, expected, output.getvalue())
        return output.getvalue()

    def snapshot(self):
        return {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for path in self.vault.root.rglob("*") if path.is_file()
        }

    def test_status_is_read_only_and_unchanged_data_has_stable_output(self):
        before = self.snapshot()
        first = self.call("status", "--json")
        self.assertEqual(first, self.call("status", "--json"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(json.loads(first)), {
            "schema_version", "vault", "recall", "inbox", "episodes", "knowledge",
            "skills", "routing", "curation", "warnings",
        })

    def test_status_separates_attempts_quality_sessions_and_non_factual_gaps(self):
        result = recall(self.vault, "copilot studio", session_id="status-session")
        assert result.attempt_id is not None
        record_outcome(
            self.vault, session_id="status-session", subject_type="recall",
            subject_id=result.attempt_id, outcome="off-target",
        )
        create_gap_candidate(self.vault, "Missing fixture knowledge", domain="mcp")
        report = json.loads(self.call("status", "--json"))
        self.assertEqual(report["recall"]["attempts"], 1)
        self.assertEqual(report["recall"]["unique_sessions"], 1)
        self.assertEqual(report["recall"]["quality"]["counts"]["off-target"], 1)
        self.assertEqual(report["recall"]["quality"]["counts"]["useful"], 0)
        self.assertEqual(report["inbox"]["gap_count"], 1)
        self.assertEqual(report["curation"]["mode"], "single-user")

    def test_skill_dependency_warnings_do_not_edit_skill_or_knowledge(self):
        note_path = self.vault.path("knowledge/patterns/validation-order.md")
        note = load_note(note_path, self.vault)
        note.meta["status"] = "stale"
        note_path.write_bytes(compose(note.meta, note.body).encode("utf-8"))
        self.vault.path("skills/status-demo.md").write_bytes(compose({
            "type": "skill", "title": "Status demo", "confidence": "high",
            "last_verified": datetime.now(timezone.utc).date().isoformat(),
            "depends_on": ["knowledge/patterns/validation-order"],
        }, "Use the dependency.").encode("utf-8"))
        before = self.snapshot()
        report = json.loads(self.call("status", "--json"))
        self.assertEqual(report["skills"]["potentially_stale"], 1)
        self.assertEqual(report["skills"]["needs_review"], 1)
        self.assertEqual(report["skills"]["details"][0]["confidence"], "high")
        explained = json.loads(self.call("explain", "skills/status-demo", "--subject", "skill"))
        self.assertTrue(explained["evaluation"]["needs_review"])
        self.assertTrue(explained["evaluation"]["potentially_stale"])
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_telemetry_is_visible_as_a_warning_not_silently_lost(self):
        path = self.vault.path("episodes/_recalls/corrupt.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid", encoding="utf-8")
        report = json.loads(self.call("status", "--json"))
        self.assertTrue(any("invalid or conflicting recall attempt" in item for item in report["warnings"]))
        self.assertEqual(report["recall"]["attempts"], 0)

    def test_invalid_diagnostic_window_fails_explicitly(self):
        self.assertIn("window days", self.call("status", "--days", "0", expected=1))

    def test_legacy_context_references_are_not_converted_to_knowledge_votes(self):
        before_ids = {event.event_id for event in collect_evidence(self.vault)}
        path = self.vault.path("episodes/legacy-context.md")
        path.write_bytes(compose({
            "type": "episode", "tool": "cli", "captured": datetime.now(timezone.utc).isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "summarised",
        }, (
            "## Knowledge used\n"
            "- [[projects/copilot-studio-skills]] not-applicable: working context only.\n"
            "- [[knowledge/_index/coding-agents]] held: routing context was available.\n"
            "- [[validation-order]] held: a knowledge rule was exercised.\n"
        )).encode("utf-8"))
        original = path.read_bytes()
        added = [event for event in collect_evidence(self.vault) if event.event_id not in before_ids]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].subject_id, "knowledge/patterns/validation-order")
        self.call("status", "--json")
        self.assertEqual(path.read_bytes(), original)

    def test_unattributed_legacy_feedback_is_reported_and_never_counted(self):
        before = {event.event_id for event in collect_evidence(self.vault)}
        path = self.vault.path("episodes/unattributed.md")
        path.write_bytes(compose({
            "type": "episode", "tool": "cli", "captured": datetime.now(timezone.utc).isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "summarised",
        }, "## Knowledge used\n- `held` - Session procedure worked, without a knowledge reference.\n").encode("utf-8"))
        original = path.read_bytes()
        report = json.loads(self.call("status", "--json"))
        self.assertTrue(any("unattributed legacy feedback excluded" in item for item in report["warnings"]))
        diagnostics = []
        self.assertEqual({event.event_id for event in collect_evidence(self.vault, diagnostics=diagnostics)}, before)
        self.assertEqual(path.read_bytes(), original)

    def test_knowledge_explain_exposes_shared_evidence_without_mutation(self):
        before = self.snapshot()
        explained = json.loads(self.call("explain", "validation-order"))
        self.assertEqual(explained["subject_id"], "knowledge/patterns/validation-order")
        self.assertIn("weighted_held", explained["evaluation"]["evidence"])
        self.assertIn("reasons", explained["evaluation"])
        self.assertIn("canonical_confidence", explained)
        self.assertEqual(self.snapshot(), before)

    def test_candidate_and_routing_explain_report_attention_not_truth(self):
        from memory_mesh.capture import learn

        candidate = learn(self.vault, "A diagnostic candidate fixture.", signal="high")
        explained = json.loads(self.call("explain", self.vault.rel(candidate.path), "--subject", "candidate"))
        self.assertEqual(explained["rank"], 1)
        self.assertEqual(explained["evaluation"]["signal"], "high")
        self.assertIn("not truth", explained["authority"])
        routing = json.loads(self.call("explain", "mcp stdio transport", "--subject", "routing"))
        self.assertIn("mcp", routing["selected"])
        self.assertTrue(routing["matches"][0]["terms"])

    def test_usage_explanation_exposes_observed_counts_without_confidence_votes(self):
        self.call("recall", "copilot studio validation", "--session", "usage-explain")
        result = json.loads(self.call("explain", "validation-order", "--usage"))
        self.assertGreaterEqual(result["usage"]["last_30_days"], 1)
        self.assertGreaterEqual(result["usage"]["last_90_days"], 1)
        self.assertIsNotNone(result["usage"]["last_recalled"])
        self.call("explain", "mcp", "--subject", "routing", "--usage", expected=1)


if __name__ == "__main__":
    unittest.main()
