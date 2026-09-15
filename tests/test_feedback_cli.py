import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import cli, config, outcomes
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.recall import load_session_state
from memory_mesh.routing_diagnostics import read_attempt, read_attempts, recall_summary, recall_quality_summary


class FeedbackCliTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def call(self, *args, expected=0):
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["--root", str(self.vault.root), *args])
        self.assertEqual(result, expected, output.getvalue())
        return output.getvalue()

    def end(self, session):
        text = self.call("session-end", "--session", session, "--tool", "cli", "--slug", session)
        match = re.search(r"episode stub: ([^\r\n]+?\.md)", text)
        self.assertIsNotNone(match, text)
        self.call("episode", "finish", match.group(1))
        return load_note(self.vault.path(match.group(1)), self.vault)

    def empty_index(self):
        self.vault.path("knowledge/_index/mcp.md").write_text(compose(
            {"type": "index", "domain": "mcp", "updated": "2026-09-14", "links": 0},
            "# MCP\n\n## Read first\n\n## Known failures\n\n## Current workarounds\n\n"
            "## Active project\n\n## Recently verified (30 days)\n\n## Recently changed\n",
        ), encoding="utf-8")

    def test_signal_and_source_episode_work_in_structured_json(self):
        payload = {
            "title": "CLI signal fixture",
            "observations": [
                {"kind": "procedure", "text": "Validate the input before capture."},
                {"kind": "evidence", "text": "The fixture rejected an invalid input."},
            ],
            "domain": "coding-agents", "signal": "high",
            "source_episode": "episodes/2026-08-14-claude-code-api-change",
        }
        text = self.call("learn", json.dumps(payload), "--structured")
        path = text.split("captured: ", 1)[1].splitlines()[0]
        note = load_note(self.vault.path(path), self.vault)
        self.assertEqual(note.meta["signal"], "high")
        self.assertEqual(note.meta["source_episode"], payload["source_episode"])
        self.assertNotIn("confidence", note.meta)

    def test_duplicate_signal_upgrade_preserves_identity_and_never_downgrades(self):
        text = "Prefer deterministic input checks (cli, 1.0)"
        first = self.call("learn", text)
        path = first.split("captured: ", 1)[1].strip()
        self.assertIn("updated candidate attention", self.call("learn", text, "--signal", "high"))
        self.call("learn", text, "--signal", "low")
        self.assertEqual(load_note(self.vault.path(path), self.vault).meta["signal"], "high")

    def test_conflicting_structured_options_fail_explicitly(self):
        payload = {"signal": "low"}
        self.assertIn("conflicts", self.call("learn", json.dumps(payload), "--structured", "--signal", "high", expected=1))
        self.call("learn", "", expected=1)

    def test_knowledge_outcome_only_session_finishes_as_partial(self):
        self.call("feedback", "validation-order", "#held", "--session", "outcome-only", "--event-id", "held-one")
        note = self.end("outcome-only")
        self.assertEqual(note.status, "summarised")
        self.assertEqual(note.meta["completeness"], "partial")
        self.assertIn("outcome-event: held-one", note.body)
        captured = [event for event in outcomes.collect_evidence(self.vault) if event.event_id == "held-one"]
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].subject_id, "knowledge/patterns/validation-order")
        self.assertEqual(load_session_state(self.vault, "outcome-only"), {})

    def test_empty_recall_survives_session_end_with_factual_prefill(self):
        self.empty_index()
        result = json.loads(self.call("recall", "mcp stdio transport", "--session", "empty", "--json"))
        self.assertEqual(result["notes"], [])
        note = self.end("empty")
        self.assertEqual(note.status, "summarised")
        self.assertEqual(note.meta["recall_attempts"], [result["attempt_id"]])
        self.assertIn("recall with 0 knowledge references", note.body)
        self.assertNotIn("## Goal\nTest passed", note.body)

    def test_gap_only_session_is_retained_without_a_factual_learning(self):
        self.call("gap", "How a transport closes", "--domain", "mcp", "--session", "gap-only")
        note = self.end("gap-only")
        self.assertIn("Referenced research gap", note.body)
        self.assertIn("no factual claim", note.body)
        self.assertEqual(
            [event for event in outcomes.collect_evidence(self.vault) if event.session_id == "gap-only"],
            [],
        )

    def test_capture_gap_uses_recorded_result_and_no_log_is_strict(self):
        self.empty_index()
        payload = json.loads(self.call(
            "recall", "mcp stdio transport", "--session", "gap-recall", "--capture-gap", "--json",
        ))
        self.assertEqual(load_note(self.vault.path(payload["gap_candidate"]), self.vault).type, "gap")
        before = sorted(str(path.relative_to(self.vault.root)) for path in self.vault.root.rglob("*"))
        self.call("recall", "mcp", "--no-log", "--capture-gap", expected=1)
        self.call("recall", "mcp", "--session", "no-log", "--no-log")
        self.assertEqual(sorted(str(path.relative_to(self.vault.root)) for path in self.vault.root.rglob("*")), before)

    def test_recall_quality_uses_exact_session_attempt_and_no_scan(self):
        payload = json.loads(self.call("recall", "copilot studio", "--session", "quality", "--json"))
        with patch.object(Path, "glob", side_effect=AssertionError("unexpected scan")):
            self.call("recall-quality", "off-target", "--session", "quality")
            self.assertEqual(read_attempt(self.vault, payload["attempt_id"]).session_id, "quality")
        event = outcomes.read_events(self.vault, session_id="quality")[0]
        self.assertEqual(event.outcome, "off-target")
        self.call("recall-quality", "useful", "--session", "wrong", "--attempt", payload["attempt_id"], expected=1)

    def test_checkpoint_prefill_is_not_replayed_twice(self):
        self.call("episode", "checkpoint", "--session", "checkpoint", "--text", "Observed the fixture output.")
        note = self.end("checkpoint")
        self.assertEqual(note.body.count("Observed the fixture output."), 1)

    def test_untouched_session_still_skips_without_creating_an_episode(self):
        before = sorted(self.vault.path(config.EPISODES).glob("*.md"))
        self.assertIn("skipping", self.call("session-end", "--session", "untouched"))
        self.assertEqual(sorted(self.vault.path(config.EPISODES).glob("*.md")), before)

    def test_corrupt_attempts_are_not_silently_reported_as_no_recall(self):
        path = self.vault.path(config.RECALL_ATTEMPTS) / "corrupt.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("broken", encoding="utf-8")
        from memory_mesh.config import VaultError

        with self.assertRaises(VaultError):
            read_attempts(self.vault)
        diagnostics = []
        self.assertEqual(read_attempts(self.vault, diagnostics=diagnostics), [])
        self.assertTrue(diagnostics)

    def test_metrics_distinguish_attempts_served_notes_and_sessions_without_rescanning(self):
        for attempt_id in ("trial-one", "trial-two", "trial-one"):
            self.call(
                "recall", "copilot studio validation", "--session", "metrics",
                "--attempt-id", attempt_id,
            )
        attempts = read_attempts(self.vault, session_id="metrics")
        with patch.object(Path, "glob", side_effect=AssertionError("unexpected telemetry rescan")):
            summary = recall_summary(self.vault, attempts=attempts)
            quality = recall_quality_summary(self.vault, attempts=attempts, events=[])
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["unique_sessions"], 1)
        self.assertEqual(summary["served_notes"], sum(attempt.usable_count for attempt in attempts))
        self.assertEqual(quality["counts"]["useful"], 0)

    def test_recovery_inspection_is_read_only_and_acknowledgement_is_explicit(self):
        from memory_mesh import fsutil
        from memory_mesh.curator.transaction import CurationConflict, curation_transaction

        target = self.vault.path("knowledge/patterns/validation-order.md")
        with self.assertRaises(CurationConflict):
            with curation_transaction(self.vault):
                target.write_bytes(target.read_bytes() + b"\nmanual edit\n")
                fsutil.curator_write(self.vault, target, "conflicting proposal")
        before = {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for path in self.vault.root.rglob("*") if path.is_file()
        }
        rows = json.loads(self.call("curation-recover", "--inspect"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "conflict")
        self.assertEqual(before, {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for path in self.vault.root.rglob("*") if path.is_file()
        })
        current = target.read_bytes()
        self.call("curation-recover", "--acknowledge", rows[0]["transaction_id"])
        self.assertEqual(target.read_bytes(), current)
        self.assertEqual(json.loads(self.call("curation-recover", "--inspect")), [])

    def test_recovery_confirmation_is_not_silently_ignored_by_inspection(self):
        self.call("curation-recover", "--inspect", "--confirm-git-stopped", expected=1)


if __name__ == "__main__":
    unittest.main()
