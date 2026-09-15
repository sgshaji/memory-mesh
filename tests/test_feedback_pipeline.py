import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from helpers import make_vault

from memory_mesh import capture, config, episodes, frontmatter, indexes, outcomes
from memory_mesh.curator import analytics, engine, feedback, review
from memory_mesh.experience import set_mode
from memory_mesh.notes import load_note, section
from memory_mesh.routing_diagnostics import RecallAttempt
from memory_mesh.schema import validate_note


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class TestFeedbackPipeline(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        for directory in (config.INBOX, config.EPISODES, *config.KNOWLEDGE_FOLDERS):
            if directory == config.INDEX_DIR:
                continue
            for path in self.vault.path(directory).rglob("*.md"):
                path.unlink()
        for index in indexes.list_domain_indexes(self.vault):
            index.sections = {name: [] for name in indexes.SECTIONS}
            index.path.write_text(indexes.render_index(index, "2026-09-14"), encoding="utf-8")
        self.write("episodes/pipeline-origin.md", {
            "type": "episode", "tool": "test-host", "domains": ["coding-agents"],
            "status": "mined", "captured": NOW.isoformat(), "trust": "first-party", "sensitivity": "checked",
        }, "## What happened\n- A synthetic source was recorded.\n")

    def write(self, relative, meta, body):
        path = self.vault.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        return path

    def knowledge(self, name="subject", *, folder="patterns", **meta):
        return self.write(f"knowledge/{folder}/pipeline-{name}.md", {
            "type": "tool-behaviour" if folder == "tools" else "pattern",
            "title": f"Pipeline {name}", "status": "validated", "trust": "first-party",
            "confidence": "high", "domains": ["coding-agents"],
            "applies_to": {"tools": ["test-host"], "from": "2026-01"},
            "first_observed": "2026-01-01", "last_verified": "2026-09-14",
            "feedback": {"served": 0, "held": 0, "failed": 0, "unclear": 0},
            "evidence": ["episodes/pipeline-origin"], **meta,
        }, "## Observations\n- [procedure] Verify the exact result before proceeding.\n")

    def event(self, path, session, outcome="held", *, reason=None, days=0):
        return outcomes.record_outcome(
            self.vault, session_id=session, subject_type="knowledge",
            subject_id=self.vault.rel(path)[:-3], outcome=outcome, reason=reason,
            context={"tool": "test-host"}, source="fixture", now=NOW - timedelta(days=days),
        )

    def index(self, *paths):
        target = self.vault.path("knowledge/_index/coding-agents.md")
        index = indexes.parse_index(target, self.vault)
        for path in paths:
            index.add("Read first", self.vault.rel(path)[:-3], "A recorded procedure")
        target.write_text(indexes.render_index(index, "2026-09-14"), encoding="utf-8")
        return target

    def stable_files(self):
        paths = list(self.vault.path(config.KNOWLEDGE).rglob("*.md"))
        paths += list(self.vault.path(config.REVIEW_DIR).rglob("*.md"))
        return {path: path.read_bytes() for path in paths}

    def test_journal_and_partial_episode_projection_count_once_during_compile(self):
        target = self.knowledge()
        event = self.event(target, "pipeline-held")
        episode = episodes.create_stub(
            self.vault, "test-host", "partial", retrieved=[self.vault.rel(target)[:-3]],
            session_id="pipeline-held", now=NOW,
        )
        note = load_note(episode, self.vault)
        partial = "## Knowledge used\n" + section(note.body, "Knowledge used") + "\n\n## Candidate learnings\n"
        episode.write_text(frontmatter.compose(note.meta, partial), encoding="utf-8")
        episodes.finish(self.vault, episode, now=NOW)
        with patch.object(outcomes, "collect_evidence", wraps=outcomes.collect_evidence) as collect:
            engine.run_compile(self.vault, now=NOW)
        self.assertEqual(collect.call_count, 1)
        note = load_note(target, self.vault)
        self.assertEqual(note.meta["feedback"], {"served": 1, "held": 1, "failed": 0, "unclear": 0})
        self.assertEqual(note.meta["confidence"], "medium")
        health = feedback.assess_knowledge(self.vault, note, now=NOW, events=[event])
        self.assertEqual(health.evidence.event_ids, (event.event_id,))
        self.assertEqual(health.confidence, note.meta["confidence"])
        self.assertEqual(json.loads(json.dumps(health.as_dict()))["subject_id"], note.ref)

    def test_unattributed_legacy_feedback_is_diagnosed_without_votes_or_episode_edits(self):
        target = self.knowledge()
        event = self.event(target, "attributed-report")
        malformed = self.write("episodes/pipeline-unattributed.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "status": "mined", "trust": "first-party", "sensitivity": "checked",
            "domains": ["coding-agents"],
        }, "## Knowledge used\n- held\n")
        original = malformed.read_bytes()
        with patch.object(outcomes, "collect_evidence", wraps=outcomes.collect_evidence) as collect:
            report = engine.run_compile(self.vault, now=NOW)
        self.assertEqual(collect.call_count, 1)
        self.assertIs(collect.call_args.kwargs["diagnostics"], report.warnings)
        self.assertTrue(any("unattributed legacy feedback" in warning for warning in report.warnings))
        self.assertEqual(load_note(target, self.vault).meta["feedback"]["held"], 1)
        diagnostics = []
        health = next(item for item in analytics.assess_all_knowledge(
            self.vault, now=NOW, diagnostics=diagnostics,
        ) if item.subject_id == self.vault.rel(target)[:-3])
        self.assertEqual(health.evidence.event_ids, (event.event_id,))
        self.assertTrue(any("unattributed legacy feedback" in warning for warning in diagnostics))
        single = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
        self.assertTrue(any("unattributed legacy feedback" in reason for reason in single.reasons))
        self.assertEqual(malformed.read_bytes(), original)

    def test_preloaded_episodes_are_forwarded_to_shared_collection_without_reopening(self):
        target = self.knowledge()
        self.write("episodes/pipeline-preloaded.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "status": "mined", "trust": "first-party", "sensitivity": "checked",
            "domains": ["coding-agents"],
        }, "## Knowledge used\n- [[knowledge/patterns/pipeline-subject]] - held - observed result\n")
        notes = [load_note(target, self.vault)]
        episode_notes = [
            load_note(path, self.vault) for path in self.vault.path(config.EPISODES).glob("*.md")
        ]
        with patch.object(outcomes, "collect_evidence", wraps=outcomes.collect_evidence) as collect:
            health = analytics.assess_all_knowledge(
                self.vault, now=NOW, notes=notes, episodes=iter(episode_notes),
            )
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.kwargs["episodes"], episode_notes)
        self.assertEqual(health[0].feedback["held"], 1)

    def test_legacy_context_references_never_become_knowledge_votes(self):
        target = self.knowledge(confidence="low")
        context = self.write("episodes/pipeline-context-only.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "status": "mined", "trust": "first-party", "sensitivity": "checked",
            "domains": ["coding-agents"],
        }, (
            "## Knowledge used\n"
            "- [[projects/copilot-studio-skills]] - held - consulted project context\n"
            "- [[knowledge/_index/coding-agents]] - held - inspected routing context\n"
        ))
        original = context.read_bytes()
        engine.run_compile(self.vault, now=NOW)
        health = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
        self.assertEqual(health.evidence.event_ids, ())
        self.assertEqual(health.feedback["held"], 0)
        self.assertEqual(health.confidence, "low")
        self.assertEqual(context.read_bytes(), original)

    def test_projection_corruption_still_aborts_with_diagnostic_sink(self):
        target = self.knowledge()
        self.write("episodes/pipeline-corrupt-projection.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "status": "mined", "trust": "first-party", "sensitivity": "checked",
            "domains": ["coding-agents"], "outcome_events": ["missing-journal-event"],
        }, "## Knowledge used\n- [[knowledge/patterns/pipeline-subject]] - held\n")
        before = self.stable_files()
        with self.assertRaisesRegex(outcomes.OutcomeError, "missing outcome event"):
            engine.run_compile(self.vault, now=NOW)
        self.assertEqual(self.stable_files(), before)
        with self.assertRaisesRegex(outcomes.OutcomeError, "missing outcome event"):
            analytics.assess_all_knowledge(self.vault, now=NOW, diagnostics=[])
        self.assertEqual(load_note(target, self.vault).meta["feedback"]["held"], 0)

    def test_repeated_compile_and_lint_do_not_compound_feedback_or_indexes(self):
        target = self.knowledge()
        self.index(target)
        for index in range(5):
            self.event(target, f"held-{index}")
        engine.run_compile(self.vault, now=NOW)
        before = self.stable_files()
        engine.run_compile(self.vault, now=NOW)
        engine.run_lint(self.vault, now=NOW)
        self.assertEqual(self.stable_files(), before)
        self.assertEqual(load_note(target, self.vault).meta["feedback"]["held"], 5)

    def test_maintenance_reuses_its_knowledge_inventory_for_usage_and_suggestions(self):
        target = self.knowledge()
        self.event(target, "cached-maintenance")
        read = analytics._read_notes

        def reject_repeated_knowledge_scan(vault, folder, diagnostics):
            if folder == config.KNOWLEDGE:
                self.fail("maintenance analytics repeated the knowledge inventory scan")
            return read(vault, folder, diagnostics)

        with patch.object(analytics, "_read_notes", side_effect=reject_repeated_knowledge_scan):
            engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(target, self.vault).meta["feedback"]["held"], 1)

    def test_two_recent_matched_changes_quarantine_without_erasing_high_confidence(self):
        target = self.knowledge()
        index_path = self.index(target)
        skill = self.write("skills/pipeline-skill.md", {
            "type": "skill", "title": "Pipeline procedure", "confidence": "high",
            "depends_on": [self.vault.rel(target)[:-3]],
        }, "## Procedure\nRun the documented checks.")
        skill_before = skill.read_bytes()
        for index in range(60):
            self.event(target, f"old-success-{index}", days=90)
        for index in range(2):
            self.event(target, f"changed-{index}", "failed", reason="behaviour_changed")
        body_before = load_note(target, self.vault).body
        engine.run_compile(self.vault, now=NOW)
        note = load_note(target, self.vault)
        self.assertEqual(note.status, "stale")
        self.assertEqual(note.meta["confidence"], "high")
        self.assertEqual(note.body, body_before)
        self.assertEqual(note.meta["feedback"]["held"], 60)
        self.assertFalse([issue for issue in validate_note(note, self.vault) if issue.severity == "error"])
        health = analytics.assess_knowledge(self.vault, note, now=NOW)
        self.assertTrue(health.needs_review)
        self.assertTrue(health.possible_behaviour_change)
        index = indexes.parse_index(index_path, self.vault)
        for section_name in ("Read first", "Known failures", "Recently verified (30 days)"):
            self.assertFalse(any(entry.ref == note.ref for entry in index.sections[section_name]))
        self.assertEqual(skill.read_bytes(), skill_before)
        queued = [item for path in review.pending_review_files(self.vault) for item in review.parse_review_file(path)]
        self.assertTrue(any(item.payload.get("attention_kind") == "knowledge" for item in queued))
        self.assertTrue(any(item.payload.get("attention_kind") == "skill" for item in queued))
        before = self.stable_files()
        engine.run_lint(self.vault, now=NOW)
        self.assertEqual(self.stable_files(), before)

    def test_misapplied_failures_are_weaker_and_never_auto_quarantine(self):
        target = self.knowledge()
        for index in range(5):
            self.event(target, f"good-{index}")
        for index in range(2):
            self.event(target, f"misapplied-{index}", "failed", reason="misapplied")
        engine.run_compile(self.vault, now=NOW)
        health = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
        self.assertAlmostEqual(health.evidence.weighted_failed, 0.2)
        self.assertFalse(health.possible_behaviour_change)
        self.assertEqual(load_note(target, self.vault).status, "validated")
        self.assertEqual(health.confidence, "high")

    def test_full_references_keep_same_named_knowledge_independent(self):
        first = self.knowledge("same")
        other = self.knowledge("same", folder="tools")
        index_path = self.index(first, other)
        for index in range(2):
            self.event(first, f"first-only-{index}", "failed", reason="behaviour_changed")
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(first, self.vault).status, "stale")
        self.assertEqual(load_note(other, self.vault).status, "validated")
        entries = indexes.parse_index(index_path, self.vault).sections["Read first"]
        self.assertEqual([entry.ref for entry in entries], [self.vault.rel(other)[:-3]])

    def test_out_of_calendar_window_does_not_reenter_recently_verified(self):
        target = self.knowledge(applies_to={"tools": ["test-host"], "from": "2026-01", "to": "2026-09-13"})
        index_path = self.index(target)
        for index in range(4):
            self.event(target, f"historical-match-{index}", days=2)
        engine.run_compile(self.vault, now=NOW)
        health = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
        self.assertEqual(health.applicability.state, "mismatch")
        self.assertGreater(health.evidence.weighted_held, 3)
        index = indexes.parse_index(index_path, self.vault)
        self.assertFalse(index.sections["Read first"])
        self.assertFalse(index.sections["Recently verified (30 days)"])
        before = index_path.read_bytes()
        engine.run_lint(self.vault, now=NOW)
        self.assertEqual(index_path.read_bytes(), before)

    def test_gap_and_episode_link_remain_non_factual_even_after_approval_attempt(self):
        gap = self.write("00-inbox/pipeline-gap.md", {
            "type": "gap", "title": "A missing explanation", "need": "Research an undocumented interface",
            "source": "fixture", "signal": "high", "captured": NOW.isoformat(),
            "trust": "first-party", "sensitivity": "checked", "domains": ["coding-agents"],
        }, "")
        self.write("episodes/pipeline-gap-context.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "summarised",
            "domains": ["coding-agents"],
        }, "## Candidate learnings\n- [[00-inbox/pipeline-gap]]\n")
        report = engine.run_compile(self.vault, now=NOW)
        self.assertFalse(any(decision.kind == "CREATE" for decision in report.decisions))
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW).gap_count, 1)
        for path in review.pending_review_files(self.vault):
            path.write_text(path.read_text(encoding="utf-8").replace("[ ] acknowledged", "[x] approve"), encoding="utf-8")
        engine.run_compile(self.vault, now=NOW)
        engine.run_lint(self.vault, now=NOW)
        note = load_note(gap, self.vault)
        for field in ("status", "confidence", "feedback", "processed"):
            self.assertNotIn(field, note.meta)
        self.assertFalse([issue for issue in validate_note(note, self.vault) if issue.severity == "error"])
        self.assertFalse(list(self.vault.path("knowledge/patterns").glob("*.md")))

    @unittest.skipUnless(os.name == "nt", "Windows reference aliases")
    def test_gap_filter_resolves_windows_case_separator_and_extension_aliases(self):
        gap = self.write("00-inbox/pipeline-alias-gap.md", {
            "type": "gap", "title": "Research need", "need": "Investigate a missing contract",
        }, "")
        candidate = self.write("00-inbox/pipeline-alias-fact.md", {
            "type": "candidate", "title": "An observed result",
        }, "## Observations\n- [observation] A recorded result.")
        should_skip = feedback.inbox_reference_filter([
            load_note(gap, self.vault), load_note(candidate, self.vault),
        ])
        for alias in (
            "00-INBOX/PIPELINE-ALIAS-GAP.MD",
            "00-inbox\\pipeline-alias-gap.MD",
            "PIPELINE-ALIAS-GAP.MD",
            "00-INBOX/PIPELINE-ALIAS-GAP.MD|Research task",
        ):
            with self.subTest(alias=alias):
                self.assertTrue(should_skip(f"Approve follow-up research [[{alias}]] (cli, 1.0)."))
        self.assertFalse(should_skip(
            "An independently observed result [[00-INBOX/PIPELINE-ALIAS-FACT.MD]] (cli, 1.0).",
        ))

    def test_high_signal_orders_processing_but_not_admission(self):
        normal = capture.learn(self.vault, "Nimbus export source routing", domain="coding-agents", now=NOW)
        high = capture.learn(self.vault, "Quartz compile branch inspection", domain="coding-agents", signal="high", now=NOW)
        report = engine.run_compile(self.vault, now=NOW)
        selected = [
            item.source_ref for item in report.decisions
            if item.source_ref in (self.vault.rel(normal.path)[:-3], self.vault.rel(high.path)[:-3])
        ]
        self.assertEqual(selected[0], self.vault.rel(high.path)[:-3])
        self.assertEqual(report.candidate_priorities[0].signal, "high")
        for note_path in self.vault.path("knowledge/patterns").glob("*.md"):
            note = load_note(note_path, self.vault)
            self.assertEqual(note.status, "candidate")
            self.assertEqual(note.meta["confidence"], "low")

    def test_candidate_and_third_party_reports_stay_low(self):
        for name, meta in (("candidate", {"status": "candidate"}), ("external", {"trust": "third-party"})):
            target = self.knowledge(name, **meta)
            for index in range(5):
                self.event(target, f"{name}-report-{index}")
            health = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
            self.assertEqual(health.confidence, "low")
            self.assertTrue(any("admission" in reason or "trust" in reason for reason in health.reasons))

    def test_reported_outcomes_never_modify_v2_marked_or_nonlegacy_knowledge(self):
        target = self.knowledge(v2_admission={"source": "protected-fixture"})
        for index in range(2):
            self.event(target, f"protected-{index}", "failed", reason="behaviour_changed")
        before = target.read_bytes()
        engine.run_compile(self.vault, now=NOW)
        engine.run_lint(self.vault, now=NOW)
        self.assertEqual(target.read_bytes(), before)
        for mode in ("strict", "shadow", "off"):
            set_mode(self.vault, mode)
            health = analytics.assess_knowledge(self.vault, load_note(target, self.vault), now=NOW)
            self.assertFalse(health.maintenance_allowed)
            self.assertEqual(target.read_bytes(), before)

    def test_routing_and_skill_notices_deduplicate_across_days_and_acknowledgement(self):
        target = self.knowledge(status="stale")
        skill = self.write("skills/pipeline-dependent.md", {
            "type": "skill", "title": "Dependent procedure", "depends_on": [self.vault.rel(target)[:-3]],
        }, "## Procedure\nInspect the dependency.")
        self.write("episodes/pipeline-routing.md", {
            "type": "episode", "tool": "test-host", "captured": NOW.isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "summarised",
            "domains": ["coding-agents"], "recall_quality": "off-target",
        }, "## What happened\n- Copilot Studio topics require grounding validation.\n")
        router_before = self.vault.path(config.ROUTER).read_bytes()
        skill_before = skill.read_bytes()
        engine.run_compile(self.vault, now=NOW)
        pending = review.pending_review_files(self.vault)
        kinds = {
            item.payload.get("attention_kind")
            for path in pending for item in review.parse_review_file(path)
        }
        self.assertTrue({"knowledge", "skill", "routing"}.issubset(kinds))
        before = {path: path.read_bytes() for path in pending}
        engine.run_compile(self.vault, now=NOW + timedelta(days=1))
        self.assertEqual(review.pending_review_files(self.vault), pending)
        self.assertEqual(before, {path: path.read_bytes() for path in pending})
        for path in pending:
            path.write_text(path.read_text(encoding="utf-8").replace("[ ] acknowledged", "[x] acknowledged"), encoding="utf-8")
        engine.run_compile(self.vault, now=NOW + timedelta(days=1))
        self.assertFalse(review.pending_review_files(self.vault))
        self.assertEqual(self.vault.path(config.ROUTER).read_bytes(), router_before)
        self.assertEqual(skill.read_bytes(), skill_before)

    def test_later_successes_never_auto_reactivate_quarantined_knowledge(self):
        target = self.knowledge(status="stale")
        index_path = self.index(target)
        for index in range(5):
            self.event(target, f"later-held-{index}")
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(target, self.vault).status, "stale")
        self.assertEqual(load_note(target, self.vault).meta["confidence"], "high")
        index = indexes.parse_index(index_path, self.vault)
        self.assertFalse(index.sections["Read first"])
        self.assertFalse(index.sections["Recently verified (30 days)"])

    def test_telemetry_does_not_create_votes_or_advance_verification(self):
        target = self.knowledge(
            "telemetry", folder="references", type="reference", confidence="low", last_verified="2026-01-01",
        )
        ref = self.vault.rel(target)[:-3]
        for index in range(5):
            attempt = RecallAttempt(
                attempt_id=f"pipeline-recall-{index}", timestamp=NOW.isoformat(),
                session_id=f"pipeline-session-{index}", task_text="Operational recall",
                task_fingerprint=None, route="coding-agents", domains=("coding-agents",),
                note_refs=(ref,), note_domains=("coding-agents",), note_revisions=("a" * 64,),
                total_count=1, usable_count=1, target_minimum=1, potential_gap=False,
            )
            self.write(f"{config.RECALL_ATTEMPTS}/attempt-{index}.md", {
                "type": "recall-attempt", **attempt.as_dict(),
            }, "Operational telemetry, not correctness evidence.")
        engine.run_compile(self.vault, now=NOW)
        note = load_note(target, self.vault)
        self.assertEqual(note.meta["confidence"], "low")
        self.assertEqual(note.meta["feedback"]["held"], 0)
        self.assertEqual(note.meta["last_verified"], "2026-01-01")
        self.assertEqual(analytics.recall_usage(self.vault, now=NOW).by_ref[ref].last_30_days, 5)

    def test_retellings_in_one_session_do_not_qualify_for_graduation(self):
        target = self.knowledge()
        for index in range(5):
            outcomes.record_outcome(
                self.vault, session_id="one-session", event_id=f"separate-report-{index}",
                subject_type="knowledge", subject_id=self.vault.rel(target)[:-3], outcome="held",
                context={"tool": "test-host"}, now=NOW,
            )
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(load_note(target, self.vault).meta["feedback"]["held"], 5)
        self.assertFalse(self.vault.path(config.GRADUATION_FILE).exists())

    def test_usage_placement_notice_is_durable_and_acknowledgement_does_not_edit_index(self):
        target = self.knowledge("popular")
        ref = self.vault.rel(target)[:-3]
        index_path = self.vault.path("knowledge/_index/coding-agents.md")
        for index in range(5):
            attempt = RecallAttempt(
                attempt_id=f"popular-{index}", timestamp=NOW.isoformat(), session_id=f"popular-session-{index}",
                task_text="Retrieve a known procedure", task_fingerprint=None,
                route="coding-agents", domains=("coding-agents",), note_refs=(ref,),
                note_domains=("coding-agents",), note_revisions=("a" * 64,),
                total_count=1, usable_count=1, target_minimum=1, potential_gap=False,
            )
            self.write(f"{config.RECALL_ATTEMPTS}/popular-{index}.md", {
                "type": "recall-attempt", **attempt.as_dict(),
            }, "Operational telemetry.")
        engine.run_compile(self.vault, now=NOW)
        queued = [
            item for path in review.pending_review_files(self.vault) for item in review.parse_review_file(path)
            if item.payload.get("attention_kind") == "index"
        ]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].payload["details"]["action"], "promote")
        self.assertTrue(queued[0].payload["review_only"])
        self.assertFalse(indexes.parse_index(index_path, self.vault).sections["Read first"])
        before = index_path.read_bytes()
        for path in review.pending_review_files(self.vault):
            path.write_text(path.read_text(encoding="utf-8").replace("[ ] acknowledged", "[x] acknowledged"), encoding="utf-8")
        engine.run_compile(self.vault, now=NOW)
        self.assertEqual(index_path.read_bytes(), before)
        self.assertFalse(review.pending_review_files(self.vault))


if __name__ == "__main__":
    unittest.main()
