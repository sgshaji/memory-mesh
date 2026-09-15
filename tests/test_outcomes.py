import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from helpers import directory_link, make_vault

from memory_mesh import config, frontmatter, outcomes
from memory_mesh.config import VaultError
from memory_mesh.notes import Note, load_note
from memory_mesh.outcome_types import event_from_dict


class TestOutcomes(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.now = datetime.now(timezone.utc) - timedelta(seconds=5)

    def capture(self, **changes):
        args = {
            "session_id": "session-one",
            "subject_type": "knowledge",
            "subject_id": "validation-order",
            "outcome": "#held",
            "now": self.now,
        }
        args.update(changes)
        return outcomes.record_outcome(self.vault, **args)

    def event_path(self, event_id):
        name = hashlib.sha256(event_id.encode("utf-8")).hexdigest() + ".md"
        return self.vault.path(config.OUTCOME_EVENTS) / name

    def write_event(self, data):
        path = self.event_path(data["event_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.compose({"type": "outcome", **data}, ""), encoding="utf-8")
        return path

    def test_capture_is_reported_canonical_and_does_not_edit_knowledge(self):
        path = self.vault.path("knowledge/patterns/validation-order.md")
        before = path.read_bytes()
        event = self.capture()
        self.assertEqual(event.subject_id, "knowledge/patterns/validation-order")
        self.assertEqual(event.outcome, "held")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(outcomes.read_events(self.vault), [event])
        text = self.event_path(event.event_id).read_text(encoding="utf-8")
        self.assertIn("reported", text.lower())
        self.assertNotIn("#held", text)
        self.assertRegex(self.event_path(event.event_id).name, r"^[0-9a-f]{64}\.md$")
        with self.assertRaises(VaultError):
            event_from_dict({**event.as_dict(), "outcome": "#held"})

    def test_retry_uses_intent_not_timestamp_and_leaves_file_unchanged(self):
        first = self.capture()
        path = self.event_path(first.event_id)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        retry = self.capture(now=self.now + timedelta(seconds=1))
        self.assertEqual(first, retry)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(len(outcomes.read_events(self.vault)), 1)

    def test_schema_parser_shares_the_persisted_envelope_without_mutating_metadata(self):
        event = self.capture()
        path = self.event_path(event.event_id)
        note = load_note(path, self.vault)
        original = dict(note.meta)
        self.assertEqual(outcomes.parse_event_note(note), event)
        self.assertEqual(note.meta, original)
        self.assertEqual(note.meta, {"type": "outcome", **event.as_dict()})
        with patch.object(outcomes, "_parse_event_note", wraps=outcomes._parse_event_note) as validator:
            self.assertEqual(outcomes.read_events(self.vault), [event])
            self.assertEqual(validator.call_count, 1)

    def test_schema_parser_preserves_optional_event_defaults_and_rejects_extra_envelope_keys(self):
        event = self.capture(outcome="failed")
        required = {"event_id", "timestamp", "session_id", "subject_type", "subject_id", "outcome"}
        meta = {"type": "outcome", **{key: value for key, value in event.as_dict().items() if key in required}}
        note = Note(self.event_path(event.event_id), meta, "", self.vault)
        self.assertEqual(outcomes.parse_event_note(note), event)
        for extra in ({"status": "validated"}, {"sensitivity": "checked"}, {"unexpected": True}):
            with self.subTest(extra=extra), self.assertRaises(VaultError):
                outcomes.parse_event_note(Note(note.path, {**meta, **extra}, "", self.vault))

    def test_capture_and_retry_do_not_scan_the_journal(self):
        path = self.vault.path(config.OUTCOME_EVENTS)
        path.mkdir()
        (path / "unrelated-malformed.md").write_text("Not an outcome.", encoding="utf-8")
        with (
            patch.object(outcomes, "read_events", side_effect=AssertionError("journal scan")),
            patch.object(Path, "glob", side_effect=AssertionError("directory scan")),
            patch.object(Path, "rglob", side_effect=AssertionError("recursive scan")),
        ):
            event = self.capture(subject_id="knowledge/patterns/validation-order", event_id="direct")
            replay = self.capture(subject_id="knowledge/patterns/validation-order", event_id="direct")
        self.assertEqual(event, replay)

    def test_schema_parser_does_not_open_the_event_or_resolve_its_subject(self):
        event = self.capture()
        note = load_note(self.event_path(event.event_id), self.vault)
        with (
            patch.object(outcomes, "read_events", side_effect=AssertionError("journal scan")),
            patch.object(outcomes, "canonical_subject_ref", side_effect=AssertionError("subject resolution")),
            patch.object(outcomes, "load_note", side_effect=AssertionError("note read")),
        ):
            self.assertEqual(outcomes.parse_event_note(note), event)

    def test_explicit_trials_remain_distinct_and_id_reuse_checks_intent(self):
        self.capture(event_id="trial-one")
        self.capture(event_id="trial-two")
        self.assertEqual(len(outcomes.read_events(self.vault)), 2)
        for change in (
            {"outcome": "failed"}, {"detail": "different report"},
            {"session_id": "another-session"}, {"context": {"version": "2"}},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(VaultError, "intent|conflict"):
                self.capture(event_id="trial-one", **change)
        self.assertEqual(len(outcomes.read_events(self.vault)), 2)

    def test_concurrent_retries_publish_one_complete_immutable_record(self):
        barrier = Barrier(6)

        def capture(index):
            barrier.wait()
            return self.capture(now=self.now + timedelta(microseconds=index))

        with ThreadPoolExecutor(max_workers=6) as executor:
            events = list(executor.map(capture, range(6)))
        self.assertTrue(all(event == events[0] for event in events))
        paths = list(self.vault.path(config.OUTCOME_EVENTS).iterdir())
        self.assertEqual(paths, [self.event_path(events[0].event_id)])
        self.assertEqual(outcomes.read_events(self.vault), [events[0]])

    def test_interrupted_publication_does_not_leave_a_partial_event(self):
        with patch.object(outcomes.os, "link", side_effect=OSError("publication interrupted")):
            with self.assertRaises(VaultError):
                self.capture()
        self.assertEqual(list(self.vault.path(config.OUTCOME_EVENTS).iterdir()), [])
        self.assertEqual(outcomes.read_events(self.vault), [])

    def test_concurrent_conflicting_id_preserves_the_winner(self):
        barrier = Barrier(2)

        def capture(value):
            barrier.wait()
            try:
                return self.capture(event_id="one-trial", outcome=value)
            except VaultError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(capture, ("held", "failed")))
        winners = [result for result in results if not isinstance(result, VaultError)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(outcomes.read_events(self.vault), winners)
        self.assertIn("intent", str(next(result for result in results if isinstance(result, VaultError))))

    def test_safe_filters_and_failure_reasons(self):
        failed = self.capture(outcome="#failed")
        self.assertEqual(failed.reason, "unknown")
        self.capture(session_id="session-two", outcome="unclear")
        self.assertEqual(outcomes.read_events(self.vault, session_id="session-one"), [failed])
        self.assertEqual(
            outcomes.read_events(self.vault, subject_type="knowledge", subject_id="validation-order"),
            outcomes.read_events(self.vault),
        )
        self.assertEqual(outcomes.read_events(self.vault, subject_type="skill"), [])
        with self.assertRaises(VaultError):
            outcomes.read_events(self.vault, subject_type="unknown")

    def test_unresolved_ambiguous_and_cross_tier_subjects_fail_explicitly(self):
        duplicate = self.vault.path("knowledge/tools/validation-order.md")
        duplicate.write_bytes(self.vault.path("knowledge/patterns/validation-order.md").read_bytes())
        for ref in (
            "missing", "validation-order", "knowledge/missing/validation-order",
            "knowledge/_index/copilot-studio", "../validation-order",
            r"..\validation-order", r"C:\private\validation-order",
            "/knowledge/patterns/validation-order",
        ):
            with self.subTest(ref=ref), self.assertRaises(VaultError):
                self.capture(subject_id=ref)
        event = self.capture(subject_id="[[knowledge/patterns/validation-order.md]]")
        self.assertEqual(event.subject_id, "knowledge/patterns/validation-order")

    def test_skill_file_and_skill_directory_are_canonical_and_ambiguity_is_rejected(self):
        folder = self.vault.path("skills/demo")
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: demo\ndescription: Test\n---\nRun a check.\n", encoding="utf-8")
        event = self.capture(subject_type="skill", subject_id="demo", outcome="succeeded")
        self.assertEqual(event.subject_id, "skills/demo/SKILL")
        flat = self.vault.path("skills/demo.md")
        flat.write_text(frontmatter.compose({"type": "skill"}, "A legacy skill."), encoding="utf-8")
        with self.assertRaisesRegex(VaultError, "ambiguous"):
            self.capture(subject_type="skill", subject_id="demo", outcome="partial")
        explicit = self.capture(subject_type="skill", subject_id="skills/demo.md", outcome="partial")
        self.assertEqual(explicit.subject_id, "skills/demo")

    def test_linked_subject_and_linked_journal_directory_are_rejected(self):
        target = self.vault.path("projects/linked-outcomes")
        target.mkdir()
        directory_link(self.vault.path(config.OUTCOME_EVENTS), target)
        with self.assertRaises(VaultError):
            self.capture()
        with self.assertRaises(VaultError):
            outcomes.read_events(self.vault)
        self.assertEqual(list(target.iterdir()), [])

    def test_all_report_fields_are_redacted_and_sensitive_identities_are_rejected(self):
        event = self.capture(
            detail="password = hunter2secret",
            source="https://example.sharepoint.com/sites/private",
            context={"project": "person@private.example.org", "tool": "password = anothersecret"},
        )
        text = self.event_path(event.event_id).read_text(encoding="utf-8")
        for secret in ("hunter2secret", "anothersecret", "private.example.org", "sharepoint.com"):
            self.assertNotIn(secret, text)
        self.assertEqual(event.context["project"], "[email]")
        token = "ghp_" + "a" * 30
        for field in ("session_id", "event_id", "domain"):
            with self.subTest(field=field), self.assertRaises(VaultError) as caught:
                self.capture(**{field: token})
            self.assertNotIn(token, str(caught.exception))
        self.vault.path(config.REDACT_FILE).write_text("literal:private-customer\n", encoding="utf-8")
        private = self.vault.path("knowledge/patterns/private-customer.md")
        private.write_bytes(self.vault.path("knowledge/patterns/validation-order.md").read_bytes())
        with self.assertRaises(VaultError):
            self.capture(subject_id="private-customer")

    def test_unknown_values_and_control_characters_do_not_write(self):
        for change in (
            {"outcome": "#succeeded"}, {"outcome": "yes"}, {"subject_type": []},
            {"reason": "misapplied"}, {"outcome": "failed", "reason": "unrecognized"},
            {"context": {"unknown": "value"}}, {"context": []},
            {"context": {"tool": "one\ntwo"}}, {"detail": "a\n## Knowledge used"},
            {"event_id": "../bad"}, {"session_id": "bad session"},
        ):
            with self.subTest(change=change), self.assertRaises(VaultError):
                self.capture(**change)
        self.assertFalse(self.vault.path(config.OUTCOME_EVENTS).exists())

    def test_timestamp_timezone_and_future_tolerance(self):
        offset = timezone(timedelta(hours=5, minutes=30))
        local = self.now.astimezone(offset)
        event = self.capture(now=local)
        self.assertEqual(datetime.fromisoformat(event.timestamp), self.now)
        with self.assertRaisesRegex(VaultError, "timezone"):
            self.capture(now=self.now.replace(tzinfo=None))
        with self.assertRaisesRegex(VaultError, "future"):
            self.capture(now=datetime.now(timezone.utc) + timedelta(days=1))
        self.capture(event_id="clock-skew", now=datetime.now(timezone.utc) + timedelta(seconds=30))
        self.vault.path(config.SETTINGS_FILE).write_text(frontmatter.compose({
            "type": "meta", "version": 1, "feedback": {"future_tolerance_seconds": 0},
        }, ""), encoding="utf-8")
        with self.assertRaisesRegex(VaultError, "future"):
            outcomes.read_events(self.vault)

    def test_malformed_stored_records_are_not_silently_skipped(self):
        event = self.capture()
        path = self.event_path(event.event_id)
        cases = [
            {**event.as_dict(), "timestamp": "2026-09-01T00:00:00"},
            {**event.as_dict(), "timestamp": "nonsense"},
            {**event.as_dict(), "timestamp": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
            {**event.as_dict(), "context": {"tool": ["not", "text"]}},
            {**event.as_dict(), "unexpected": True},
            {**event.as_dict(), "schema_version": True},
            {**event.as_dict(), "source": "password = hunter2secret"},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.write_event(data)
                with self.assertRaises(VaultError):
                    outcomes.parse_event_note(load_note(path, self.vault))
                with self.assertRaises(VaultError):
                    outcomes.read_events(self.vault)
        path.write_text("---\ntype: outcome\n", encoding="utf-8")
        with self.assertRaises(VaultError):
            outcomes.read_events(self.vault)

    def test_duplicate_keys_and_mismatched_event_filenames_fail(self):
        event = self.capture()
        path = self.event_path(event.event_id)
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace("type: outcome", "type: outcome\ntype: outcome"), encoding="utf-8")
        with self.assertRaises(VaultError):
            outcomes.read_events(self.vault)
        path.write_text(original, encoding="utf-8")
        path.rename(path.with_name("conflicting-copy.md"))
        with self.assertRaises(VaultError):
            outcomes.read_events(self.vault)

    def test_stored_event_remains_available_if_the_subject_is_later_deleted(self):
        event = self.capture()
        self.vault.path("knowledge/patterns/validation-order.md").unlink()
        self.assertEqual(outcomes.read_events(self.vault), [event])

    def test_legacy_episodes_canonicalize_and_duplicate_bullets_deduplicate(self):
        before = outcomes.collect_evidence(self.vault)
        self.assertEqual(len(before), 3)
        self.assertTrue(all(event.subject_id.startswith("knowledge/") for event in before))
        path = self.vault.path("episodes/2026-09-01-copilot-studio-schema-stage.md")
        note = load_note(path, self.vault)
        bullet = "- [[validation-order]] — held — sequence worked as documented"
        path.write_text(frontmatter.compose(note.meta, note.body.replace(bullet, bullet + "\n" + bullet)), encoding="utf-8")
        self.assertEqual(outcomes.collect_evidence(self.vault), before)
        other = path.with_name("2026-09-02-independent.md")
        other.write_bytes(path.read_bytes())
        after = outcomes.collect_evidence(self.vault)
        self.assertEqual(len(after), 5)
        self.assertEqual(len({event.event_id for event in after}), 5)

    def test_legacy_skill_usage_and_recall_quality_are_common_events(self):
        skill = self.vault.path("skills/demo.md")
        skill.write_text(frontmatter.compose({"type": "skill"}, "A skill."), encoding="utf-8")
        path = self.vault.path("episodes/2026-09-02-partial.md")
        path.write_text(frontmatter.compose({
            "type": "episode", "status": "summarised", "captured": "2026-09-02",
            "tool": "cli", "domains": ["mcp"], "recall_quality": "off-target",
            "context": {"route": "keyword", "task_category": "debugging"},
        }, "## Skills used\n- [[skills/demo]] — failed — reason=misapplied; wrong arguments\n"), encoding="utf-8")
        events = [event for event in outcomes.collect_evidence(self.vault) if event.subject_type != "knowledge"]
        self.assertEqual({event.subject_type for event in events}, {"skill", "recall"})
        skill_event = next(event for event in events if event.subject_type == "skill")
        self.assertEqual(skill_event.reason, "misapplied")
        self.assertEqual(skill_event.context["route"], "keyword")
        self.assertEqual(skill_event.timestamp, "2026-09-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
