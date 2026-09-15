import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from helpers import directory_link, make_vault

from memory_mesh import config, frontmatter
from memory_mesh.config import VaultError
from memory_mesh.curator import analytics
from memory_mesh.notes import Note, iter_notes, load_note
from memory_mesh.schema import validate_note


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class TestCandidateAnalytics(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        for path in self.vault.path(config.INBOX).rglob("*.md"):
            path.unlink()

    def write(self, relative, meta, body=""):
        path = self.vault.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        return path

    def candidate(self, slug, *, age=1, body="## Observations\n- [observation] An unreviewed claim.", **meta):
        return self.write(f"00-inbox/{slug}.md", {
            "type": "candidate", "title": slug, "source": "test",
            "captured": (NOW - timedelta(days=age)).isoformat(),
            "trust": "first-party", "sensitivity": "checked", **meta,
        }, body)

    def episode(self, slug, *, age=1, links=(), body=None, **meta):
        if body is None:
            body = "## Candidate learnings\n" + "\n".join(f"- [[{ref}]]" for ref in links)
        return self.write(f"episodes/{slug}.md", {
            "type": "episode", "tool": "test",
            "captured": (NOW - timedelta(days=age)).isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "raw", **meta,
        }, body)

    def ranked(self):
        return analytics.rank_candidates(self.vault, now=NOW)

    def test_empty_legacy_inbox_is_healthy(self):
        self.assertEqual(self.ranked(), [])
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 0)
        self.assertEqual(health.candidate_count, 0)
        self.assertEqual(health.gap_count, 0)
        self.assertEqual(health.high_signal_count, 0)
        self.assertEqual(health.linked_count, 0)
        self.assertIsNone(health.oldest_age_days)
        self.assertIsNone(health.oldest_ref)
        self.assertEqual(health.review_days, 14)
        self.assertEqual(health.warnings, ())

    def test_preloaded_inbox_and_episodes_preserve_results_without_body_reads(self):
        self.candidate("high", signal="high", source_episode="episodes/context")
        self.candidate("bad-fields", signal="urgent", captured="invalid")
        self.candidate("processed", processed="done")
        self.episode("context", links=["00-inbox/high"])
        broken = self.vault.path("00-inbox/broken.md")
        broken.write_text("---\nnot yaml\n---\n", encoding="utf-8")
        inbox = list(iter_notes(self.vault, config.INBOX))
        episodes = list(iter_notes(self.vault, config.EPISODES))
        expected_rank = self.ranked()
        expected_health = analytics.inbox_health(self.vault, now=NOW)
        with patch.object(analytics, "load_note", side_effect=AssertionError("cached body reopened")):
            ranked = analytics.rank_candidates(
                self.vault, now=NOW, inbox=iter(reversed(inbox)), episodes=iter(reversed(episodes)),
            )
            health = analytics.inbox_health(self.vault, now=NOW, inbox=inbox, episodes=episodes)
        self.assertEqual(ranked, expected_rank)
        self.assertEqual(health, expected_health)
        self.assertTrue(any("broken.md" in warning for warning in health.warnings))

    def test_empty_preloaded_inventories_disable_discovery(self):
        self.candidate("on-disk", signal="high")
        with patch.object(analytics, "load_note", side_effect=AssertionError("unexpected discovery")):
            self.assertEqual(analytics.rank_candidates(self.vault, now=NOW, inbox=[], episodes=[]), [])
            health = analytics.inbox_health(self.vault, now=NOW, inbox=[], episodes=[])
        self.assertEqual(health.pending_count, 0)
        self.assertEqual(health.warnings, ())

    def test_preloaded_inventory_rejects_cross_folder_notes(self):
        wrong_inbox = self.write("projects/not-inbox.md", {"type": "candidate"}, "")
        wrong_episode = self.write("00-inbox/not-episode-directory.md", {"type": "episode"}, "")
        with self.assertRaises(VaultError):
            analytics.inbox_health(
                self.vault, now=NOW, inbox=[load_note(wrong_inbox, self.vault)], episodes=[],
            )
        with self.assertRaises(VaultError):
            analytics.rank_candidates(
                self.vault, now=NOW, inbox=[], episodes=[load_note(wrong_episode, self.vault)],
            )

    def test_preloaded_redirected_path_is_diagnosed_without_reading_it(self):
        target = self.vault.path("projects/cached-target")
        target.mkdir()
        redirected_note = target / "candidate.md"
        redirected_note.write_text("This body must not be read through the redirected inbox path.", encoding="utf-8")
        link = self.vault.path("00-inbox/cached-link")
        directory_link(link, target)
        note = Note(
            link / "candidate.md",
            {"type": "candidate", "title": "Redirect", "captured": NOW.isoformat()}, "",
            self.vault,
        )
        with patch.object(analytics, "load_note", side_effect=AssertionError("redirected body read")):
            health = analytics.inbox_health(self.vault, now=NOW, inbox=[note], episodes=[])
        self.assertEqual(health.pending_count, 0)
        self.assertTrue(any("redirected" in warning for warning in health.warnings))

    def test_unmodified_legacy_fixture_needs_no_migration(self):
        vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        before = {path: path.read_bytes() for path in vault.root.rglob("*.md")}
        ranked = analytics.rank_candidates(vault, now=NOW)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].signal, "normal")
        self.assertFalse(ranked[0].linked)
        self.assertEqual(ranked[0].warnings, ())
        self.assertEqual(before, {path: path.read_bytes() for path in vault.root.rglob("*.md")})

    def test_high_signal_wins_over_linkage_recurrence_and_recency(self):
        self.candidate("high", signal="high", age=100)
        self.candidate("normal", age=0, source_episode="episodes/first")
        self.candidate("low", signal="low", age=0)
        self.episode("first", links=["00-inbox/normal", "00-inbox/low"], age=0)
        self.episode("second", links=["00-inbox/normal", "00-inbox/low"], age=0)
        self.assertEqual([item.title for item in self.ranked()], ["high", "normal", "low"])

    def test_linked_context_precedes_newer_standalone_candidate(self):
        self.candidate("standalone", age=0)
        self.candidate("linked", age=100)
        self.episode("context", links=["00-inbox/linked"], age=99)
        linked, standalone = self.ranked()
        self.assertEqual(linked.title, "linked")
        self.assertTrue(linked.linked)
        self.assertFalse(standalone.linked)
        self.assertEqual(linked.episode_refs, ("episodes/context",))
        self.assertEqual(linked.recurrence, 0)
        self.assertTrue(any("attention" in reason for reason in linked.reasons))
        self.assertTrue(any("episode" in reason for reason in linked.reasons))

    def test_both_link_directions_union_without_inflating_recurrence(self):
        self.candidate("repeated", source_episode="episodes/first.md")
        self.episode("first", links=["00-inbox/repeated", "repeated.md", "00-inbox/repeated"])
        self.episode("second", links=["00-inbox/repeated"])
        item = self.ranked()[0]
        self.assertEqual(item.episode_refs, ("episodes/first", "episodes/second"))
        self.assertEqual(item.recurrence, 1)
        self.assertEqual(len(item.episode_refs), 2)
        self.assertEqual(item.warnings, ())

    def test_more_distinct_episode_context_precedes_recency(self):
        self.candidate("recurrent", age=30)
        self.candidate("recent", age=0)
        self.episode("older-a", links=["00-inbox/recurrent"], age=25)
        self.episode("older-b", links=["00-inbox/recurrent"], age=20)
        self.episode("today", links=["00-inbox/recent"], age=0)
        self.assertEqual([item.title for item in self.ranked()], ["recurrent", "recent"])

    def test_recency_uses_latest_episode_without_resetting_inbox_age(self):
        self.candidate("revisited", age=30)
        self.candidate("other", age=5)
        self.episode("today", links=["00-inbox/revisited"], age=0)
        self.episode("yesterday", links=["00-inbox/other"], age=1)
        first = self.ranked()[0]
        self.assertEqual(first.title, "revisited")
        self.assertEqual(first.last_seen_at, NOW)
        self.assertEqual(first.age_days, 30)
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW).oldest_age_days, 30)

    def test_recency_and_full_reference_provide_deterministic_ties(self):
        self.candidate("z", age=2)
        self.candidate("b", age=1)
        self.candidate("a", age=1)
        self.assertEqual([item.title for item in self.ranked()], ["a", "b", "z"])

    def test_only_candidate_learning_sections_provide_reverse_linkage(self):
        self.candidate("included")
        self.candidate("excluded")
        self.episode("partial", body=(
            "## Knowledge used\n- [[00-inbox/excluded]] held\n"
            "## Candidate learnings\n- [[00-inbox/included.md#details|Candidate]]\n"
            "## Decisions\n- [[00-inbox/excluded]]\n"
        ))
        priorities = {item.title: item for item in self.ranked()}
        self.assertTrue(priorities["included"].linked)
        self.assertFalse(priorities["excluded"].linked)

    def test_bare_and_windows_episode_links_resolve(self):
        self.episode("source")
        self.candidate("bare", source_episode="source")
        self.candidate("windows", source_episode="episodes\\source.md")
        for item in self.ranked():
            self.assertEqual(item.episode_refs, ("episodes/source",))

    def test_missing_or_malformed_source_episode_does_not_fake_context(self):
        self.episode("exists")
        self.candidate("missing", source_episode="episodes/missing")
        self.candidate("invalid", source_episode=["episodes/exists"])
        self.candidate("escaped", source_episode="../episodes/exists")
        self.candidate("external", source_episode="https://example.com/exists")
        for item in self.ranked():
            self.assertFalse(item.linked)
            self.assertTrue(any("source_episode" in warning for warning in item.warnings))

    def test_qualified_refs_never_fall_back_to_an_unrelated_basename(self):
        self.episode("exists")
        self.candidate("wrong-folder", source_episode="projects/exists")
        self.candidate("wrong-subfolder", source_episode="episodes/missing/exists")
        self.episode("wrong-target", links=["knowledge/patterns/wrong-folder"])
        for item in self.ranked():
            self.assertFalse(item.linked)

    def test_ambiguous_bare_episode_reference_is_not_guessed(self):
        self.episode("a/same")
        self.episode("b/same")
        self.candidate("ambiguous", source_episode="same")
        item = self.ranked()[0]
        self.assertFalse(item.linked)
        self.assertTrue(any("ambiguous" in warning for warning in item.warnings))

    def test_ambiguous_bare_candidate_reference_is_not_guessed(self):
        self.candidate("a/same")
        self.candidate("b/same")
        self.episode("source", links=["same"])
        warnings = []
        ranked = analytics.rank_candidates(self.vault, now=NOW, diagnostics=warnings)
        self.assertTrue(all(not item.linked for item in ranked))
        self.assertTrue(any("ambiguous" in warning for warning in warnings))

    def test_unknown_or_malformed_signal_falls_back_with_diagnostic(self):
        for index, signal in enumerate(("urgent", "HIGH", None, ["high"], True)):
            self.candidate(f"bad-{index}", signal=signal)
        for item in self.ranked():
            self.assertEqual(item.signal, "normal")
            self.assertTrue(any("signal" in warning for warning in item.warnings))
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW).high_signal_count, 0)

    def test_missing_optional_signal_remains_normal_without_warning(self):
        self.candidate("legacy")
        item = self.ranked()[0]
        self.assertEqual(item.signal, "normal")
        self.assertIsNone(item.source_episode)
        self.assertEqual(item.warnings, ())

    def test_malformed_timestamps_are_unknown_not_filesystem_recency(self):
        self.candidate("valid", age=50)
        for index, stamp in enumerate((
            "nonsense", "2026-02-30T12:00:00Z", "2026-09-14X12:00:00Z", [], 42, None,
        )):
            self.candidate(f"unknown-{index}", captured=stamp)
        ranked = self.ranked()
        self.assertEqual(ranked[0].title, "valid")
        for item in ranked[1:]:
            self.assertIsNone(item.captured_at)
            self.assertIsNone(item.age_days)
            self.assertIsNone(item.last_seen_at)
            self.assertTrue(any("captured" in warning for warning in item.warnings))
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW).oldest_age_days, 50)

    def test_naive_legacy_timestamp_is_explicitly_interpreted_as_utc(self):
        self.candidate("naive", captured="2026-09-13T12:00:00")
        item = self.ranked()[0]
        self.assertEqual(item.age_days, 1)
        self.assertTrue(any("UTC" in warning for warning in item.warnings))
        self.assertEqual(
            analytics.rank_candidates(self.vault, now=NOW.replace(tzinfo=None)), self.ranked(),
        )

    def test_future_capture_and_episode_clocks_cannot_produce_negative_ages(self):
        self.candidate("future", age=-100, source_episode="episodes/future")
        self.episode("future", age=-200)
        item = self.ranked()[0]
        self.assertEqual(item.age_days, 0)
        self.assertEqual(item.last_seen_at, NOW)
        self.assertTrue(any("future" in warning for warning in item.warnings))
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.oldest_age_days, 0)
        self.assertEqual(health.overdue_count, 0)

    def test_bad_episode_timestamp_preserves_linkage_but_not_recency(self):
        self.candidate("linked", age=3, source_episode="episodes/bad-time")
        self.episode("bad-time", captured="invalid")
        item = self.ranked()[0]
        self.assertTrue(item.linked)
        self.assertEqual(item.last_seen_at, NOW - timedelta(days=3))
        self.assertTrue(any("episodes/bad-time" in warning for warning in item.warnings))

    def test_gaps_count_for_attention_but_carry_no_factual_claims(self):
        gap = self.candidate(
            "gap", type="gap", need="Documentation of an unfamiliar interface",
            signal="high", age=20, body="", source_episode="episodes/context",
        )
        self.candidate("observation", age=1)
        self.episode("context")
        self.assertEqual(
            [issue.message for issue in validate_note(load_note(gap, self.vault), self.vault)
             if issue.severity == "error"], [],
        )
        first = self.ranked()[0]
        self.assertEqual(first.kind, "gap")
        self.assertTrue(first.is_gap)
        self.assertTrue(any("not a factual claim" in reason for reason in first.reasons))
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 2)
        self.assertEqual(health.candidate_count, 1)
        self.assertEqual(health.gap_count, 1)
        self.assertEqual(health.high_signal_count, 1)
        self.assertEqual(health.linked_count, 1)
        self.assertEqual(health.oldest_ref, "00-inbox/gap")
        self.assertEqual(health.oldest_age_days, 20)
        self.assertEqual(health.overdue_count, 1)

    def test_processed_items_and_non_candidate_notes_do_not_count(self):
        self.candidate("done", signal="high", processed="2026-09-01", age=100)
        self.candidate("done-gap", type="gap", need="Something", processed=False, age=100)
        self.candidate("not-candidate", type="reference", age=100)
        self.candidate("pending")
        self.episode("old-context", links=["00-inbox/done"])
        self.assertEqual([item.title for item in self.ranked()], ["pending"])
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 1)
        self.assertEqual(health.high_signal_count, 0)
        self.assertEqual(health.oldest_age_days, 1)
        self.assertEqual(health.warnings, ())

    def test_age_threshold_is_configured_and_warning_requires_exceeding_it(self):
        self.write(config.SETTINGS_FILE, {"type": "meta", "feedback": {"inbox_review_days": 3}})
        self.candidate("at-threshold", age=3)
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW).warnings, ())
        self.candidate("over-threshold", age=3.5)
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.review_days, 3)
        self.assertEqual(health.overdue_count, 1)
        self.assertEqual(health.oldest_age_days, 3.5)
        self.assertTrue(any("review threshold" in warning for warning in health.warnings))

    def test_unknown_ages_are_reported_without_inventing_an_oldest_date(self):
        path = self.candidate("missing-time")
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        del meta["captured"]
        path.write_text(frontmatter.compose(meta, body), encoding="utf-8")
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 1)
        self.assertIsNone(health.oldest_age_days)
        self.assertIsNone(health.oldest_ref)
        self.assertTrue(any("captured" in warning for warning in health.warnings))

    def test_partial_and_unreadable_notes_are_diagnosed_without_hiding_valid_candidates(self):
        self.candidate("valid")
        self.vault.path("00-inbox/broken.md").write_text("---\nnot yaml\n---\n", encoding="utf-8")
        self.vault.path("00-inbox/unreadable.md").write_bytes(b"\xff\xfe\x00")
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 1)
        self.assertTrue(any("broken.md" in warning for warning in health.warnings))
        self.assertTrue(any("unreadable.md" in warning for warning in health.warnings))

    def test_untyped_partial_inbox_file_is_diagnosed_not_silently_omitted(self):
        self.vault.path("00-inbox/partial.md").write_text("Incomplete candidate text", encoding="utf-8")
        health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(health.pending_count, 0)
        self.assertTrue(any("partial.md" in warning for warning in health.warnings))

    def test_timestamp_offsets_compare_instants_and_overflow_is_diagnosed(self):
        self.candidate("utc", captured="2026-09-13T12:00:00Z")
        self.candidate("offset", captured="2026-09-13T17:30:00+05:30")
        self.candidate("overflow", captured="0001-01-01T00:00:00+14:00")
        ranked = self.ranked()
        self.assertEqual([item.title for item in ranked], ["offset", "utc", "overflow"])
        self.assertEqual(ranked[0].age_days, 1)
        self.assertEqual(ranked[0].captured_at, ranked[1].captured_at)
        self.assertIsNone(ranked[2].age_days)
        self.assertTrue(ranked[2].warnings)

    def test_qualified_candidate_links_disambiguate_shared_basename(self):
        self.candidate("a/same")
        self.candidate("b/same")
        self.episode("context", links=["00-inbox/b/same"])
        ranked = self.ranked()
        self.assertEqual(ranked[0].ref, "00-inbox/b/same")
        self.assertTrue(ranked[0].linked)
        self.assertFalse(ranked[1].linked)

    def test_non_episode_records_cannot_supply_episode_context(self):
        self.episode("event", type="outcome")
        self.candidate("unlinked", source_episode="episodes/event")
        item = self.ranked()[0]
        self.assertFalse(item.linked)
        self.assertTrue(item.warnings)

    def test_diagnostics_do_not_accumulate_duplicates_on_replay(self):
        self.candidate("unknown", signal="urgent", source_episode="episodes/missing")
        warnings = []
        analytics.rank_candidates(self.vault, now=NOW, diagnostics=warnings)
        first = list(warnings)
        analytics.rank_candidates(self.vault, now=NOW, diagnostics=warnings)
        self.assertTrue(warnings)
        self.assertEqual(warnings, first)

    def test_rank_and_health_are_read_only_idempotent_and_json_serializable(self):
        self.candidate("high", signal="high", age=20, source_episode="episodes/context")
        self.episode("context", links=["00-inbox/high"])
        before = {path: path.read_bytes() for path in self.vault.root.rglob("*.md")}
        first_rank = self.ranked()
        first_health = analytics.inbox_health(self.vault, now=NOW)
        self.assertEqual(self.ranked(), first_rank)
        self.assertEqual(analytics.inbox_health(self.vault, now=NOW), first_health)
        self.assertEqual(before, {path: path.read_bytes() for path in self.vault.root.rglob("*.md")})
        self.assertEqual(json.loads(json.dumps(first_rank[0].as_dict()))["signal"], "high")
        self.assertEqual(json.loads(json.dumps(first_health.as_dict()))["pending_count"], 1)

    def test_episode_files_are_read_once_per_inventory_not_once_per_candidate(self):
        for index in range(25):
            self.candidate(f"candidate-{index}", source_episode="episodes/shared")
        shared = self.episode("shared", links=["00-inbox/candidate-0"])
        with patch.object(analytics, "load_note", wraps=analytics.load_note) as read:
            ranked = self.ranked()
        self.assertEqual(len(ranked), 25)
        self.assertTrue(all(item.linked for item in ranked))
        self.assertEqual(sum(call.args[0] == shared for call in read.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
