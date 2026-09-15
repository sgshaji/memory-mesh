import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import config, recall, router
from memory_mesh.config import VaultError
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.outcome_types import OutcomeEvent
from memory_mesh.routing_diagnostics import (
    create_gap_candidate, parse_attempt_note, read_attempts,
    recall_quality_summary, recall_summary, routing_suggestions,
)
from memory_mesh.schema import validate_note

NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


class TestRoutingDiagnostics(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)

    def snapshot(self, directory=""):
        return {
            self.vault.rel(path): path.read_bytes()
            for path in self.vault.path(directory).rglob("*") if path.is_file()
        }

    def settings(self, **fields):
        self.vault.path(config.SETTINGS_FILE).write_text(
            compose({"type": "meta", "version": 1, **fields}, ""), encoding="utf-8",
        )

    def index(self, refs=(), domain="mcp"):
        self.vault.path(f"knowledge/_index/{domain}.md").write_text(compose({
            "type": "index", "domain": domain, "updated": "2026-09-02", "links": len(refs),
        }, "# Test index\n\n## Read first\n" + "\n".join(f"- [[{ref}]]" for ref in refs)),
            encoding="utf-8")

    def episode(self, body, **meta):
        path = self.vault.path("episodes/routing-session.md")
        path.write_text(compose({
            "type": "episode", "tool": "cli", "captured": NOW.isoformat(),
            "domains": ["coding-agents"], "status": "summarised",
            "trust": "first-party", "sensitivity": "checked", **meta,
        }, body), encoding="utf-8")
        return load_note(path, self.vault)

    def test_vocabulary_merges_without_using_scope_or_rewriting_registry(self):
        before = self.vault.path(config.ROUTER).read_bytes()
        self.settings(routing={"copilot-studio": {
            "keywords": ["pva"], "aliases": ["declarative orchestration"],
            "concepts": ["connector authentication"],
        }})
        domains = router.load_domains(self.vault)
        for query in ("mcs", "pva", "declarative-orchestration", "connector authentication"):
            self.assertEqual(router.match(query, domains), ["copilot-studio"])
        self.assertEqual(router.match("publishing", domains), [])
        self.assertEqual(router.match("mcsunrelated", domains), [])
        self.assertEqual(before, self.vault.path(config.ROUTER).read_bytes())

    def test_duplicate_normalized_terms_do_not_inflate_scores(self):
        original = router.match_evidence("copilot studio", router.load_domains(self.vault))
        self.settings(routing={"copilot-studio": {
            "keywords": ["copilot studio"], "aliases": ["copilot-studio"],
            "concepts": ["COPILOT STUDIO"],
        }})
        self.assertEqual(
            router.match_evidence("copilot studio", router.load_domains(self.vault)), original,
        )

    def test_unknown_overlay_and_malformed_registry_fail_without_rewrite(self):
        self.settings(routing={"not-registered": {"aliases": ["anything"]}})
        before = self.snapshot()
        with self.assertRaisesRegex(VaultError, "not declared"):
            router.load_domains(self.vault)
        self.assertEqual(before, self.snapshot())
        self.settings()
        path = self.vault.path(config.ROUTER)
        for row in ("| ../escape | invalid | word |", "| valid | incomplete |",
                    "| mcp | duplicate | mcp |"):
            original = path.read_text(encoding="utf-8")
            with self.subTest(row=row):
                path.write_text(original + "\n" + row + "\n", encoding="utf-8")
                with self.assertRaises(VaultError):
                    router.load_domains(self.vault)
            path.write_text(original, encoding="utf-8")

    def test_missing_registry_keeps_legacy_unclassified_fallback(self):
        self.vault.path(config.ROUTER).unlink()
        result = recall.recall(self.vault, "unmatched", session_id="fallback", now=NOW)
        self.assertTrue(result.unclassified)
        self.assertEqual(result.domains, ["unclassified"])
        attempt = read_attempts(self.vault)[0]
        self.assertEqual(attempt.domains, ("unclassified",))
        self.assertIn("_general", attempt.note_domains)
        self.assertEqual(attempt.usable_count, len(result.notes))
        self.settings(routing={"mcp": {"keywords": ["mcp"]}})
        with self.assertRaises(VaultError):
            router.load_domains(self.vault)

    def test_empty_and_weak_attempts_use_configured_target_without_fake_tsv_rows(self):
        self.settings(feedback={"recall_target_minimum": 3})
        self.index()
        result = recall.recall(self.vault, "mcp stdio", session_id="empty", now=NOW)
        attempt = read_attempts(self.vault, session_id="empty")[0]
        self.assertEqual(attempt.attempt_id, result.attempt_id)
        self.assertEqual((attempt.total_count, attempt.usable_count, attempt.target_minimum), (0, 0, 3))
        self.assertEqual(attempt.domains, ("mcp",))
        self.assertTrue(attempt.potential_gap)
        self.assertFalse(self.vault.path(config.RECALL_LOG).exists())
        self.assertTrue(recall.load_session_state(self.vault, "empty")["recalled"])
        self.index(("validation-order",))
        recall.recall(self.vault, "mcp stdio", session_id="weak", now=NOW)
        weak = read_attempts(self.vault, session_id="weak")[0]
        self.assertEqual(weak.note_refs, ("knowledge/patterns/validation-order",))
        self.assertEqual(weak.usable_count, 1)
        self.assertTrue(weak.potential_gap)
        for line in self.vault.path(config.RECALL_LOG).read_text(encoding="utf-8").splitlines():
            self.assertEqual(len(line.split("\t")), 4)
        summary = recall_summary(self.vault, now=NOW)
        self.assertEqual(summary["empty_recalls"], 1)
        self.assertEqual(summary["weak_recalls"], 1)
        self.assertEqual(summary["by_route"]["mcp"]["potential_gaps"], 2)

    def test_unusable_links_are_counted_but_not_fabricated_as_served(self):
        self.index(("validation-order", "missing-note"))
        path = self.vault.path("knowledge/patterns/validation-order.md")
        note = load_note(path, self.vault)
        note.meta["applies_to"] = {"to": "2026-08"}
        path.write_text(compose(note.meta, note.body), encoding="utf-8")
        recall.recall(self.vault, "mcp", session_id="no-usable", now=NOW)
        attempt = read_attempts(self.vault)[0]
        self.assertEqual((attempt.total_count, attempt.usable_count), (2, 0))
        self.assertEqual(attempt.note_refs, ())
        self.assertTrue(attempt.potential_gap)
        self.assertFalse(self.vault.path(config.RECALL_LOG).exists())

    def test_malformed_and_ambiguous_index_refs_are_reported_without_fallback(self):
        source = self.vault.path("knowledge/patterns/validation-order.md")
        duplicate = self.vault.path("knowledge/tools/validation-order.md")
        duplicate.write_bytes(source.read_bytes())
        self.index(("../outside", "validation-order"))
        result = recall.recall(self.vault, "mcp", log=False, now=NOW)
        self.assertEqual(result.notes, [])
        self.assertEqual(result.skipped, [
            "../outside (invalid reference)", "validation-order (invalid reference)",
        ])

    def test_qualified_missing_ref_never_resolves_an_unrelated_basename(self):
        self.index(("knowledge/patterns/missing/validation-order",))
        result = recall.recall(self.vault, "mcp", log=False, now=NOW)
        self.assertEqual(result.notes, [])
        self.assertEqual(
            result.skipped, ["knowledge/patterns/missing/validation-order (unresolved)"],
        )

    def test_windows_qualified_index_ref_is_resolved_without_guessing(self):
        self.index(("knowledge\\patterns\\validation-order",))
        result = recall.recall(self.vault, "mcp", log=False, now=NOW)
        self.assertEqual(len(result.notes), 1)
        self.assertEqual(result.notes[0].path, self.vault.path("knowledge/patterns/validation-order.md"))

    def test_nested_index_notes_require_qualified_refs_without_recursive_discovery(self):
        nested = self.vault.path("knowledge/patterns/nested/nested-only.md")
        nested.parent.mkdir()
        nested.write_bytes(self.vault.path("knowledge/patterns/validation-order.md").read_bytes())
        with patch("os.walk", side_effect=AssertionError("broad scan")):
            self.index(("nested-only",))
            bare = recall.recall(self.vault, "mcp", log=False, now=NOW)
            self.assertEqual(bare.notes, [])
            self.assertEqual(bare.skipped, ["nested-only (unresolved)"])
            self.index(("knowledge/patterns/nested/nested-only",))
            qualified = recall.recall(self.vault, "mcp", log=False, now=NOW)
            self.assertEqual([note.path for note in qualified.notes], [nested])

    def test_strict_recall_reports_invalid_refs_without_relaxing_admission(self):
        from memory_mesh.experience import create_task, set_mode

        set_mode(self.vault, "strict")
        create_task(
            self.vault, task_id="invalid-refs", event_id="start", project="test-project",
            tool="python", version="3.13", goal="mcp transport checks",
            checks={"check": "The transport behavior is observed."},
        )
        self.index(("../outside", "validation-order"))
        result = recall.recall(self.vault, "mcp", task_id="invalid-refs", log=False, now=NOW)
        self.assertEqual(result.notes, [])
        self.assertEqual(result.reason_counts["invalid_note_reference"], 1)
        self.assertEqual(result.reason_counts["legacy_note"], 1)

    def test_retry_deduplicates_attempt_and_tsv_but_explicit_trial_is_distinct(self):
        first = recall.recall(self.vault, "copilot studio", session_id="retry", now=NOW)
        before = self.snapshot()
        again = recall.recall(
            self.vault, "copilot  studio", session_id="retry", now=NOW + timedelta(seconds=10),
        )
        self.assertEqual(first.attempt_id, again.attempt_id)
        self.assertEqual(before, self.snapshot())
        recall.recall(self.vault, "copilot studio", session_id="retry", attempt_id="trial-2", now=NOW)
        self.assertEqual(len(read_attempts(self.vault)), 2)
        with self.assertRaisesRegex(VaultError, "different intent"):
            recall.recall(self.vault, "mcp", session_id="retry", attempt_id="trial-2", now=NOW)
        self.assertEqual(len(read_attempts(self.vault)), 2)

    def test_concurrent_retries_publish_one_complete_attempt_and_one_tsv_copy(self):
        def attempt(_):
            return recall.recall(self.vault, "copilot studio", session_id="concurrent", now=NOW)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(attempt, range(8)))
        self.assertEqual(len({item.attempt_id for item in results}), 1)
        self.assertEqual(len(read_attempts(self.vault)), 1)
        rows = self.vault.path(config.RECALL_LOG).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), len(results[0].notes))
        self.assertEqual(list(self.vault.path(config.RECALL_ATTEMPTS).glob(".mm-*")), [])

    def test_interrupted_publication_leaves_no_partial_journal_or_legacy_rows(self):
        self.index()
        with patch("memory_mesh.routing_diagnostics.os.link", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                recall.recall(self.vault, "mcp", session_id="interrupted", now=NOW)
        self.assertEqual(read_attempts(self.vault), [])
        self.assertEqual(list(self.vault.path(config.RECALL_ATTEMPTS).glob(".mm-*")), [])
        self.assertFalse(self.vault.path(config.RECALL_LOG).exists())
        recall.recall(self.vault, "mcp", session_id="interrupted", now=NOW)
        self.assertEqual(len(read_attempts(self.vault)), 1)

    def test_standalone_calls_are_independent_and_explicit_standalone_ids_replay(self):
        for _ in range(2):
            recall.recall(self.vault, "mcp", now=NOW)
        self.assertEqual(len(read_attempts(self.vault)), 2)
        for _ in range(2):
            recall.recall(self.vault, "mcp", now=NOW, attempt_id="standalone-trial")
        self.assertEqual(len(read_attempts(self.vault)), 3)

    def test_truncated_task_display_does_not_collapse_distinct_intents(self):
        self.index()
        prefix = "mcp " + "same task prefix " * 40
        for suffix in ("first work item", "second work item"):
            recall.recall(self.vault, prefix + suffix, session_id="long-tasks", now=NOW)
        attempts = read_attempts(self.vault)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].task_text, attempts[1].task_text)
        self.assertNotEqual(attempts[0].task_fingerprint, attempts[1].task_fingerprint)

    def test_no_log_with_session_has_no_filesystem_side_effects(self):
        before = self.snapshot()
        result = recall.recall(self.vault, "copilot studio", session_id="preview", log=False, now=NOW)
        self.assertTrue(result.notes)
        self.assertIsNone(result.attempt_id)
        self.assertEqual(before, self.snapshot())

    def test_attempt_writes_do_not_scan_vault_or_existing_telemetry(self):
        with patch("memory_mesh.experience.get_mode", return_value="legacy"), \
                patch.object(Path, "glob", side_effect=AssertionError("broad scan")), \
                patch.object(Path, "rglob", side_effect=AssertionError("broad scan")), \
                patch("os.walk", side_effect=AssertionError("broad scan")):
            result = recall.recall(self.vault, "copilot studio", session_id="bounded", now=NOW)
        self.assertTrue(result.notes)
        self.assertEqual(len(read_attempts(self.vault)), 1)

    def test_redaction_precedes_bounding_and_persistence(self):
        self.vault.path(config.REDACT_FILE).write_text("literal:SampleCustomer\n", encoding="utf-8")
        sensitive = "SampleCustomer api_key=" + "A" * 32
        task = "mcp " + sensitive + " https://tenant.sharepoint.com/private " + "x" * 800
        self.index()
        recall.recall(self.vault, task, session_id="privacy", now=NOW)
        attempt = read_attempts(self.vault)[0]
        self.assertLessEqual(len(attempt.task_text), 500)
        self.assertEqual(attempt.sensitivity, "redacted")
        text = next(self.vault.path(config.RECALL_ATTEMPTS).glob("*.md")).read_text(encoding="utf-8")
        self.assertNotIn("SampleCustomer", text)
        self.assertNotIn("A" * 32, text)
        self.assertNotIn("sharepoint.com", text)
        self.assertIn("[redacted-secret]", text)

    def test_shared_parser_rejects_malformed_counts_version_and_truth_fields(self):
        recall.recall(self.vault, "copilot studio", session_id="shape", now=NOW)
        path = next(self.vault.path(config.RECALL_ATTEMPTS).glob("*.md"))
        note = load_note(path, self.vault)
        attempt = parse_attempt_note(note)
        self.assertEqual(attempt.usable_count, len(attempt.note_refs))
        for changed in (
            {"schema_version": 99}, {"usable_count": True}, {"route": "wrong"},
            {"potential_gap": "true"}, {"status": "validated"}, {"note_refs": "../outside"},
        ):
            with self.subTest(changed=changed):
                original = dict(note.meta)
                note.meta.update(changed)
                with self.assertRaises(VaultError):
                    parse_attempt_note(note)
                note.meta = original

    def test_duplicate_and_malformed_attempt_files_are_observable_and_not_double_counted(self):
        self.index()
        recall.recall(self.vault, "mcp", session_id="copies", now=NOW)
        path = next(self.vault.path(config.RECALL_ATTEMPTS).glob("*.md"))
        self.vault.path(config.RECALL_ATTEMPTS + "/copy.md").write_bytes(path.read_bytes())
        self.vault.path(config.RECALL_ATTEMPTS + "/partial.md").write_text("---\nbroken:", encoding="utf-8")
        issues = []
        self.assertEqual(len(read_attempts(self.vault, diagnostics=issues)), 1)
        self.assertEqual(len(issues), 1)
        note = load_note(path, self.vault)
        note.meta["task_text"] = "a contradictory intent"
        self.vault.path(config.RECALL_ATTEMPTS + "/conflict.md").write_text(
            compose(note.meta, note.body), encoding="utf-8",
        )
        self.assertEqual(read_attempts(self.vault, diagnostics=issues), [])
        self.assertTrue(any("conflicting" in issue for issue in issues))

    def test_gap_is_linked_idempotent_and_never_a_factual_observation(self):
        self.index()
        recall.recall(self.vault, "mcp", session_id="gap-session", now=NOW)
        episode = self.episode("## What happened\nNo applicable knowledge was available.",
                               session_id="gap-session", domains=["mcp"])
        canonical = self.snapshot("knowledge")
        path = create_gap_candidate(
            self.vault, "- [behaviour] Need transport retry guidance", domain="mcp",
            session_id="gap-session", source_episode=episode.ref, now=NOW,
        )
        note = load_note(path, self.vault)
        self.assertEqual(note.type, "gap")
        self.assertEqual(note.meta["domains"], ["mcp"])
        self.assertEqual(note.meta["source_episode"], episode.ref)
        self.assertEqual(note.meta["signal"], "normal")
        self.assertEqual(note.observations(), [])
        for key in ("status", "confidence", "approval", "feedback", "last_verified"):
            self.assertNotIn(key, note.meta)
        self.assertEqual(validate_note(note, self.vault), [])
        before = self.snapshot()
        replay = create_gap_candidate(
            self.vault, "- [behaviour] Need transport retry guidance", domain="mcp",
            session_id="gap-session", source_episode=episode.ref + ".md",
            now=NOW + timedelta(days=1),
        )
        self.assertEqual(replay, path)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(canonical, self.snapshot("knowledge"))

    def test_gap_redaction_and_invalid_domains_or_linkage(self):
        need = "mcp password=" + "B" * 30
        path = create_gap_candidate(self.vault, need, domain="mcp", now=NOW)
        self.assertNotIn("B" * 30, path.read_text(encoding="utf-8"))
        for options in (
            {"domain": "absent"}, {"domain": "mcp", "source_episode": "../outside"},
            {"domain": "mcp", "source_episode": "knowledge/patterns/validation-order"},
        ):
            with self.subTest(options=options), self.assertRaises(VaultError):
                create_gap_candidate(self.vault, "research need", **options)

    def test_quality_uses_common_events_and_filters_duplicates_old_and_future_reports(self):
        self.index()
        result = recall.recall(self.vault, "mcp", session_id="quality", now=NOW)
        event = OutcomeEvent(
            "quality-event", NOW.isoformat(), "quality", "recall", result.attempt_id,
            "off-target", domain="mcp", context={"route": "mcp"},
        )
        events = [
            event, event,
            replace(event, event_id="old", timestamp=(NOW - timedelta(days=31)).isoformat()),
            replace(event, event_id="future", timestamp=(NOW + timedelta(days=1)).isoformat()),
        ]
        before = self.snapshot()
        summary = recall_quality_summary(self.vault, now=NOW, events=events)
        self.assertEqual(summary["counts"]["off-target"], 1)
        self.assertEqual(summary["by_domain"]["mcp"]["off-target"], 1)
        self.assertEqual(summary["by_route"]["mcp"]["off-target"], 1)
        self.assertEqual(before, self.snapshot())

    def test_quality_reads_shared_journal_and_legacy_episode_projection(self):
        from memory_mesh.outcomes import record_outcome

        self.index()
        result = recall.recall(self.vault, "mcp", session_id="quality-journal", now=NOW)
        event = record_outcome(
            self.vault, session_id="quality-journal", subject_type="recall",
            subject_id=result.attempt_id, outcome="missed", domain="mcp",
            context={"route": "mcp"}, now=NOW,
        )
        self.episode(
            "## What happened\nNo suitable memory was returned.",
            session_id="quality-journal", domains=["mcp"], recall_quality="missed",
            outcome_events=[event.event_id],
        )
        summary = recall_quality_summary(self.vault, now=NOW)
        self.assertEqual(summary["counts"]["missed"], 1)

    def test_attempt_time_window_excludes_old_and_future_attempts(self):
        self.index()
        for session, timestamp in (
            ("recent", NOW), ("old", NOW - timedelta(days=31)), ("future", NOW + timedelta(days=1)),
        ):
            recall.recall(self.vault, "mcp", session_id=session, now=timestamp)
        self.assertEqual(recall_summary(self.vault, now=NOW)["attempts"], 1)
        self.assertEqual(recall_summary(self.vault, now=NOW, days=90)["attempts"], 2)

    def test_unchanged_counts_do_not_churn_status_with_the_read_clock(self):
        self.index()
        recall.recall(self.vault, "mcp", session_id="stable-status", now=NOW)
        self.assertEqual(
            recall_summary(self.vault, now=NOW),
            recall_summary(self.vault, now=NOW + timedelta(seconds=1)),
        )
        self.assertEqual(
            recall_quality_summary(self.vault, now=NOW, events=[]),
            recall_quality_summary(self.vault, now=NOW + timedelta(seconds=1), events=[]),
        )

    def test_off_target_second_pass_shares_matcher_and_never_rewrites(self):
        self.settings(routing={"copilot-studio": {
            "aliases": ["declarative orchestration"], "concepts": ["connectors"],
        }})
        episode = self.episode(
            "## Goal\nmcp stdio only appears in an excluded section.\n\n"
            "## What happened\nTested declarative orchestration.\n\n"
            "## Candidate learnings\n- Check connectors before reuse.\n\n"
            "## Knowledge used\n- [[unused]] unclear — did not apply.\n",
            recall_quality="off-target",
        )
        before = self.snapshot()
        suggestions = routing_suggestions(self.vault, episodes=[episode], now=NOW)
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion.suggested_domain, "copilot-studio")
        self.assertEqual(suggestion.recalled_domains, ("coding-agents",))
        self.assertEqual(suggestion.matched_terms, ("connectors", "declarative orchestration"))
        self.assertIn("episode reports off-target recall", suggestion.reasons)
        self.assertNotIn("Goal", suggestion.sections)
        self.assertEqual(before, self.snapshot())

    def test_second_pass_prefers_attempt_domains_and_ignores_repeated_generic_word(self):
        self.index()
        recall.recall(self.vault, "mcp", session_id="actual-route", now=NOW)
        episode = self.episode("## What happened\nMCP transports were checked.",
                               session_id="actual-route")
        self.assertEqual(routing_suggestions(self.vault, episodes=[episode], now=NOW), [])
        episode = self.episode("## What happened\ntopic topic topic topic")
        self.assertEqual(routing_suggestions(self.vault, episodes=[episode], now=NOW), [])
        episode = self.episode("## What happened\nCopilot Studio changed.", domains="malformed")
        diagnostics = []
        self.assertEqual(
            routing_suggestions(self.vault, episodes=[episode], now=NOW, diagnostics=diagnostics), [],
        )
        self.assertTrue(diagnostics)

    def test_second_pass_never_invents_a_phrase_across_section_boundaries(self):
        self.settings(routing={"copilot-studio": {"aliases": ["declarative orchestration"]}})
        episode = self.episode(
            "## What happened\nA declarative\n\n"
            "## Candidate learnings\norchestration was discussed.\n",
        )
        self.assertEqual(routing_suggestions(self.vault, episodes=[episode], now=NOW), [])


if __name__ == "__main__":
    unittest.main()
