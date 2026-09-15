"""Skill health fixtures stay inside the checkout and are removed after use."""

import json
import shutil
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from helpers import directory_link

from memory_mesh import skill_health
from memory_mesh.config import Vault, VaultError
from memory_mesh.frontmatter import compose
from memory_mesh.outcome_types import OutcomeEvent
from memory_mesh.skill_health import (
    _DependencyLookup, _descriptors, _freshness, _now, _select_skill, _status_reasons,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class SkillFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / (".skill-health-fixture-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.vault = Vault(self.root)

    def write(self, reference, meta, body="Run deterministic validation first."):
        path = self.vault.path(reference)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(compose(meta, body), encoding="utf-8")
        return path


class SkillDescriptorTests(SkillFixture):
    def test_legacy_skill_has_no_invented_dependencies(self):
        self.write("skills/check.md", {"type": "skill", "title": "Check"})
        descriptor = _descriptors(self.vault)[0]
        self.assertEqual(descriptor.dependencies, ())
        self.assertEqual(descriptor.reasons, ())
        self.assertNotIn("confidence", descriptor.note.meta)

    def test_named_skill_md_and_vault_notes_are_descriptors_not_indexes(self):
        self.write("skills/runner/SKILL.md", {"name": "run-checks", "description": "Check"})
        self.write("skills/simple.md", {"type": "skill", "title": "Simple"})
        self.write("skills/_index.md", {"type": "index"})
        self.write("skills/README.md", {}, "# Skills\n\nDocumentation, not a skill.")
        self.write("skills/runner/example.md", {"name": "example"})
        descriptors = _descriptors(self.vault)
        self.assertEqual([item.note.ref for item in descriptors], [
            "skills/runner/SKILL", "skills/simple",
        ])
        for reference in ("runner", "run-checks", "skills/runner", "skills/runner/SKILL.md"):
            with self.subTest(reference=reference):
                self.assertEqual(
                    _select_skill(self.vault, reference, descriptors).note.ref,
                    "skills/runner/SKILL",
                )

    def test_duplicate_dependencies_are_reported_and_deduplicated(self):
        self.write("skills/check.md", {
            "type": "skill",
            "depends_on": [
                "knowledge/patterns/check",
                "knowledge/patterns/check.md",
                "[[knowledge/patterns/check]]",
            ],
        })
        descriptor = _descriptors(self.vault)[0]
        self.assertEqual(descriptor.dependencies, ("knowledge/patterns/check",))
        self.assertEqual(descriptor.reasons, (
            "Duplicate dependency declaration: knowledge/patterns/check",
        ))

    def test_invalid_dependency_list_does_not_become_an_inferred_reference(self):
        for invalid in ("knowledge/patterns/check", None, 4, {}):
            with self.subTest(invalid=invalid):
                self.write("skills/check.md", {"type": "skill", "depends_on": invalid})
                descriptor = _descriptors(self.vault)[0]
                self.assertEqual(descriptor.dependencies, ())
                self.assertIn("depends_on must be a list", descriptor.reasons[0])

    def test_valid_entries_survive_a_partly_malformed_dependency_list(self):
        self.write("skills/check.md", {
            "type": "skill", "depends_on": ["knowledge/patterns/check", 9, " "],
        })
        descriptor = _descriptors(self.vault)[0]
        self.assertEqual(descriptor.dependencies, ("knowledge/patterns/check",))
        self.assertTrue(descriptor.reasons)

    def test_ambiguous_and_unknown_skill_requests_are_explicit_errors(self):
        self.write("skills/one/check.md", {"type": "skill"})
        self.write("skills/two/check.md", {"type": "skill"})
        descriptors = _descriptors(self.vault)
        with self.assertRaisesRegex(VaultError, "ambiguous skill reference"):
            _select_skill(self.vault, "check", descriptors)
        for reference in ("missing", "../check", "skills/nonexistent/check.md"):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(VaultError, "unknown skill reference"):
                    _select_skill(self.vault, reference, descriptors)
        self.assertEqual(
            _select_skill(self.vault, "skills/two/check.md", descriptors).note.ref,
            "skills/two/check",
        )

    def test_malformed_skill_md_is_a_diagnostic_not_a_silent_omission(self):
        path = self.write("skills/check/SKILL.md", {"name": "check"})
        path.write_text("---\nname: check\n", encoding="utf-8")
        descriptor = _descriptors(self.vault)[0]
        self.assertIn("Malformed skill descriptor", descriptor.reasons[0])

    def test_missing_skills_directory_is_supported(self):
        self.assertEqual(_descriptors(self.vault), [])

    def test_discovery_does_not_follow_redirected_directories_or_cycles(self):
        self.write("skills/check.md", {"type": "skill"})
        self.write("knowledge/redirected/SKILL.md", {"name": "redirected"})
        directory_link(self.vault.path("skills/redirected"), self.vault.path("knowledge/redirected"))
        directory_link(self.vault.path("skills/loop"), self.vault.path("skills"))
        with patch.object(skill_health.notes, "load_note", wraps=skill_health.notes.load_note) as load:
            self.assertEqual([item.note.ref for item in _descriptors(self.vault)], ["skills/check"])
        self.assertEqual(load.call_count, 1)

    def test_terminal_and_unvalidated_states_have_specific_reasons(self):
        for status in ("candidate", "stale", "superseded", "resolved", "rejected"):
            with self.subTest(status=status):
                self.write("skills/check.md", {"type": "skill", "status": status})
                self.assertEqual(
                    _status_reasons(_descriptors(self.vault)[0].note),
                    [f"Recorded status is {status}"],
                )

    def test_supersession_pointer_is_not_hidden_by_a_validated_status(self):
        self.write("skills/check.md", {
            "type": "skill", "status": "validated", "superseded_by": "skills/new-check",
        })
        self.assertEqual(
            _status_reasons(_descriptors(self.vault)[0].note),
            ["Supersession is recorded: skills/new-check"],
        )


class SkillVerificationTests(unittest.TestCase):
    def test_missing_verification_remains_unknown_not_recent_success(self):
        result = _freshness(None, None, date(2026, 9, 14), 90)
        self.assertIsNone(result.last_verified)
        self.assertFalse(result.potentially_stale)
        self.assertFalse(result.needs_review)
        self.assertIn("unknown", result.reasons[0])

    def test_recent_success_can_refresh_an_old_verification_date(self):
        result = _freshness("2026-01-01", "2026-09-14", date(2026, 9, 14), 90)
        self.assertEqual(result.last_verified, "2026-09-14")
        self.assertFalse(result.potentially_stale)
        self.assertFalse(result.needs_review)

    def test_stale_verification_recommends_review_at_the_configured_interval(self):
        self.assertFalse(_freshness("2026-06-16", None, date(2026, 9, 14), 90).needs_review)
        result = _freshness("2026-06-15", None, date(2026, 9, 14), 90)
        self.assertTrue(result.potentially_stale)
        self.assertTrue(result.needs_review)
        self.assertIn("91 days", result.reasons[0])

    def test_future_and_invalid_dates_do_not_count_as_verification(self):
        for value in ("2027-01-01", "2026-02-30", "not-a-date", 20260914, [], "2026-W01-1"):
            with self.subTest(value=value):
                result = _freshness(value, None, date(2026, 9, 14), 90)
                self.assertIsNone(result.last_verified)
                self.assertTrue(result.needs_review)
                self.assertTrue(any("invalid" in reason or "future" in reason for reason in result.reasons))

    def test_invalid_declared_date_is_explained_even_with_usable_evidence(self):
        result = _freshness("invalid", "2026-09-14", date(2026, 9, 14), 90)
        self.assertEqual(result.last_verified, "2026-09-14")
        self.assertTrue(result.needs_review)
        self.assertIn("invalid", result.reasons[0])

    def test_current_time_is_normalized_once_to_utc(self):
        self.assertEqual(
            _now(date(2026, 9, 14)),
            datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(VaultError, "timezone"):
            _now(datetime(2026, 9, 14))
        with self.assertRaises(VaultError):
            _now("invalid")


class DependencyLookupTests(SkillFixture):
    def test_missing_and_qualified_dependency_refs_do_not_match_unrelated_notes(self):
        self.write("knowledge/patterns/base.md", {"type": "pattern", "status": "validated"})
        lookup = _DependencyLookup(self.vault)
        note, problem = lookup.get("knowledge/missing/base")
        self.assertIsNone(note)
        self.assertIn("Missing", problem)

    def test_indices_and_other_tiers_are_not_knowledge_dependencies(self):
        for ref, kind in (("knowledge/_index/base.md", "index"), ("projects/base.md", "project")):
            with self.subTest(reference=ref):
                self.write(ref, {"type": kind})
                _, problem = _DependencyLookup(self.vault).get(ref)
                self.assertIn("knowledge note", problem)

    def test_bare_dependency_names_cannot_resolve_outside_knowledge(self):
        self.write("projects/base.md", {"type": "project"})
        note, problem = _DependencyLookup(self.vault).get("base")
        self.assertIsNone(note)
        self.assertIn("Missing", problem)

    def test_corrupt_dependency_is_loadable_as_a_diagnostic(self):
        path = self.write("knowledge/patterns/base.md", {"type": "pattern"})
        path.write_text("---\ntype: pattern\n", encoding="utf-8")
        note, problem = _DependencyLookup(self.vault).get("knowledge/patterns/base")
        self.assertIsNotNone(note)
        self.assertIn("Malformed dependency frontmatter", problem)

    def test_resolution_and_note_loading_are_cached_across_aliases(self):
        path = self.write("knowledge/patterns/base.md", {"type": "pattern"})
        lookup = _DependencyLookup(self.vault)
        with (
            patch.object(skill_health.notes, "load_note", wraps=skill_health.notes.load_note) as load,
            patch.object(skill_health.notes, "resolve_ref", wraps=skill_health.notes.resolve_ref) as resolve,
        ):
            for _ in range(3):
                self.assertIsNotNone(lookup.get("base")[0])
                self.assertIsNotNone(lookup.get("knowledge/patterns/base")[0])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(load.call_args.args[0], path)
        self.assertEqual(resolve.call_count, 2)


class SkillHealthTests(SkillFixture):
    context = {"product": "workbench", "version": "2.1"}

    def skill(self, reference="skills/check.md", **updates):
        meta = {
            "type": "skill", "title": "Check", "confidence": "high",
            "last_verified": "2026-09-14",
            "applies_to": {"product": "workbench", "version": ">=2.0"},
        }
        meta.update(updates)
        return self.write(reference, meta)

    def knowledge(self, reference="knowledge/patterns/base.md", **updates):
        meta = {
            "type": "pattern", "title": "Base", "status": "validated",
            "confidence": "high", "last_verified": "2026-09-14",
            "applies_to": {"product": "workbench", "version": ">=2.0"},
        }
        meta.update(updates)
        return self.write(reference, meta)

    def event(self, number, outcome="succeeded", **updates):
        values = {
            "event_id": f"event-{number}", "timestamp": NOW.isoformat(),
            "session_id": f"session-{number}", "subject_type": "skill",
            "subject_id": "skills/check", "outcome": outcome,
            "context": self.context,
        }
        values.update(updates)
        return OutcomeEvent(**values)

    def health(self, reference="skills/check", events=(), **kwargs):
        kwargs.setdefault("context", self.context)
        kwargs.setdefault("now", NOW)
        return skill_health.assess_skill(self.vault, reference, events=events, **kwargs)

    def test_legacy_missing_metadata_is_supported_without_fabricating_success(self):
        self.write("skills/check.md", {"type": "skill", "title": "Legacy"})
        health = self.health()
        self.assertIsNone(health.last_verified)
        self.assertNotEqual(health.confidence, "high")
        self.assertEqual(health.dependencies, ())
        self.assertFalse(health.failed_recently)
        self.assertFalse(health.needs_review)
        self.assertFalse(health.potentially_stale)

    def test_malformed_descriptor_is_reported_by_public_batch_assessment(self):
        path = self.write("skills/check/SKILL.md", {"name": "check"})
        path.write_text("---\nname: check\n", encoding="utf-8")
        health = skill_health.assess_skills(self.vault, now=NOW, events=[])[0]
        self.assertTrue(health.needs_review)
        self.assertIsNone(health.confidence)
        self.assertIn("Malformed skill descriptor", " ".join(health.reasons))

    def test_healthy_dependency_is_resolved_with_canonical_identity(self):
        self.knowledge()
        self.skill(depends_on=["knowledge/patterns/base.md"])
        health = self.health()
        dependency = health.dependencies[0]
        self.assertEqual(dependency.subject_id, "knowledge/patterns/base")
        self.assertEqual(dependency.status, "validated")
        self.assertFalse(dependency.needs_review)
        self.assertFalse(health.potentially_stale)

    def test_stale_superseded_resolved_rejected_dependencies_recommend_review(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        for status in ("stale", "superseded", "resolved", "rejected"):
            with self.subTest(status=status):
                self.knowledge(status=status)
                health = self.health()
                self.assertTrue(health.potentially_stale)
                self.assertTrue(health.needs_review)
                self.assertEqual(health.confidence, "high")
                self.assertTrue(any(
                    "knowledge/patterns/base" in reason and status in reason
                    for reason in health.reasons
                ))

    def test_supersession_pointer_and_low_confidence_are_dependency_diagnostics(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        for updates, text in (
            ({"superseded_by": "knowledge/patterns/replacement"}, "replacement"),
            ({"confidence": "low"}, "low"),
        ):
            with self.subTest(updates=updates):
                self.knowledge(**updates)
                health = self.health()
                self.assertTrue(health.potentially_stale)
                self.assertTrue(any(text in reason for reason in health.reasons))

    def test_invalid_dependency_metadata_remains_diagnostic_not_a_trust_claim(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        self.knowledge(confidence=99, status="invented")
        health = self.health()
        self.assertTrue(health.needs_review)
        self.assertIsNone(health.dependencies[0].confidence)
        self.assertIn("Dependency confidence is invalid", " ".join(health.reasons))
        self.assertIn("Dependency status is invalid", " ".join(health.reasons))

    def test_missing_dependency_does_not_fall_back_to_an_unrelated_basename(self):
        self.knowledge()
        self.skill(depends_on=["knowledge/missing/base"])
        health = self.health()
        dependency = health.dependencies[0]
        self.assertIsNone(dependency.subject_id)
        self.assertTrue(dependency.needs_review)
        self.assertTrue(health.potentially_stale)
        self.assertIn("knowledge/missing/base", " ".join(health.reasons))

    def test_ambiguous_bare_dependency_is_a_warning_not_a_selected_note(self):
        self.knowledge()
        self.knowledge("knowledge/workarounds/base.md", type="workaround")
        self.skill(depends_on=["base"])
        health = self.health()
        self.assertIsNone(health.dependencies[0].subject_id)
        self.assertTrue(health.needs_review)
        self.assertIn("ambiguous", " ".join(health.reasons).lower())

    def test_non_knowledge_dependencies_and_traversal_are_diagnostics(self):
        self.write("projects/base.md", {"type": "project"})
        self.write("knowledge/_index/base.md", {"type": "index"})
        for ref in ("projects/base", "knowledge/_index/base", "../base", "skills/check"):
            with self.subTest(reference=ref):
                self.skill(depends_on=[ref])
                health = self.health()
                self.assertTrue(health.needs_review)
                self.assertTrue(health.dependencies[0].needs_review)

    def test_duplicate_aliases_are_evaluated_once_and_explained(self):
        self.knowledge()
        self.skill(depends_on=["base", "knowledge/patterns/base", "knowledge/patterns/base.md"])
        health = self.health()
        self.assertEqual(len(health.dependencies), 1)
        self.assertIn("duplicate", " ".join(health.reasons).lower())

    def test_dependency_version_mismatch_is_distinct_from_unknown_context(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        self.knowledge(applies_to={"product": "workbench", "version": ">=3.0"})
        mismatched = self.health()
        self.assertTrue(mismatched.potentially_stale)
        self.assertEqual(mismatched.dependencies[0].applicability["state"], "mismatch")
        unknown = self.health(context=None)
        self.assertTrue(unknown.needs_review)
        self.assertEqual(unknown.dependencies[0].applicability["state"], "unknown")

    def test_expired_skill_preserves_matched_historical_successes_without_current_context(self):
        self.skill(last_verified=None, applies_to={
            "tools": ["checker"], "from": "2026-08", "to": "2026-08",
        })
        events = [
            self.event(index, timestamp="2026-08-20T12:00:00Z", context={"tool": "checker"})
            for index in range(5)
        ]
        health = self.health(events=events, context=None)
        self.assertEqual(health.applicability["state"], "mismatch")
        self.assertEqual(health.confidence, "high")
        self.assertEqual(health.last_verified, "2026-08-20")
        self.assertTrue(health.needs_review)
        self.assertTrue(health.potentially_stale)
        self.assertTrue(all(
            item["applicability"]["state"] == "match"
            for item in health.evidence["contributions"]
        ))

    def test_expired_dependency_flags_the_skill_even_without_host_or_version_context(self):
        self.skill(applies_to=None, depends_on=["knowledge/patterns/base"])
        self.knowledge(applies_to={"tools": ["checker"], "to": "2026-08"})
        health = self.health(context=None)
        dependency = health.dependencies[0]
        self.assertEqual(dependency.applicability["state"], "mismatch")
        self.assertEqual(dependency.confidence, "high")
        self.assertTrue(dependency.potentially_stale)
        self.assertTrue(health.potentially_stale)
        self.assertTrue(health.needs_review)

    def test_in_window_calendar_bounds_do_not_supply_a_missing_explicit_version(self):
        self.skill(applies_to={
            "from": "2026-09", "to": "2026-09", "version": ">=2026-09",
        })
        unknown = self.health(context=None)
        self.assertEqual(unknown.applicability["state"], "unknown")
        self.assertTrue(unknown.needs_review)
        self.assertFalse(unknown.potentially_stale)
        matched = self.health(context={"version": "2026-09"})
        self.assertEqual(matched.applicability["state"], "match")
        self.assertFalse(matched.needs_review)

    def test_skill_tool_mismatch_unknown_version_and_legacy_tools_are_explained(self):
        self.skill(applies_to={"tools": ["checker"], "from": "2.0"})
        for context, state in (
            ({"tool": "other", "version": "2.1"}, "mismatch"),
            ({"tool": "checker"}, "unknown"),
            ({"tool": "checker", "version": "2.1"}, "match"),
        ):
            with self.subTest(context=context):
                health = self.health(context=context)
                self.assertEqual(health.applicability["state"], state)
                self.assertEqual(health.needs_review, state != "match")

    def test_product_cannot_supply_a_legacy_skill_host_or_failure_quorum(self):
        self.skill(applies_to={"tools": ["checker"]})
        for context, state in (
            ({"product": "checker"}, "unknown"),
            ({"tool": "other", "product": "checker"}, "mismatch"),
        ):
            with self.subTest(context=context):
                events = [
                    self.event(index, "failed", reason="behaviour_changed", context=context)
                    for index in (1, 2)
                ]
                health = self.health(events=events, context=context)
                self.assertEqual(health.applicability["state"], state)
                self.assertEqual(health.evidence["recent_behaviour_changes"], 0)
                self.assertFalse(health.evidence["needs_review"])
                self.assertTrue(health.needs_review)
                self.assertEqual(health.potentially_stale, state == "mismatch")
                self.assertIn("context.tool", " ".join(health.reasons))
                self.assertNotIn("Recent failed skill outcomes from", " ".join(health.reasons))

    def test_dependency_host_checks_do_not_substitute_matching_product_text(self):
        self.skill(applies_to=None, depends_on=["knowledge/patterns/base"])
        self.knowledge(applies_to={"tools": ["checker"]})
        for context, state in (
            ({"product": "checker"}, "unknown"),
            ({"tool": "other", "product": "checker"}, "mismatch"),
        ):
            with self.subTest(context=context):
                events = [
                    self.event(index, "failed", subject_type="knowledge",
                               subject_id="knowledge/patterns/base",
                               reason="behaviour_changed", context=context)
                    for index in (1, 2)
                ]
                health = self.health(events=events, context=context)
                dependency = health.dependencies[0]
                self.assertEqual(dependency.applicability["state"], state)
                self.assertEqual(dependency.evidence["recent_behaviour_changes"], 0)
                self.assertFalse(dependency.evidence["needs_review"])
                self.assertTrue(dependency.needs_review)
                self.assertEqual(health.potentially_stale, state == "mismatch")

    def test_questionable_applicability_requests_review_without_downgrading_history(self):
        self.skill(applies_to={"product": "workbench", "version": "latest preview"})
        health = self.health()
        self.assertEqual(health.applicability["state"], "unknown")
        self.assertEqual(health.confidence, "high")
        self.assertTrue(health.needs_review)
        self.assertIn("applicab", " ".join(health.reasons).lower())

    def test_stale_skill_verification_does_not_rewrite_confidence(self):
        self.skill(last_verified="2026-01-01")
        health = self.health()
        self.assertEqual(health.confidence, "high")
        self.assertTrue(health.potentially_stale)
        self.assertTrue(health.needs_review)
        self.assertIn("Last verified", " ".join(health.reasons))

    def test_old_dependency_verification_is_visible(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        self.knowledge(last_verified="2026-01-01")
        health = self.health()
        self.assertTrue(health.potentially_stale)
        self.assertIn("knowledge/patterns/base", " ".join(health.reasons))
        self.assertIn("Last verified", " ".join(health.reasons))

    def test_success_uses_shared_evidence_and_partial_does_not_verify(self):
        from memory_mesh.confidence import evaluate_evidence

        self.skill(last_verified=None, confidence=None)
        successes = [self.event(index) for index in range(4)]
        health = self.health(events=successes)
        expected = evaluate_evidence(
            successes, applies_to={"product": "workbench", "version": ">=2.0"}, now=NOW,
        )
        self.assertEqual(health.confidence, expected.confidence)
        self.assertEqual(health.last_verified, "2026-09-14")
        partial = self.health(events=[self.event(5, "partial")])
        self.assertIsNone(partial.last_verified)
        self.assertFalse(partial.failed_recently)
        self.assertIn("partial", str(partial.evidence))

    def test_one_failure_is_visible_but_does_not_stale_or_modify_a_skill(self):
        path = self.skill()
        before = path.read_bytes()
        health = self.health(events=[self.event(1, "failed", reason="behaviour_changed")])
        self.assertTrue(health.failed_recently)
        self.assertFalse(health.potentially_stale)
        self.assertFalse(health.needs_review)
        self.assertEqual(path.read_bytes(), before)

    def test_repeated_failures_require_independent_sessions(self):
        self.skill()
        first = self.event(1, "failed", reason="behaviour_changed")
        same_session = self.event(2, "failed", reason="behaviour_changed", session_id=first.session_id)
        independent = self.event(3, "failed", reason="behaviour_changed")
        single = self.health(events=[first, first, same_session])
        self.assertFalse(single.potentially_stale)
        repeated = self.health(events=[first, independent])
        self.assertTrue(repeated.potentially_stale)
        self.assertTrue(repeated.needs_review)
        self.assertIn("independent", " ".join(repeated.reasons).lower())
        self.assertIn("behaviour_changed", str(repeated.evidence))

    def test_repeated_unknown_failures_request_review_without_inventing_cause(self):
        self.skill()
        health = self.health(events=[self.event(1, "failed"), self.event(2, "failed")])
        self.assertTrue(health.needs_review)
        self.assertIn("unknown", str(health.evidence))
        self.assertNotIn("behaviour changed", " ".join(health.reasons).lower())

    def test_high_reported_confidence_remains_independent_of_failure_attention(self):
        self.skill()
        history = [
            self.event(index, timestamp=(NOW - timedelta(days=20)).isoformat())
            for index in range(30)
        ]
        health = self.health(events=[*history, self.event(30, "failed"), self.event(31, "failed")])
        self.assertEqual(health.confidence, "high")
        self.assertEqual(health.confidence_source, "reported_evidence")
        self.assertFalse(health.evidence["needs_review"])
        self.assertTrue(health.needs_review)
        self.assertTrue(health.potentially_stale)

    def test_recent_failure_signal_is_not_lost_when_session_confidence_is_capped(self):
        self.skill()
        history = [
            self.event(index, "failed", reason="behaviour_changed",
                       timestamp=(NOW - timedelta(days=40)).isoformat())
            for index in (1, 2)
        ]
        recent = [
            self.event(index + 2, "failed", session_id=f"session-{index}")
            for index in (1, 2)
        ]
        health = self.health(events=[*history, *recent])
        self.assertTrue(health.failed_recently)
        self.assertTrue(health.needs_review)
        self.assertTrue(health.potentially_stale)

    def test_attention_survives_weight_underflow_with_a_long_review_window(self):
        self.write("_meta/config.md", {
            "type": "meta", "version": 1,
            "feedback": {"half_life_days": 1, "recent_days": 3000},
        })
        self.skill()
        events = [
            self.event(index, "failed", timestamp=(NOW - timedelta(days=2000)).isoformat())
            for index in (1, 2)
        ]
        health = self.health(events=events)
        self.assertEqual(health.evidence["weighted_failed"], 0)
        self.assertEqual(health.evidence["recent_failed_sessions"], ["session-1", "session-2"])
        self.assertTrue(health.failed_recently)
        self.assertTrue(health.needs_review)
        self.assertTrue(health.potentially_stale)

    def test_mismatched_misapplied_and_future_failures_do_not_prove_skill_staleness(self):
        self.skill()
        for changes in (
            {"context": {"product": "another-product", "version": "2.1"}},
            {"reason": "misapplied"},
            {"reason": "context_mismatch"},
            {"timestamp": (NOW + timedelta(days=1)).isoformat()},
        ):
            with self.subTest(changes=changes):
                health = self.health(events=[
                    self.event(1, "failed", **changes), self.event(2, "failed", **changes),
                ])
                self.assertFalse(health.potentially_stale)

    def test_only_matching_skill_subjects_contribute_to_skill_health(self):
        self.skill()
        events = [
            self.event(1, "failed", subject_id="skills/other/check"),
            self.event(2, "failed", subject_type="knowledge"),
        ]
        health = self.health(events=events)
        self.assertFalse(health.failed_recently)
        self.assertEqual(health.confidence, "high")
        self.assertFalse(health.needs_review)

    def test_conflicting_event_ids_are_rejected_even_across_subject_groups(self):
        self.skill()
        with self.assertRaisesRegex(VaultError, "conflicting duplicate"):
            self.health(events=[
                self.event(1), self.event(1, "failed", subject_id="skills/other"),
            ])

    def test_dependency_outcomes_can_trigger_review_before_a_canonical_rewrite(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        path = self.knowledge()
        before = path.read_bytes()
        health = self.health(events=[
            self.event(index, "failed", subject_type="knowledge", subject_id="knowledge/patterns/base",
                       reason="behaviour_changed")
            for index in (1, 2)
        ])
        self.assertTrue(health.dependencies[0].needs_review)
        self.assertTrue(health.potentially_stale)
        self.assertEqual(path.read_bytes(), before)

    def test_policy_controls_skill_review_interval_and_failure_threshold(self):
        self.write("_meta/config.md", {
            "type": "meta", "version": 1,
            "feedback": {"skill_review_days": 7, "skill_failure_threshold": 3},
        })
        self.skill(last_verified="2026-09-01")
        self.assertTrue(self.health().potentially_stale)
        self.skill()
        two = [self.event(index, "failed") for index in (1, 2)]
        self.assertFalse(self.health(events=two).potentially_stale)
        self.assertTrue(self.health(events=[*two, self.event(3, "failed")]).potentially_stale)

    def test_batch_assessment_reuses_dependency_reads_and_consumes_events_once(self):
        dependency = self.knowledge()
        for index in range(12):
            self.skill(f"skills/check-{index}.md", depends_on=["knowledge/patterns/base"])
        with patch.object(skill_health.notes, "load_note", wraps=skill_health.notes.load_note) as load:
            results = skill_health.assess_skills(
                self.vault, context=self.context, now=NOW, events=iter(()),
            )
        self.assertEqual(len(results), 12)
        reads = [call for call in load.call_args_list if call.args[0] == dependency]
        self.assertEqual(len(reads), 1)
        self.assertEqual(
            [result.subject_id for result in results],
            sorted(result.subject_id for result in results),
        )

    def test_distinct_bare_dependencies_build_one_shared_filename_index(self):
        for index in range(12):
            self.knowledge(f"knowledge/patterns/base-{index}.md")
            self.skill(f"skills/check-{index}.md", depends_on=[f"base-{index}"])
        with (
            patch.object(skill_health, "_markdown_paths", wraps=skill_health._markdown_paths) as paths,
            patch.object(skill_health.notes, "resolve_ref", wraps=skill_health.notes.resolve_ref) as resolve,
        ):
            results = skill_health.assess_skills(
                self.vault, context=self.context, now=NOW, events=[],
            )
        self.assertEqual(len(results), 12)
        self.assertEqual(len([call for call in paths.call_args_list if call.args[1] == "knowledge"]), 1)
        self.assertTrue(all("/" in call.args[1] for call in resolve.call_args_list))

    def test_default_evidence_collection_reads_journal_once_without_writes(self):
        self.skill()
        self.skill("skills/other.md")
        for session in ("journal-one", "journal-two"):
            skill_health.outcomes.record_outcome(
                self.vault, session_id=session, subject_type="skill", subject_id="check",
                outcome="failed", reason="behaviour_changed", context=self.context, now=NOW,
            )
        before = {
            path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        with patch.object(
            skill_health.outcomes, "collect_evidence", wraps=skill_health.outcomes.collect_evidence,
        ) as collect:
            results = skill_health.assess_skills(self.vault, context=self.context, now=NOW)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0].evidence["event_ids"]), 2)
        self.assertTrue(results[0].needs_review)
        self.assertEqual(results[1].confidence_source, "recorded_metadata")
        after = {
            path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_explicit_empty_events_do_not_load_the_journal(self):
        self.skill()
        with patch.object(skill_health.outcomes, "collect_evidence") as collect:
            health = self.health(events=[])
        collect.assert_not_called()
        self.assertEqual(health.confidence_source, "recorded_metadata")
        self.assertEqual(health.evidence["weighted_held"], 0)
        self.assertEqual(health.confidence, "high")

    def test_explanations_are_json_serializable_and_detached_from_result(self):
        self.skill()
        health = self.health(events=[self.event(1)])
        original = health.as_dict()
        encoded = json.loads(json.dumps(original))
        self.assertEqual(encoded, original)
        original["evidence"]["reasons"].append("caller edit")
        self.assertNotIn("caller edit", health.evidence["reasons"])

    def test_assessment_is_repeatable_explainable_and_read_only(self):
        self.skill(depends_on=["knowledge/patterns/base"])
        self.knowledge(status="stale")
        events = [self.event(1, "failed"), self.event(2, "partial")]
        before = {
            path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        first = self.health(events=events).as_dict()
        second = self.health(events=iter(events)).as_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["subject_id"], first["reference"])
        self.assertIn("knowledge/patterns/base", str(first["reasons"]))
        self.assertIn("event-1", str(first["evidence"]))
        after = {
            path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
