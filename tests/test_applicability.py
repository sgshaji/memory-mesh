import json
import unittest
from datetime import date, datetime, timedelta, timezone

from memory_mesh.applicability import match_applicability


class TestApplicability(unittest.TestCase):
    def test_missing_metadata_is_explicitly_unrestricted(self):
        for metadata in (None, {}, {"tools": [], "from": None, "to": None}):
            with self.subTest(metadata=metadata):
                result = match_applicability(metadata)
                self.assertEqual(result.state, "match")
                self.assertIn("unrestricted", " ".join(result.reasons).lower())

    def test_product_matching_is_case_insensitive_but_not_guessed_from_tool(self):
        metadata = {"product": "Copilot-Studio"}
        self.assertEqual(
            match_applicability(metadata, {"product": "copilot-studio"}).state,
            "match",
        )
        self.assertEqual(
            match_applicability(metadata, {"product": "other"}).state, "mismatch",
        )
        self.assertEqual(
            match_applicability(metadata, {"tool": "copilot-studio"}).state,
            "unknown",
        )

    def test_missing_context_is_not_a_definite_mismatch(self):
        for context in (None, {}, {"product": ""}):
            with self.subTest(context=context):
                result = match_applicability({"product": "example"}, context)
                self.assertEqual(result.state, "unknown")
                self.assertIn("missing", " ".join(result.reasons).lower())

    def test_legacy_tools_match_only_the_actual_host(self):
        metadata = {"tools": ["github-copilot", "claude-code"]}
        for context in (
            {"tool": "Claude-Code"},
            {"tool": "github-copilot", "product": "copilot-studio"},
        ):
            with self.subTest(context=context):
                result = match_applicability(metadata, context)
                self.assertEqual(result.state, "match")
                self.assertIn(context["tool"], " ".join(result.reasons))
        self.assertEqual(match_applicability(metadata, {}).state, "unknown")
        result = match_applicability(
            metadata, {"tool": "other-host", "product": "claude-code"},
        )
        self.assertEqual(result.state, "mismatch")
        self.assertIn("other-host", " ".join(result.reasons))

    def test_product_cannot_fill_in_an_unknown_legacy_host(self):
        result = match_applicability(
            {"tools": ["claude-code"]}, {"product": "claude-code"},
        )
        self.assertEqual(result.state, "unknown")
        self.assertIn("context.tool", " ".join(result.reasons))
        self.assertIn("missing", " ".join(result.reasons))

    def test_product_is_optional_unless_declared_by_metadata(self):
        context = {"tool": "github-copilot"}
        metadata = {"tools": ["github-copilot"]}
        self.assertEqual(match_applicability(metadata, context).state, "match")
        metadata["product"] = "copilot-studio"
        result = match_applicability(metadata, context)
        self.assertEqual(result.state, "unknown")
        self.assertIn("context.product", " ".join(result.reasons))
        context["product"] = "copilot-studio"
        self.assertEqual(match_applicability(metadata, context).state, "match")

    def test_definite_dimension_mismatch_wins_over_missing_version(self):
        metadata = {"product": "example", "version": ">=2026-01"}
        result = match_applicability(metadata, {"product": "other"})
        self.assertEqual(result.state, "mismatch")
        self.assertTrue(any("version" in reason for reason in result.reasons))

    def test_numeric_range_boundaries_and_zero_padding(self):
        metadata = {"version": ">=1.2,<2.0"}
        for version, expected in (
            ("1.1.99", "mismatch"), ("1.2", "match"), ("1.2.0", "match"),
            ("1.9.99", "match"), ("1.10", "match"), ("2", "mismatch"),
            ("2.0.0", "mismatch"),
        ):
            with self.subTest(version=version):
                self.assertEqual(
                    match_applicability(metadata, {"version": version}).state,
                    expected,
                )

    def test_numeric_exact_and_exclusive_constraints(self):
        self.assertEqual(
            match_applicability({"version": "1.2"}, {"version": "1.2.0"}).state,
            "match",
        )
        for version, expected in (
            ("1.2", "mismatch"), ("1.2.1", "match"), ("1.3", "match"),
            ("1.3.1", "mismatch"),
        ):
            with self.subTest(version=version):
                self.assertEqual(
                    match_applicability(
                        {"version": ">1.2, <=1.3"}, {"version": version},
                    ).state, expected,
                )

    def test_date_style_month_and_day_boundaries(self):
        metadata = {"version": ">=2026-01, <=2026-02"}
        for version, expected in (
            ("2025-12", "mismatch"), ("2026-01", "match"),
            ("2026-01-01", "match"), ("2026-02-28", "match"),
            ("2026-03-01", "mismatch"),
        ):
            with self.subTest(version=version):
                self.assertEqual(
                    match_applicability(metadata, {"version": version}).state,
                    expected,
                )
        self.assertEqual(
            match_applicability(
                {"version": ">2026-02"}, {"version": "2026-02-28"},
            ).state, "mismatch",
        )

    def test_imprecise_month_cannot_prove_a_day_constraint(self):
        self.assertEqual(
            match_applicability(
                {"version": ">=2026-01-15"}, {"version": "2026-01"},
            ).state, "unknown",
        )
        self.assertEqual(
            match_applicability(
                {"version": "2026-01"}, {"version": "2026-01-15"},
            ).state, "match",
        )

    def test_legacy_calendar_bounds_are_inclusive_without_version_context(self):
        metadata = {"tools": ["example"], "from": "2026-01", "to": "2026-09"}
        for day, expected in (
            ("2025-12-31", "mismatch"), ("2026-01-01", "match"),
            ("2026-09-30", "match"), ("2026-10-01", "mismatch"),
        ):
            with self.subTest(day=day):
                self.assertEqual(
                    match_applicability(
                        metadata, {"tool": "example"}, now=date.fromisoformat(day),
                    ).state, expected,
                )

    def test_legacy_numeric_and_v_prefixed_bounds_require_observed_version(self):
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        for metadata in (
            {"from": "1.2", "to": "2.0"},
            {"from": "v1.2", "to": "v2.0"},
            {"from": "1.2", "to": "V2.0"},
        ):
            with self.subTest(metadata=metadata):
                self.assertEqual(match_applicability(metadata, now=now).state, "unknown")
                for version, expected in (
                    ("1.1", "mismatch"), ("v1.2", "match"),
                    ("V1.5.0", "match"), ("2.0.0", "match"), ("2.1", "mismatch"),
                ):
                    with self.subTest(version=version):
                        self.assertEqual(
                            match_applicability(metadata, {"version": version}, now=now).state,
                            expected,
                        )

    def test_expired_calendar_bound_wins_even_without_host_context(self):
        result = match_applicability(
            {"tools": ["example"], "to": "2026-08"}, now=date(2026, 9, 1),
        )
        self.assertEqual(result.state, "mismatch")
        self.assertIn("calendar", " ".join(result.reasons))
        self.assertIn("context.tool", " ".join(result.reasons))

    def test_calendar_month_end_includes_leap_day_and_entire_last_day(self):
        for year, last_day in ((2027, 28), (2028, 29)):
            metadata = {"from": f"{year}-02", "to": f"{year}-02"}
            with self.subTest(year=year):
                self.assertEqual(
                    match_applicability(
                        metadata, now=datetime(year, 2, 1, tzinfo=timezone.utc),
                    ).state, "match",
                )
                self.assertEqual(
                    match_applicability(
                        metadata, now=datetime(year, 2, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc),
                    ).state, "match",
                )
                self.assertEqual(
                    match_applicability(
                        metadata, now=datetime(year, 3, 1, tzinfo=timezone.utc),
                    ).state, "mismatch",
                )

    def test_calendar_day_bounds_are_inclusive_and_use_utc(self):
        metadata = {"from": "2026-01-01", "to": "2026-01-01"}
        for timestamp, expected in (
            ("2025-12-31T23:59:59Z", "mismatch"),
            ("2026-01-01T00:00:00Z", "match"),
            ("2026-01-01T23:59:59.999999Z", "match"),
            ("2026-01-02T00:00:00Z", "mismatch"),
            ("2026-01-02T00:30:00+01:00", "match"),
        ):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(
                    match_applicability(
                        metadata, now=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                    ).state,
                    expected,
                )

    def test_calendar_and_explicit_version_constraints_are_independent(self):
        metadata = {"from": "2026-01", "to": "2026-12", "version": ">=1.2,<2"}
        now = date(2026, 9, 14)
        self.assertEqual(match_applicability(metadata, now=now).state, "unknown")
        self.assertEqual(
            match_applicability(
                metadata, {"version": "1.3"}, now=now,
            ).state, "match",
        )
        self.assertEqual(
            match_applicability(
                metadata, {"version": "2.0"}, now=now,
            ).state, "mismatch",
        )
        self.assertEqual(
            match_applicability(
                metadata, {"version": "1.3"}, now=date(2027, 1, 1),
            ).state, "mismatch",
        )
        self.assertEqual(
            match_applicability(
                {"from": "2026-01"}, {"version": "release-label"}, now=now,
            ).state, "match",
        )

    def test_invalid_or_mixed_legacy_bounds_remain_unknown_with_diagnostics(self):
        for metadata in (
            {"from": "2026-13"}, {"to": "2026-02-30"},
            {"from": "2026-02", "to": "2026-01"},
            {"from": "2026-01", "to": "2.0"},
            {"from": "1.2", "to": "2026-09"},
            {"from": "1.2", "version": ">=2026-01"},
            {"from": "v2026-09"},
        ):
            with self.subTest(metadata=metadata):
                result = match_applicability(
                    metadata, {"version": "1.5"}, now=date(2026, 9, 14),
                )
                self.assertEqual(result.state, "unknown")
                self.assertTrue(result.reasons)

    def test_invalid_calendar_evaluation_clock_is_not_a_fabricated_match(self):
        for now in (
            datetime(2026, 9, 14),
            datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
        ):
            with self.subTest(now=now):
                result = match_applicability({"from": "2026-01"}, now=now)
                self.assertEqual(result.state, "unknown")
                self.assertIn("calendar", " ".join(result.reasons))

    def test_all_supplied_version_constraints_must_hold(self):
        self.assertEqual(
            match_applicability(
                {"version": ">=1.0", "to": "1.5"}, {"version": "1.6"},
            ).state, "mismatch",
        )

    def test_now_does_not_invent_a_missing_product_version(self):
        result = match_applicability(
            {"version": ">=2026-01"}, {},
            now=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(result.state, "unknown")

    def test_unsupported_or_malformed_versions_have_diagnostics(self):
        for expression in (
            "stable", ">=stable", "^1.2", "~1.2", "v1.2", "1.*",
            ">=1.2 || <2.0", ">=1.2,", ">>1.2", "2026-13",
            "2026-02-30", ">=2.0,<1.0", ">=2,<2", ">=1.2,<2026-01",
        ):
            with self.subTest(expression=expression):
                result = match_applicability(
                    {"version": expression}, {"version": "1.2"},
                )
                self.assertEqual(result.state, "unknown")
                self.assertTrue(result.reasons)
        self.assertEqual(
            match_applicability(
                {"version": ">=2026-01"}, {"version": "1.2"},
            ).state, "unknown",
        )
        self.assertEqual(
            match_applicability(
                {"version": ">=1.2"}, {"version": "release-next"},
            ).state, "unknown",
        )

    def test_invalid_metadata_is_not_silently_unrestricted(self):
        for metadata in (
            "", [], 1, {"version": 1.2}, {"tools": "example"},
            {"tools": ["example", None]}, {"product": None}, {"from": False},
            {"unknown_dimension": "example"}, {"from": ">=1.2"},
        ):
            with self.subTest(metadata=metadata):
                self.assertEqual(
                    match_applicability(metadata, {"version": "1.2"}).state,
                    "unknown",
                )

    def test_result_is_json_serializable_and_inputs_are_unchanged(self):
        metadata = {"tools": ["example"], "version": ">=1.2,<2"}
        context = {"tool": "example", "version": "1.3"}
        result = match_applicability(metadata, context)
        self.assertEqual(
            json.loads(json.dumps(result.as_dict())),
            {"state": "match", "reasons": list(result.reasons)},
        )
        self.assertEqual(metadata, {"tools": ["example"], "version": ">=1.2,<2"})
        self.assertEqual(context, {"tool": "example", "version": "1.3"})


if __name__ == "__main__":
    unittest.main()
