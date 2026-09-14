"""Synthetic, in-memory contract tests; these are not pilot benchmarks."""

import copy
import json
import unittest
from unittest.mock import patch

from memory_mesh.config import VaultError
from memory_mesh.reuse_evaluation import EvaluationError, evaluate_runs


def run_row(**changes):
    row = {
        "case_id": "case-a",
        "family": "family-a",
        "trial_id": "trial-1",
        "arm": "native",
        "accepted": True,
        "active_ms": 100,
        "model_cost": 8,
        "memory_cost": 2,
        "review_seconds": 10,
        "currency": "USD",
        "cost_source": "synthetic billing fixture",
    }
    row.update(changes)
    return row


def coverage(measured, total):
    return {
        "measured_count": measured,
        "total_count": total,
        "fraction": measured / total if total else None,
    }


class TestEvaluationValidation(unittest.TestCase):
    def test_error_is_a_vault_error(self):
        self.assertTrue(issubclass(EvaluationError, VaultError))

    def test_input_must_be_a_list(self):
        for value in (None, {}, {"runs": []}, (), "", 1, True):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs(value)

    def test_each_run_must_be_a_dictionary(self):
        for value in (None, [], (), "private input", 1, False):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([value])

    def test_all_base_fields_are_required_even_when_null(self):
        for field in run_row():
            with self.subTest(field=field):
                row = run_row()
                del row[field]
                with self.assertRaises(EvaluationError):
                    evaluate_runs([row])

    def test_unexpected_fields_and_nonstring_keys_are_rejected(self):
        for key in ("prompt", "lesson_id", "verified", "status", 1, None):
            with self.subTest(key=key):
                row = run_row()
                row[key] = "DO_NOT_ECHO_PAYLOAD"
                with self.assertRaises(EvaluationError) as caught:
                    evaluate_runs([row])
                self.assertNotIn("DO_NOT_ECHO_PAYLOAD", str(caught.exception))

    def test_safe_ascii_identifiers_are_bounded_and_not_paths(self):
        for field in ("case_id", "family", "trial_id"):
            for value in (
                "", "a" * 101, " a", "a ", "two words", "a\nb", "a\rb",
                "a\x00b", "a\u2028b", "café", "case/1", "case\\1",
                "../escape", ".", "..", "*", "-leading", "_leading",
                ".leading", "case:1", None, 1, True, [],
            ):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(EvaluationError):
                        evaluate_runs([run_row(**{field: value})])

    def test_identifier_boundaries_are_valid(self):
        report = evaluate_runs([
            run_row(case_id="a" * 100, family="Family_1.v-2", trial_id="0"),
        ])
        self.assertEqual(report["arms"]["native"]["run_count"], 1)

    def test_only_declared_arms_are_valid(self):
        for value in ("V2", "baseline", "", None, 2, True, []):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(arm=value)])

    def test_accepted_requires_an_explicit_boolean(self):
        for value in (0, 1, None, "false", "true", [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(accepted=value)])

    def test_critical_failure_is_boolean_or_null_not_truthiness(self):
        for value in (0, 1, "false", "unknown", [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(critical_failure=value)])

    def test_numeric_fields_reject_bool_nonfinite_negative_and_other_types(self):
        for field in ("active_ms", "model_cost", "memory_cost", "review_seconds"):
            for value in (
                True, False, float("nan"), float("inf"), -float("inf"),
                -1, -0.01, "1", [], {}, complex(1, 0),
            ):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(EvaluationError):
                        evaluate_runs([run_row(**{field: value})])

    def test_unrepresentably_large_numbers_fail_safely(self):
        for field in ("active_ms", "model_cost", "memory_cost", "review_seconds"):
            with self.subTest(field=field):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(**{field: 10 ** 1000})])

    def test_overflowing_aggregates_fail_instead_of_returning_infinity(self):
        for changes in (
            {"model_cost": 1e308, "memory_cost": 1e308},
            {"review_seconds": 1e308},
        ):
            with self.subTest(changes=changes):
                rows = [
                    run_row(trial_id="trial-1", **changes),
                    run_row(trial_id="trial-2", **changes),
                ]
                with self.assertRaises(EvaluationError):
                    evaluate_runs(rows)

    def test_currency_must_be_three_uppercase_ascii_letters_or_null(self):
        for value in ("usd", "US", "USDD", "US1", "ÜSD", "USD\n", "", 1, []):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(currency=value)])

    def test_each_measured_cost_component_even_zero_needs_currency_and_source(self):
        for field in ("model_cost", "memory_cost"):
            for value in (0, 1.25):
                for missing in ("currency", "cost_source"):
                    with self.subTest(field=field, value=value, missing=missing):
                        row = run_row(model_cost=None, memory_cost=None)
                        row[field] = value
                        row[missing] = None
                        with self.assertRaises(EvaluationError):
                            evaluate_runs([row])

    def test_cost_provenance_is_nonblank_text_not_a_truthy_value(self):
        for value in ("", " ", "\t\n", 1, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(cost_source=value)])

    def test_null_billing_may_have_no_currency_or_provenance(self):
        report = evaluate_runs([
            run_row(model_cost=None, memory_cost=None,
                    currency=None, cost_source=None),
        ])
        self.assertIsNone(report["currency"])
        self.assertIsNone(report["arms"]["native"]["cost"]["total_spending"])

    def test_incompatible_currencies_are_rejected_even_without_matched_cases(self):
        for rows in (
            [run_row(), run_row(case_id="case-b", arm="v2", currency="EUR")],
            [run_row(), run_row(trial_id="trial-2", currency="EUR")],
            [
                run_row(model_cost=None, memory_cost=None, currency="USD"),
                run_row(case_id="case-b", model_cost=None,
                        memory_cost=None, currency="EUR"),
            ],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(EvaluationError):
                    evaluate_runs(rows)

    def test_duplicate_logical_run_is_rejected_even_with_different_measurements(self):
        for second in (run_row(), run_row(accepted=False, model_cost=100)):
            with self.subTest(second=second):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(), second])

    def test_one_case_cannot_change_family_across_arms_or_trials(self):
        for second in (
            run_row(arm="v2", family="family-b"),
            run_row(trial_id="trial-2", family="family-b"),
        ):
            with self.subTest(second=second):
                with self.assertRaises(EvaluationError):
                    evaluate_runs([run_row(), second])

    def test_ten_thousand_runs_are_allowed_but_more_are_rejected(self):
        report = evaluate_runs([
            run_row(case_id=f"case-{number}") for number in range(10000)
        ])
        self.assertEqual(report["run_count"], 10000)
        self.assertEqual(report["samples"]["case_count"], 10000)
        with self.assertRaises(EvaluationError):
            evaluate_runs([run_row()] * 10001)

    def test_error_messages_do_not_echo_invalid_values_or_valid_private_ids(self):
        marker = "DO_NOT_ECHO_PRIVATE"
        for rows in (
            [run_row(case_id=marker + "\n")],
            [run_row(cost_source=marker, currency=marker)],
            [run_row(case_id=marker), run_row(case_id=marker)],
            [run_row(case_id=marker), run_row(case_id=marker, arm="v2",
                                           family=marker)],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(EvaluationError) as caught:
                    evaluate_runs(rows)
                self.assertNotIn(marker, str(caught.exception))


class TestArmSummaries(unittest.TestCase):
    def test_empty_input_has_no_invented_measurements(self):
        report = evaluate_runs([])
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["design"], "observational")
        self.assertIs(report["causal_claims_supported"], False)
        self.assertEqual(report["run_count"], 0)
        self.assertIsNone(report["currency"])
        self.assertEqual(set(report["arms"]), {"native", "v1", "v2"})
        self.assertEqual(report["samples"]["case_count"], 0)
        for arm in report["arms"].values():
            self.assertEqual(arm["run_count"], 0)
            self.assertEqual(arm["accepted_count"], 0)
            self.assertIsNone(arm["accepted_rate"])
            self.assertIsNone(arm["cost"]["total_spending"])
            self.assertIsNone(arm["cost"]["cost_per_accepted_task"])
            self.assertIsNone(arm["cost"]["measured_component_subtotal"])
            self.assertIsNone(arm["critical_failures"]["measured_failure_count"])
            self.assertEqual(arm["critical_failures"]["coverage"], coverage(0, 0))
            self.assertIsNone(arm["active_ms"]["median"])
            self.assertIsNone(arm["review_seconds"]["total"])
            self.assertTrue(arm["warnings"])
        self.assertIn("observational", " ".join(report["warnings"]).lower())
        self.assertIn("lesson", " ".join(report["warnings"]).lower())

    def test_failed_and_no_match_attempts_contribute_to_all_spending(self):
        report = evaluate_runs([
            run_row(case_id="accepted", model_cost=2, memory_cost=1),
            run_row(case_id="failed", accepted=False, model_cost=4, memory_cost=2),
            run_row(case_id="no-match", accepted=False,
                    model_cost=5, memory_cost=3),
        ])
        arm = report["arms"]["native"]
        self.assertEqual(arm["run_count"], 3)
        self.assertEqual(arm["accepted_count"], 1)
        self.assertAlmostEqual(arm["accepted_rate"], 1 / 3)
        self.assertEqual(arm["cost"]["currency"], "USD")
        self.assertEqual(arm["cost"]["total_spending"], 17)
        self.assertEqual(arm["cost"]["cost_per_accepted_task"], 17)
        self.assertEqual(arm["cost"]["measured_component_subtotal"], 17)
        self.assertFalse(arm["cost"]["measured_component_subtotal_is_partial"])
        self.assertEqual(arm["cost"]["complete_run_coverage"], coverage(3, 3))

    def test_partial_components_do_not_combine_into_complete_billing(self):
        arm = evaluate_runs([
            run_row(accepted=False, model_cost=10, memory_cost=None),
            run_row(trial_id="trial-2", model_cost=None, memory_cost=2),
        ])["arms"]["native"]
        self.assertEqual(arm["cost"]["measured_component_subtotal"], 12)
        self.assertTrue(arm["cost"]["measured_component_subtotal_is_partial"])
        self.assertEqual(arm["cost"]["model_cost_coverage"], coverage(1, 2))
        self.assertEqual(arm["cost"]["memory_cost_coverage"], coverage(1, 2))
        self.assertEqual(arm["cost"]["complete_run_coverage"], coverage(0, 2))
        self.assertIsNone(arm["cost"]["total_spending"])
        self.assertIsNone(arm["cost"]["cost_per_accepted_task"])
        self.assertIn("billing", " ".join(arm["warnings"]).lower())

    def test_one_incomplete_attempt_makes_the_whole_arm_total_unknown(self):
        for component in ("model_cost", "memory_cost"):
            with self.subTest(component=component):
                arm = evaluate_runs([
                    run_row(),
                    run_row(trial_id="trial-2", accepted=False,
                            **{component: None}),
                ])["arms"]["native"]
                self.assertEqual(arm["cost"]["complete_run_coverage"], coverage(1, 2))
                self.assertIsNone(arm["cost"]["total_spending"])
                self.assertIsNone(arm["cost"]["cost_per_accepted_task"])
                self.assertTrue(arm["cost"]["measured_component_subtotal_is_partial"])

    def test_all_unknown_measurements_are_null_not_zero(self):
        arm = evaluate_runs([
            run_row(active_ms=None, model_cost=None, memory_cost=None,
                    review_seconds=None, currency=None, cost_source=None),
        ])["arms"]["native"]
        self.assertIsNone(arm["cost"]["total_spending"])
        self.assertIsNone(arm["cost"]["measured_component_subtotal"])
        self.assertIsNone(arm["cost"]["currency"])
        self.assertEqual(arm["cost"]["complete_run_coverage"], coverage(0, 1))
        self.assertIsNone(arm["active_ms"]["median"])
        self.assertIsNone(arm["review_seconds"]["median"])
        self.assertIsNone(arm["review_seconds"]["measured_subtotal"])
        self.assertIsNone(arm["review_seconds"]["total"])

    def test_explicit_zeroes_are_real_measurements(self):
        arm = evaluate_runs([
            run_row(active_ms=0, model_cost=0, memory_cost=0, review_seconds=0,
                    critical_failure=False),
        ])["arms"]["native"]
        self.assertEqual(arm["cost"]["total_spending"], 0)
        self.assertEqual(arm["cost"]["cost_per_accepted_task"], 0)
        self.assertEqual(arm["cost"]["complete_run_coverage"], coverage(1, 1))
        self.assertEqual(arm["active_ms"]["median"], 0)
        self.assertEqual(arm["review_seconds"]["total"], 0)
        self.assertEqual(arm["critical_failures"]["measured_failure_count"], 0)
        self.assertEqual(arm["critical_failures"]["coverage"], coverage(1, 1))

    def test_zero_successes_have_spending_but_no_cost_per_accepted_task(self):
        arm = evaluate_runs([
            run_row(accepted=False, model_cost=10, memory_cost=2),
            run_row(trial_id="trial-2", accepted=False, model_cost=20, memory_cost=3),
        ])["arms"]["native"]
        self.assertEqual(arm["accepted_rate"], 0)
        self.assertEqual(arm["cost"]["total_spending"], 35)
        self.assertIsNone(arm["cost"]["cost_per_accepted_task"])
        self.assertIn("accepted", " ".join(arm["warnings"]).lower())

    def test_active_and_review_time_have_separate_disclosed_coverage(self):
        arm = evaluate_runs([
            run_row(active_ms=100, review_seconds=None),
            run_row(trial_id="trial-2", active_ms=None, review_seconds=20),
            run_row(trial_id="trial-3", active_ms=300, review_seconds=40),
        ])["arms"]["native"]
        self.assertEqual(arm["active_ms"]["median"], 200)
        self.assertEqual(arm["active_ms"]["coverage"], coverage(2, 3))
        self.assertEqual(arm["review_seconds"]["median"], 30)
        self.assertEqual(arm["review_seconds"]["coverage"], coverage(2, 3))
        self.assertEqual(arm["review_seconds"]["measured_subtotal"], 60)
        self.assertIsNone(arm["review_seconds"]["total"])
        self.assertEqual(arm["cost"]["total_spending"], 30)
        self.assertIn("time", " ".join(arm["warnings"]).lower())

    def test_complete_review_time_total_includes_failed_runs(self):
        arm = evaluate_runs([
            run_row(review_seconds=10),
            run_row(trial_id="trial-2", accepted=False, review_seconds=30),
        ])["arms"]["native"]
        self.assertEqual(arm["review_seconds"]["total"], 40)
        self.assertEqual(arm["review_seconds"]["median"], 20)
        self.assertEqual(arm["review_seconds"]["coverage"], coverage(2, 2))
        self.assertEqual(arm["cost"]["total_spending"], 20)

    def test_missing_and_null_critical_checks_are_not_false(self):
        arm = evaluate_runs([
            run_row(),
            run_row(trial_id="trial-2", critical_failure=None),
        ])["arms"]["native"]
        self.assertIsNone(arm["critical_failures"]["measured_failure_count"])
        self.assertEqual(arm["critical_failures"]["coverage"], coverage(0, 2))
        self.assertIn("critical", " ".join(arm["warnings"]).lower())

    def test_partial_critical_checks_count_only_observed_failures(self):
        arm = evaluate_runs([
            run_row(critical_failure=True),
            run_row(trial_id="trial-2", critical_failure=False),
            run_row(trial_id="trial-3", critical_failure=None),
            run_row(trial_id="trial-4"),
        ])["arms"]["native"]
        self.assertEqual(arm["critical_failures"]["measured_failure_count"], 1)
        self.assertEqual(arm["critical_failures"]["coverage"], coverage(2, 4))

    def test_repeated_trials_do_not_inflate_case_or_family_counts(self):
        report = evaluate_runs([
            run_row(trial_id=f"trial-{trial}", arm=arm)
            for trial in range(5)
            for arm in ("native", "v1", "v2")
        ])
        self.assertEqual(report["run_count"], 15)
        self.assertEqual(report["samples"]["case_count"], 1)
        self.assertEqual(report["samples"]["case_trial_count"], 5)
        self.assertEqual(report["samples"]["repeated_trial_count"], 4)
        self.assertEqual(report["samples"]["family_count"], 1)
        self.assertEqual(report["samples"]["families"]["family-a"], {
            "run_count": 15, "case_count": 1, "case_trial_count": 5,
        })
        for arm in report["arms"].values():
            self.assertEqual(arm["samples"]["case_count"], 1)
            self.assertEqual(arm["samples"]["case_trial_count"], 5)
        for comparison in report["comparisons"].values():
            self.assertEqual(comparison["pair_count"], 5)
            self.assertEqual(comparison["samples"]["case_count"], 1)
            self.assertEqual(comparison["samples"]["repeated_trial_count"], 4)
        self.assertIn("transfer", " ".join(report["warnings"]).lower())

    def test_many_cases_in_one_family_do_not_imply_many_families(self):
        report = evaluate_runs([
            run_row(case_id=f"paraphrase-{number}") for number in range(20)
        ])
        self.assertEqual(report["samples"]["case_count"], 20)
        self.assertEqual(report["samples"]["family_count"], 1)
        self.assertEqual(report["samples"]["families"]["family-a"]["run_count"], 20)

    def test_floating_point_spending_is_stably_summed(self):
        arm = evaluate_runs([
            run_row(model_cost=0.1, memory_cost=0.2),
            run_row(trial_id="trial-2", model_cost=0.3, memory_cost=0.4),
        ])["arms"]["native"]
        self.assertEqual(arm["cost"]["total_spending"], 1.0)
        self.assertEqual(arm["cost"]["cost_per_accepted_task"], 0.5)

    def test_large_finite_active_median_does_not_overflow(self):
        arm = evaluate_runs([
            run_row(active_ms=1e308),
            run_row(trial_id="trial-2", active_ms=1e308),
        ])["arms"]["native"]
        self.assertEqual(arm["active_ms"]["median"], 1e308)


class TestPairedComparisons(unittest.TestCase):
    def test_paired_data_reports_acceptance_cost_and_within_pair_time_differences(self):
        rows = []
        for index, (native_ok, candidate_ok) in enumerate(
            ((True, True), (True, False), (False, True), (False, False))
        ):
            common = {
                "case_id": f"case-{index}",
                "family": "family-a" if index < 2 else "family-b",
                "critical_failure": False,
            }
            rows.extend([
                run_row(**common, arm="native", accepted=native_ok,
                        model_cost=8, memory_cost=2,
                        active_ms=(index + 1) * 100, review_seconds=(index + 1) * 10),
                run_row(**common, arm="v1", model_cost=7, memory_cost=1),
                run_row(**common, arm="v2", accepted=candidate_ok,
                        model_cost=4, memory_cost=2,
                        active_ms=(90, 110, 330, 340)[index],
                        review_seconds=(9, 11, 33, 34)[index]),
            ])
        report = evaluate_runs(rows)
        self.assertEqual(set(report["comparisons"]), {"native_vs_v2", "v1_vs_v2"})
        comparison = report["comparisons"]["native_vs_v2"]
        self.assertEqual(comparison["baseline_arm"], "native")
        self.assertEqual(comparison["candidate_arm"], "v2")
        self.assertEqual(comparison["pair_count"], 4)
        self.assertEqual(comparison["unmatched_counts"], {"baseline": 0, "candidate": 0})
        self.assertEqual(comparison["acceptance"], {
            "both_accepted": 1,
            "baseline_only": 1,
            "candidate_only": 1,
            "neither_accepted": 1,
            "baseline_accepted_count": 2,
            "candidate_accepted_count": 2,
            "baseline_accepted_rate": 0.5,
            "candidate_accepted_rate": 0.5,
            "candidate_minus_baseline_rate": 0.0,
        })
        self.assertEqual(comparison["cost"]["complete_pair_coverage"], coverage(4, 4))
        self.assertEqual(comparison["cost"]["baseline_total_spending"], 40)
        self.assertEqual(comparison["cost"]["candidate_total_spending"], 24)
        self.assertEqual(comparison["cost"]["baseline_cost_per_accepted_task"], 20)
        self.assertEqual(comparison["cost"]["candidate_cost_per_accepted_task"], 12)
        self.assertEqual(
            comparison["cost"]["candidate_minus_baseline_cost_per_accepted_task"], -8,
        )
        self.assertEqual(comparison["active_ms"], {
            "complete_pair_coverage": coverage(4, 4),
            "baseline_median": 250,
            "candidate_median": 220,
            "median_candidate_minus_baseline": -35,
        })
        self.assertEqual(comparison["review_seconds"]["median_candidate_minus_baseline"], -3.5)
        self.assertEqual(comparison["samples"]["case_count"], 4)
        self.assertEqual(comparison["samples"]["family_count"], 2)
        other = report["comparisons"]["v1_vs_v2"]
        self.assertEqual(other["cost"]["candidate_minus_baseline_cost_per_accepted_task"], 4)
        self.assertEqual(other["acceptance"]["candidate_minus_baseline_rate"], -0.5)

    def test_only_matching_case_and_trial_keys_enter_comparisons(self):
        rows = [
            run_row(case_id="paired", model_cost=8, memory_cost=2),
            run_row(case_id="paired", arm="v2", model_cost=4, memory_cost=2),
            run_row(case_id="baseline-extra", model_cost=1000, memory_cost=0),
            run_row(case_id="candidate-extra", arm="v2", model_cost=2000, memory_cost=0),
        ]
        report = evaluate_runs(rows)
        comparison = report["comparisons"]["native_vs_v2"]
        self.assertEqual(comparison["pair_count"], 1)
        self.assertEqual(comparison["unmatched_counts"], {"baseline": 1, "candidate": 1})
        self.assertEqual(comparison["cost"]["baseline_total_spending"], 10)
        self.assertEqual(comparison["cost"]["candidate_total_spending"], 6)
        self.assertEqual(report["arms"]["native"]["cost"]["total_spending"], 1010)
        self.assertEqual(report["arms"]["v2"]["cost"]["total_spending"], 2006)
        self.assertIn("unmatched", " ".join(comparison["warnings"]).lower())

    def test_matching_one_key_alone_does_not_make_a_pair(self):
        for candidate in (
            run_row(arm="v2", trial_id="trial-2"),
            run_row(arm="v2", case_id="case-b"),
        ):
            with self.subTest(candidate=candidate):
                comparison = evaluate_runs([
                    run_row(), candidate,
                ])["comparisons"]["native_vs_v2"]
                self.assertEqual(comparison["pair_count"], 0)
                self.assertEqual(comparison["unmatched_counts"], {
                    "baseline": 1, "candidate": 1,
                })
                self.assertIsNone(comparison["acceptance"]["candidate_minus_baseline_rate"])
                self.assertIsNone(comparison["cost"]["baseline_total_spending"])
                self.assertIsNone(comparison["active_ms"]["baseline_median"])
                self.assertEqual(comparison["cost"]["complete_pair_coverage"], coverage(0, 0))

    def test_missing_paired_billing_suppresses_both_sides_not_just_missing_side(self):
        for component in ("model_cost", "memory_cost"):
            with self.subTest(component=component):
                comparison = evaluate_runs([
                    run_row(),
                    run_row(arm="v2"),
                    run_row(trial_id="trial-2"),
                    run_row(arm="v2", trial_id="trial-2", **{component: None}),
                ])["comparisons"]["native_vs_v2"]
                self.assertEqual(comparison["cost"]["complete_pair_coverage"], coverage(1, 2))
                for field in (
                    "baseline_total_spending", "candidate_total_spending",
                    "baseline_cost_per_accepted_task", "candidate_cost_per_accepted_task",
                    "candidate_minus_baseline_cost_per_accepted_task",
                ):
                    self.assertIsNone(comparison["cost"][field])
                self.assertIn("billing", " ".join(comparison["warnings"]).lower())

    def test_disjoint_measured_subsets_are_not_compared(self):
        for field in ("active_ms", "review_seconds"):
            with self.subTest(field=field):
                report = evaluate_runs([
                    run_row(**{field: 100}),
                    run_row(arm="v2", **{field: None}),
                    run_row(trial_id="trial-2", **{field: None}),
                    run_row(arm="v2", trial_id="trial-2", **{field: 50}),
                ])
                self.assertEqual(report["arms"]["native"][field]["median"], 100)
                self.assertEqual(report["arms"]["v2"][field]["median"], 50)
                metric = report["comparisons"]["native_vs_v2"][field]
                self.assertEqual(metric["complete_pair_coverage"], coverage(0, 2))
                self.assertIsNone(metric["baseline_median"])
                self.assertIsNone(metric["candidate_median"])
                self.assertIsNone(metric["median_candidate_minus_baseline"])

    def test_even_partially_complete_paired_times_are_not_cherry_picked(self):
        for field in ("active_ms", "review_seconds"):
            with self.subTest(field=field):
                comparison = evaluate_runs([
                    run_row(),
                    run_row(arm="v2"),
                    run_row(trial_id="trial-2"),
                    run_row(arm="v2", trial_id="trial-2", **{field: None}),
                ])["comparisons"]["native_vs_v2"]
                self.assertEqual(comparison[field]["complete_pair_coverage"], coverage(1, 2))
                self.assertIsNone(comparison[field]["baseline_median"])
                self.assertIsNone(comparison[field]["candidate_median"])
                self.assertIsNone(comparison[field]["median_candidate_minus_baseline"])

    def test_zero_acceptance_never_produces_a_dollar_benefit(self):
        for baseline_ok, candidate_ok in ((False, True), (True, False), (False, False)):
            with self.subTest(baseline=baseline_ok, candidate=candidate_ok):
                comparison = evaluate_runs([
                    run_row(accepted=baseline_ok),
                    run_row(arm="v2", accepted=candidate_ok),
                ])["comparisons"]["native_vs_v2"]
                self.assertEqual(comparison["cost"]["baseline_total_spending"], 10)
                self.assertEqual(comparison["cost"]["candidate_total_spending"], 10)
                self.assertIsNone(
                    comparison["cost"]["candidate_minus_baseline_cost_per_accepted_task"],
                )
                if not baseline_ok:
                    self.assertIsNone(comparison["cost"]["baseline_cost_per_accepted_task"])
                if not candidate_ok:
                    self.assertIsNone(comparison["cost"]["candidate_cost_per_accepted_task"])

    def test_different_comparisons_disclose_their_own_family_cohorts(self):
        report = evaluate_runs([
            run_row(case_id="case-a", family="family-a"),
            run_row(case_id="case-a", family="family-a", arm="v2"),
            run_row(case_id="case-b", family="family-b", arm="v1"),
            run_row(case_id="case-b", family="family-b", arm="v2"),
        ])
        comparisons = report["comparisons"]
        self.assertEqual(set(comparisons["native_vs_v2"]["samples"]["families"]), {"family-a"})
        self.assertEqual(set(comparisons["v1_vs_v2"]["samples"]["families"]), {"family-b"})
        self.assertIn("cohort", " ".join(report["warnings"]).lower())

    def test_no_billing_on_either_side_has_no_currency_or_cost_delta(self):
        comparison = evaluate_runs([
            run_row(arm=arm, model_cost=None, memory_cost=None,
                    currency=None, cost_source=None)
            for arm in ("native", "v2")
        ])["comparisons"]["native_vs_v2"]
        self.assertIsNone(comparison["cost"]["currency"])
        self.assertIsNone(comparison["cost"]["candidate_minus_baseline_cost_per_accepted_task"])
        self.assertEqual(comparison["cost"]["complete_pair_coverage"], coverage(0, 1))


class TestEvaluationPurity(unittest.TestCase):
    def test_json_serializable_deterministic_and_does_not_mutate_or_echo_raw_rows(self):
        rows = [
            run_row(case_id="private-case-marker", family="family-z",
                    cost_source="private-provenance-marker"),
            run_row(case_id="private-case-marker", family="family-z", arm="v2"),
            run_row(case_id="another-case", family="family-a", arm="v1"),
        ]
        original = copy.deepcopy(rows)
        report = evaluate_runs(rows)
        self.assertEqual(rows, original)
        self.assertEqual(report, evaluate_runs(list(reversed(rows))))
        encoded = json.dumps(report, allow_nan=False)
        self.assertEqual(json.loads(encoded), report)
        self.assertNotIn("private-case-marker", encoded)
        self.assertNotIn("private-provenance-marker", encoded)

    def test_evaluation_does_not_use_files_network_or_subprocesses(self):
        rows = [run_row(), run_row(arm="v2")]
        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch("pathlib.Path.open", side_effect=AssertionError("path access")),
            patch("socket.socket", side_effect=AssertionError("network access")),
            patch("subprocess.Popen", side_effect=AssertionError("process access")),
        ):
            report = evaluate_runs(rows)
        self.assertEqual(report["comparisons"]["native_vs_v2"]["pair_count"], 1)

    def test_mutating_a_report_cannot_change_later_reports(self):
        rows = [run_row()]
        report = evaluate_runs(rows)
        report["warnings"].clear()
        report["arms"]["native"]["samples"]["families"].clear()
        later = evaluate_runs(rows)
        self.assertTrue(later["warnings"])
        self.assertEqual(later["arms"]["native"]["samples"]["family_count"], 1)
        self.assertIn("family-a", later["arms"]["native"]["samples"]["families"])


if __name__ == "__main__":
    unittest.main()
