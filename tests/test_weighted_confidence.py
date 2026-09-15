import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from memory_mesh.applicability import match_applicability
from memory_mesh.confidence import evaluate_evidence
from memory_mesh.config import VaultError
from memory_mesh.feedback_config import FeedbackPolicy
from memory_mesh.outcome_types import OutcomeEvent

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
APPLIES = {"product": "example", "version": ">=2026-01"}


def outcome(
    name, value="held", *, days=0, reason=None, session=None, context=None,
    subject_type="knowledge", subject_id=None, timestamp=None,
):
    return OutcomeEvent(
        event_id=name, timestamp=timestamp or (NOW - timedelta(days=days)).isoformat(),
        session_id=session or name, subject_type=subject_type,
        subject_id=subject_id or (
            "knowledge/patterns/example" if subject_type == "knowledge"
            else "skills/example"
        ),
        outcome=value, reason=reason,
        context={"product": "example", "version": "2026-09"} if context is None else context,
    )


class TestWeightedConfidence(unittest.TestCase):
    def test_decay_is_monotonic_and_halves_at_configured_half_life(self):
        weights = [
            evaluate_evidence([outcome(f"e-{days}", days=days)], APPLIES, now=NOW).weighted_held
            for days in (0, 90, 180)
        ]
        self.assertEqual(weights, [1.0, 0.5, 0.25])
        shorter = evaluate_evidence(
            [outcome("old", days=90)], APPLIES, now=NOW,
            policy=FeedbackPolicy(half_life_days=45),
        )
        self.assertEqual(shorter.weighted_held, 0.25)

    def test_confidence_uses_weighted_support_and_not_unclear_votes(self):
        events = [outcome(f"held-{i}") for i in range(4)]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.confidence, "high")
        result = evaluate_evidence(
            events + [outcome(f"unclear-{i}", "unclear") for i in range(20)],
            APPLIES, now=NOW,
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.weighted_unclear, 20.0)
        self.assertEqual(result.effective_evidence, 4.0)
        self.assertEqual(
            evaluate_evidence([outcome("one")], APPLIES, now=NOW).confidence,
            "medium",
        )

    def test_recent_independent_behaviour_changes_override_old_popularity_for_review(self):
        old = [outcome(f"old-{i}", days=720) for i in range(100)]
        failures = [
            outcome(f"failed-{i}", "failed", days=i, reason="behaviour_changed")
            for i in range(2)
        ]
        result = evaluate_evidence(old + failures, APPLIES, now=NOW)
        self.assertTrue(result.needs_review)
        self.assertEqual(result.recent_behaviour_changes, 2)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.counts["held"], 100)
        self.assertEqual(len(result.event_ids), 102)
        self.assertEqual(len(result.contributions), 102)
        self.assertTrue(any("behaviour_changed" in reason for reason in result.reasons))

    def test_review_remains_separate_from_historically_high_confidence(self):
        events = [outcome(f"old-{i}", days=180) for i in range(200)]
        events += [
            outcome(f"failed-{i}", "failed", reason="behaviour_changed")
            for i in range(2)
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.confidence, "high")
        self.assertTrue(result.needs_review)

    def test_one_session_is_not_independent_repeated_evidence(self):
        events = [
            outcome(f"failure-{i}", "failed", session="one-session", reason="behaviour_changed")
            for i in range(10)
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.recent_behaviour_changes, 1)
        self.assertFalse(result.needs_review)
        self.assertEqual(result.weighted_failed, 1.0)
        self.assertEqual(result.counts["failed"], 10)
        successes = [
            outcome(f"held-{i}", session="one-session") for i in range(10)
        ]
        result = evaluate_evidence(successes, APPLIES, now=NOW)
        self.assertEqual(result.weighted_held, 1.0)
        self.assertEqual(result.confidence, "medium")

    def test_reason_weights_distinguish_change_misapplication_and_uncertainty(self):
        expected = {
            "behaviour_changed": 1.0, "unknown": 0.5,
            "insufficient_information": 0.25,
            "misapplied": 0.1, "context_mismatch": 0.1,
        }
        for reason, weight in expected.items():
            with self.subTest(reason=reason):
                result = evaluate_evidence(
                    [outcome("failure", "failed", reason=reason)], APPLIES, now=NOW,
                )
                self.assertEqual(result.weighted_failed, weight)
                self.assertFalse(result.needs_review)
        default = evaluate_evidence(
            [outcome("failure", "failed")], APPLIES, now=NOW,
        )
        self.assertEqual(default.weighted_failed, expected["unknown"])

    def test_misapplication_punishes_confidence_less_than_behaviour_change(self):
        held = [outcome(f"held-{i}") for i in range(4)]
        changed = evaluate_evidence(
            held + [outcome("failed", "failed", reason="behaviour_changed")],
            APPLIES, now=NOW,
        )
        misapplied = evaluate_evidence(
            held + [outcome("failed", "failed", reason="misapplied")],
            APPLIES, now=NOW,
        )
        self.assertEqual(changed.confidence, "medium")
        self.assertEqual(misapplied.confidence, "high")

    def test_context_weights_distinguish_unknown_from_mismatch(self):
        policy = FeedbackPolicy(unknown_context_weight=0.4, out_of_context_weight=0.05)
        for context, expected in (
            ({}, 0.4), ({"product": "example"}, 0.4),
            ({"product": "other"}, 0.05),
            ({"product": "example", "version": "2025-12"}, 0.05),
        ):
            with self.subTest(context=context):
                events = [
                    outcome(f"failed-{i}", "failed", reason="behaviour_changed", context=context)
                    for i in range(2)
                ]
                result = evaluate_evidence(events, APPLIES, now=NOW, policy=policy)
                self.assertAlmostEqual(result.weighted_failed, expected * 2)
                self.assertEqual(result.recent_behaviour_changes, 0)
                self.assertFalse(result.needs_review)

    def test_out_of_context_success_does_not_verify_or_support_the_claim(self):
        result = evaluate_evidence(
            [outcome("outside", context={"product": "other"})], APPLIES, now=NOW,
        )
        self.assertEqual(result.weighted_held, 0)
        self.assertIsNone(result.last_verified)
        unknown = evaluate_evidence(
            [outcome(f"unknown-{i}", context={}) for i in range(20)], APPLIES, now=NOW,
        )
        self.assertEqual(unknown.weighted_held, 10)
        self.assertNotEqual(unknown.confidence, "high")
        self.assertIsNone(unknown.last_verified)

    def test_missing_applicability_is_unrestricted(self):
        result = evaluate_evidence([outcome("held", context={})], now=NOW)
        self.assertEqual(result.weighted_held, 1)
        self.assertEqual(result.last_verified, NOW.date().isoformat())

    def test_expired_calendar_window_preserves_historically_matched_evidence(self):
        metadata = {"tools": ["example"], "from": "2026-06", "to": "2026-08"}
        context = {"tool": "example"}
        events = [
            outcome("historical", timestamp="2026-08-31T12:00:00Z", context=context),
            outcome("outside", context=context),
        ]
        self.assertEqual(match_applicability(metadata, context, now=NOW).state, "mismatch")
        result = evaluate_evidence(events, metadata, now=NOW)
        self.assertEqual(result.contributions[0].applicability.state, "match")
        self.assertEqual(result.contributions[1].applicability.state, "mismatch")
        self.assertAlmostEqual(result.weighted_held, 2 ** (-14 / 90))
        self.assertEqual(result.last_verified, "2026-08-31")
        self.assertEqual(result.counts["held"], 2)
        self.assertEqual(result.event_ids, ("historical", "outside"))

    def test_recent_failure_sessions_match_calendar_at_event_time(self):
        metadata = {"from": "2026-08", "to": "2026-08"}
        events = [
            outcome(f"changed-{day}", "failed", reason="behaviour_changed",
                    timestamp=f"2026-08-{day}T12:00:00Z", context={})
            for day in (30, 31)
        ]
        self.assertEqual(match_applicability(metadata, now=NOW).state, "mismatch")
        result = evaluate_evidence(events, metadata, now=NOW)
        self.assertEqual(result.recent_behaviour_changes, 2)
        self.assertTrue(result.needs_review)
        self.assertEqual(result.recent_failed_sessions, ("changed-30", "changed-31"))
        self.assertTrue(all(item.applicability.state == "match" for item in result.contributions))

    def test_historical_calendar_match_does_not_invent_explicit_version_context(self):
        metadata = {"from": "2026-06", "to": "2026-08", "version": ">=1.2"}
        event = outcome("historical", timestamp="2026-08-31T12:00:00Z", context={})
        result = evaluate_evidence([event], metadata, now=NOW)
        self.assertEqual(result.contributions[0].applicability.state, "unknown")
        self.assertAlmostEqual(result.weighted_held, 0.5 * 2 ** (-14 / 90))
        self.assertIsNone(result.last_verified)

    def test_tolerated_future_calendar_clock_is_clamped_before_matching(self):
        now = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)
        event = outcome("near", timestamp="2026-09-01T00:01:00Z", context={})
        result = evaluate_evidence([event], {"to": "2026-08"}, now=now)
        self.assertEqual(result.contributions[0].applicability.state, "match")
        self.assertEqual(result.weighted_held, 1)
        self.assertEqual(result.last_verified, "2026-08-31")

    def test_product_does_not_fabricate_matched_legacy_host_evidence(self):
        metadata = {"tools": ["github-copilot"]}
        for context, expected_weight in (
            ({"product": "github-copilot"}, 0.5),
            ({"tool": "other-host", "product": "github-copilot"}, 0.1),
        ):
            with self.subTest(context=context):
                events = [
                    outcome(f"failure-{i}", "failed", reason="behaviour_changed", context=context)
                    for i in range(2)
                ]
                result = evaluate_evidence(events, metadata, now=NOW)
                self.assertEqual(result.weighted_failed, 2 * expected_weight)
                self.assertEqual(result.recent_behaviour_changes, 0)
                self.assertFalse(result.needs_review)

    def test_not_applicable_and_skill_partial_are_not_success(self):
        result = evaluate_evidence(
            [outcome("not-used", "not-applicable")], APPLIES, now=NOW,
        )
        self.assertEqual(result.effective_evidence, 0)
        self.assertEqual(result.counts["not-applicable"], 1)
        self.assertIsNone(result.last_verified)
        partial = evaluate_evidence(
            [outcome("partial", "partial", subject_type="skill")], APPLIES, now=NOW,
        )
        self.assertEqual(partial.weighted_held, 0)
        self.assertEqual(partial.weighted_failed, 0)
        self.assertEqual(partial.weighted_unclear, 1)
        self.assertEqual(partial.effective_evidence, 0)
        self.assertEqual(partial.counts["partial"], 1)
        succeeded = evaluate_evidence(
            [outcome("success", "succeeded", subject_type="skill")], APPLIES, now=NOW,
        )
        self.assertEqual(succeeded.weighted_held, 1)
        self.assertEqual(succeeded.counts["succeeded"], 1)
        self.assertTrue(any("execution" in reason for reason in succeeded.reasons))

    def test_review_recent_window_and_threshold_are_configurable(self):
        events = [
            outcome(f"failed-{i}", "failed", days=20, reason="behaviour_changed")
            for i in range(2)
        ]
        self.assertTrue(evaluate_evidence(events, APPLIES, now=NOW).needs_review)
        self.assertFalse(evaluate_evidence(
            events, APPLIES, now=NOW, policy=FeedbackPolicy(recent_days=10),
        ).needs_review)
        self.assertFalse(evaluate_evidence(
            events, APPLIES, now=NOW,
            policy=FeedbackPolicy(behaviour_change_failures=3),
        ).needs_review)
        boundary = [outcome("failed", "failed", days=30, reason="behaviour_changed")]
        self.assertTrue(evaluate_evidence(
            boundary, APPLIES, now=NOW,
            policy=FeedbackPolicy(behaviour_change_failures=1),
        ).needs_review)

    def test_recent_failed_sessions_include_eligible_reports_not_only_behaviour_changes(self):
        events = [
            outcome("unknown", "failed", subject_type="skill"),
            outcome("insufficient", "failed", days=30, reason="insufficient_information", subject_type="skill"),
            outcome("changed", "failed", reason="behaviour_changed", subject_type="skill"),
            outcome("misapplied", "failed", reason="misapplied", subject_type="skill"),
            outcome("context-mismatch", "failed", reason="context_mismatch", subject_type="skill"),
            outcome("outside", "failed", context={"product": "other"}, subject_type="skill"),
            outcome("unknown-context", "failed", context={}, subject_type="skill"),
            outcome("old", "failed", days=31, subject_type="skill"),
            outcome("future", "failed", days=-1, subject_type="skill"),
            outcome("success", "succeeded", subject_type="skill"),
            outcome("partial", "partial", subject_type="skill"),
        ]
        events += [
            replace(events[0]),
            outcome("same-session", "failed", session="unknown", subject_type="skill"),
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.recent_failed_sessions, ("changed", "insufficient", "unknown"))
        self.assertEqual(result.recent_behaviour_changes, 1)
        self.assertEqual(
            result.as_dict()["recent_failed_sessions"],
            ["changed", "insufficient", "unknown"],
        )
        contributions = {item.event.event_id: item for item in result.contributions}
        self.assertTrue(contributions["future"].future_excluded)
        self.assertFalse(contributions["old"].future_excluded)
        self.assertTrue(contributions["future"].as_dict()["future_excluded"])
        shorter = evaluate_evidence(
            events, APPLIES, now=NOW, policy=FeedbackPolicy(recent_days=10),
        )
        self.assertEqual(shorter.recent_failed_sessions, ("changed", "unknown"))

    def test_general_failure_attention_is_independent_of_confidence(self):
        events = [
            outcome(f"held-{i}", "succeeded", days=180, subject_type="skill")
            for i in range(100)
        ]
        events += [
            outcome(f"failed-{i}", "failed", subject_type="skill")
            for i in range(2)
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.confidence, "high")
        self.assertFalse(result.needs_review)
        self.assertEqual(len(result.recent_failed_sessions), 2)

    def test_session_weight_cap_does_not_hide_eligible_failure_reports(self):
        events = [
            outcome("changed", "failed", days=29, session="shared", reason="behaviour_changed"),
            outcome("misapplied", "failed", session="shared", reason="misapplied"),
        ]
        result = evaluate_evidence(
            events, APPLIES, now=NOW, policy=FeedbackPolicy(half_life_days=1),
        )
        self.assertFalse(result.contributions[0].included)
        self.assertFalse(result.contributions[0].future_excluded)
        self.assertEqual(result.recent_failed_sessions, ("shared",))

    def test_recent_failed_sessions_obey_the_shared_future_clock_policy(self):
        events = [
            outcome("near", "failed", timestamp=(NOW + timedelta(seconds=300)).isoformat()),
            outcome("far", "failed", timestamp=(NOW + timedelta(seconds=301)).isoformat()),
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.recent_failed_sessions, ("near",))
        strict = evaluate_evidence(
            events, APPLIES, now=NOW, policy=FeedbackPolicy(future_tolerance_seconds=0),
        )
        self.assertEqual(strict.recent_failed_sessions, ())

    def test_zero_evidence_does_not_inherit_prior_authority(self):
        result = evaluate_evidence([], APPLIES, now=NOW, prior_confidence="high")
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.effective_evidence, 0)
        self.assertEqual(result.counts["held"], 0)
        self.assertEqual(result.event_ids, ())
        self.assertIsNone(result.last_verified)
        self.assertFalse(result.needs_review)

    def test_prior_confidence_cannot_compound_repeated_projections(self):
        events = [outcome(f"held-{i}") for i in range(4)]
        events.append(outcome("failed", "failed", reason="behaviour_changed"))
        first = evaluate_evidence(events, APPLIES, now=NOW, prior_confidence="high")
        replay = evaluate_evidence(
            events, APPLIES, now=NOW, prior_confidence=first.confidence,
        )
        self.assertEqual(first.confidence, replay.confidence)
        self.assertEqual(first.effective_evidence, replay.effective_evidence)
        self.assertFalse(replay.needs_review)

    def test_future_tolerance_is_bounded_and_never_future_dates_verification(self):
        now = NOW.replace(hour=23, minute=59)
        near = outcome("near", timestamp=(now + timedelta(seconds=300)).isoformat())
        result = evaluate_evidence([near], APPLIES, now=now)
        self.assertEqual(result.weighted_held, 1)
        self.assertEqual(result.last_verified, now.date().isoformat())
        far = outcome("far", timestamp=(now + timedelta(seconds=301)).isoformat())
        result = evaluate_evidence([far], APPLIES, now=now)
        self.assertEqual(result.effective_evidence, 0)
        self.assertIsNone(result.last_verified)
        self.assertEqual(result.event_ids, ("far",))
        self.assertEqual(result.counts["held"], 1)
        self.assertTrue(any("future" in reason for reason in result.reasons))
        self.assertEqual(result.contributions[0].event.timestamp, far.timestamp)
        strict = evaluate_evidence(
            [near], APPLIES, now=now,
            policy=FeedbackPolicy(future_tolerance_seconds=0),
        )
        self.assertEqual(strict.weighted_held, 0)

    def test_future_failures_cannot_fabricate_behaviour_change(self):
        events = [
            outcome(
                f"future-{i}", "failed", days=-2, reason="behaviour_changed",
            ) for i in range(2)
        ]
        result = evaluate_evidence(events, APPLIES, now=NOW)
        self.assertEqual(result.weighted_failed, 0)
        self.assertEqual(result.recent_behaviour_changes, 0)

    def test_invalid_and_naive_timestamps_are_rejected(self):
        for timestamp in ("not-a-time", "2026-09-14", "2026-09-14T12:00:00"):
            with self.subTest(timestamp=timestamp), self.assertRaises(VaultError):
                evaluate_evidence([outcome("bad", timestamp=timestamp)], now=NOW)
        with self.assertRaises(VaultError):
            evaluate_evidence([], now=NOW.replace(tzinfo=None))
        result = evaluate_evidence([], now=date(2026, 9, 14))
        self.assertEqual(result.confidence, "low")

    def test_duplicate_ids_are_counted_once_and_conflicts_rejected(self):
        event = outcome("same")
        result = evaluate_evidence([event, replace(event)], APPLIES, now=NOW)
        self.assertEqual(result.weighted_held, 1)
        self.assertEqual(result.counts["held"], 1)
        self.assertEqual(result.event_ids, ("same",))
        self.assertEqual(len(result.contributions), 1)
        for other in (
            replace(event, outcome="failed"),
            replace(event, timestamp=(NOW - timedelta(days=1)).isoformat()),
            replace(event, context={"product": "other"}),
        ):
            with self.subTest(other=other), self.assertRaises(VaultError):
                evaluate_evidence([event, other], APPLIES, now=NOW)

    def test_mixed_subjects_and_routing_outcomes_cannot_inflate_confidence(self):
        for events in (
            [outcome("one"), outcome("two", subject_id="knowledge/patterns/other")],
            [outcome("one"), outcome("two", "succeeded", subject_type="skill")],
            [outcome("one", "useful", subject_type="recall")],
        ):
            with self.subTest(events=events), self.assertRaises(VaultError):
                evaluate_evidence(events, APPLIES, now=NOW)

    def test_invalid_direct_policy_values_fail_clearly(self):
        for policy in (
            FeedbackPolicy(half_life_days=0),
            FeedbackPolicy(half_life_days=float("nan")),
            FeedbackPolicy(half_life_days=float("inf")),
            FeedbackPolicy(unknown_context_weight=-0.1),
            FeedbackPolicy(out_of_context_weight=1.1),
            FeedbackPolicy(recent_days=0),
            FeedbackPolicy(behaviour_change_failures=0),
            FeedbackPolicy(future_tolerance_seconds=-1),
        ):
            with self.subTest(policy=policy), self.assertRaises(VaultError):
                evaluate_evidence([], now=NOW, policy=policy)
        with self.assertRaises(VaultError):
            evaluate_evidence([], now=NOW, prior_confidence="validated")

    def test_serialization_is_inspectable_deterministic_and_does_not_mutate_events(self):
        events = [
            outcome("held", days=1), outcome("unclear", "unclear"),
            outcome("failed", "failed", reason="misapplied"),
        ]
        original = [event.as_dict() for event in events]
        first = evaluate_evidence(iter(events), APPLIES, now=NOW)
        second = evaluate_evidence(reversed(events), APPLIES, now=NOW)
        self.assertEqual(first.as_dict(), second.as_dict())
        encoded = json.loads(json.dumps(first.as_dict()))
        self.assertEqual(encoded["counts"]["held"], 1)
        self.assertEqual(len(encoded["contributions"]), 3)
        self.assertEqual(encoded["contributions"][0]["event"]["timestamp"], events[0].timestamp)
        self.assertEqual([event.as_dict() for event in events], original)
        with self.assertRaises(TypeError):
            first.counts["held"] = 100


if __name__ == "__main__":
    unittest.main()
