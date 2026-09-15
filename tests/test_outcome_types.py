import unittest

from memory_mesh.config import VaultError
from memory_mesh.outcome_types import OutcomeEvent, event_from_dict


class OutcomeTypeTests(unittest.TestCase):
    def event(self, **overrides):
        fields = dict(
            event_id="event-1", timestamp="2026-09-14T12:00:00Z",
            session_id="session-1", subject_type="knowledge",
            subject_id="knowledge/patterns/a", outcome="held",
        )
        fields.update(overrides)
        return OutcomeEvent(**fields)

    def test_round_trip_and_immutable_context(self):
        context = {"tool": "cli", "version": "1.0"}
        event = self.event(context=context)
        context["tool"] = "changed"
        self.assertEqual(event.context["tool"], "cli")
        self.assertEqual(event_from_dict(event.as_dict()), event)
        with self.assertRaises(TypeError):
            event.context["tool"] = "changed"

    def test_failed_reason_defaults_to_unknown(self):
        self.assertEqual(self.event(outcome="failed").reason, "unknown")

    def test_bad_subject_outcome_reason_timestamp_and_context_are_rejected(self):
        for fields in (
            {"subject_type": "arbitrary"},
            {"subject_type": []},
            {"outcome": "#held"},
            {"outcome": "failed", "reason": "arbitrary"},
            {"reason": "misapplied"},
            {"timestamp": "2026-09-14"},
            {"timestamp": "2026-09-14T12:00:00"},
            {"timestamp": "2026-02-30T12:00:00Z"},
            {"context": {"secret": "no"}},
            {"schema_version": True},
            {"domain": 0},
            {"detail": False},
            {"timestamp": "0001-01-01T00:00:00+14:00"},
        ):
            with self.subTest(fields=fields), self.assertRaises(VaultError):
                self.event(**fields)

    def test_intent_ignores_retry_timestamp_not_payload(self):
        first = self.event()
        second = self.event(timestamp="2026-09-14T12:01:00Z")
        self.assertEqual(first.intent(), second.intent())
        self.assertNotEqual(first.intent(), self.event(outcome="unclear").intent())

    def test_unknown_or_missing_serialized_fields_are_rejected(self):
        data = self.event().as_dict()
        data["unexpected"] = "value"
        with self.assertRaises(VaultError):
            event_from_dict(data)
        with self.assertRaises(VaultError):
            event_from_dict({})
        with self.assertRaises(VaultError):
            event_from_dict({1: "value", "unknown": "value"})


if __name__ == "__main__":
    unittest.main()
