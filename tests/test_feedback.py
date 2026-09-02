import unittest
from datetime import date

from helpers import make_vault

from memory_mesh.confidence import (
    FeedbackState,
    decay_due,
    derive_confidence,
    drop_one_level,
    graduation_ready,
    never_exercised_flag,
    same_version,
)
from memory_mesh.curator import engine
from memory_mesh.frontmatter import parse as fm_parse

TODAY = date(2026, 9, 2)


class TestConfidenceRules(unittest.TestCase):
    def test_confidence_high(self):
        fb = FeedbackState(served=5, held=4, failed=0)
        self.assertEqual(derive_confidence(fb, "2026-08-20", "first-party", "validated", TODAY), "high")

    def test_confidence_high_with_ratio(self):
        fb = FeedbackState(served=12, held=10, failed=1)  # 10/11 ≈ 0.91 ≥ 0.9
        self.assertEqual(derive_confidence(fb, "2026-08-30", "mixed", "validated", TODAY), "high")
        fb = FeedbackState(served=12, held=8, failed=2)  # 0.8 < 0.9 → not high
        self.assertEqual(derive_confidence(fb, "2026-08-30", "mixed", "validated", TODAY), "medium")

    def test_would_be_high_but_aged_is_medium(self):
        fb = FeedbackState(served=5, held=4, failed=0)
        self.assertEqual(derive_confidence(fb, "2026-06-15", "first-party", "validated", TODAY), "medium")  # ~79 days

    def test_confidence_medium(self):
        fb = FeedbackState(served=3, held=2, failed=1)
        self.assertEqual(derive_confidence(fb, "2026-08-20", "first-party", "validated", TODAY), "medium")

    def test_failed_over_held_is_low(self):
        fb = FeedbackState(served=4, held=1, failed=2)
        self.assertEqual(derive_confidence(fb, "2026-09-01", "first-party", "validated", TODAY), "low")

    def test_third_party_never_above_low(self):
        fb = FeedbackState(served=9, held=8, failed=0)
        self.assertEqual(derive_confidence(fb, "2026-09-01", "third-party", "validated", TODAY), "low")

    def test_every_candidate_is_low(self):
        fb = FeedbackState(served=9, held=8, failed=0)
        self.assertEqual(derive_confidence(fb, "2026-09-01", "first-party", "candidate", TODAY), "low")

    def test_drop_one_level(self):
        self.assertEqual(drop_one_level("high"), "medium")
        self.assertEqual(drop_one_level("medium"), "low")
        self.assertEqual(drop_one_level("low"), "low")

    def test_decay_windows(self):
        self.assertTrue(decay_due("tool-behaviour", "validated", "2026-05-01", None, TODAY))  # >90d
        self.assertFalse(decay_due("tool-behaviour", "validated", "2026-07-01", None, TODAY))
        self.assertFalse(decay_due("pattern", "validated", "2026-05-01", None, TODAY))  # 180d window
        self.assertTrue(decay_due("pattern", "validated", "2026-01-01", None, TODAY))
        self.assertFalse(decay_due("failure", "validated", "2025-01-01", None, TODAY))  # failures preserved
        self.assertFalse(decay_due("tool-behaviour", "stale", "2026-01-01", None, TODAY))

    def test_never_exercised(self):
        self.assertTrue(never_exercised_flag(FeedbackState(served=3), "2026-05-01", TODAY))
        self.assertFalse(never_exercised_flag(FeedbackState(served=0), "2026-05-01", TODAY))
        self.assertFalse(never_exercised_flag(FeedbackState(served=3, held=1), "2026-05-01", TODAY))

    def test_same_version(self):
        a = {"tools": ["copilot-studio"], "from": "2026-07"}
        self.assertTrue(same_version(a, {"tools": ["copilot-studio"], "from": "2026-07"}))
        self.assertFalse(same_version(a, {"tools": ["copilot-studio"], "from": "2026-09"}))
        self.assertFalse(same_version(a, {"tools": ["cursor"], "from": "2026-07"}))

    def test_graduation_rule(self):
        self.assertTrue(graduation_ready(FeedbackState(held=5, failed=0), "validated", True))
        self.assertFalse(graduation_ready(FeedbackState(held=5, failed=1), "validated", True))
        self.assertFalse(graduation_ready(FeedbackState(held=4, failed=0), "validated", True))
        self.assertFalse(graduation_ready(FeedbackState(held=5, failed=0), "candidate", True))
        self.assertFalse(graduation_ready(FeedbackState(held=5, failed=0), "validated", False))


class TestFeedbackTally(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_tally_reconstructed_from_episodes_only(self):
        tally = engine._tally_from_episodes(self.vault)
        vo = tally["validation-order"]
        self.assertEqual(vo.fb.served, 2)
        self.assertEqual(vo.fb.held, 2)
        self.assertEqual(vo.fb.failed, 0)
        self.assertEqual(vo.last_verified, "2026-09-01")
        wa = tally["schema-validation-workaround"]
        self.assertEqual(wa.fb.served, 1)  # retrieved but never used
        self.assertEqual(wa.fb.held, 0)

    def test_unclear_outcome_tallied(self):
        from datetime import datetime, timezone

        body = """---
type: episode
tool: claude-code
domains: [copilot-studio]
captured: 2026-09-02T09:00:00+05:30
trust: first-party
sensitivity: checked
status: summarised
session_ref: u-1
---

# Session: unclear test

## Goal
g

## What happened
- worked

## Decisions

## Problems

## Knowledge retrieved
- [[validation-order]]
- [[cs-optional-properties]]

## Knowledge used
- [[validation-order]] — unclear — could not tell whether the sequence mattered
- [[cs-optional-properties]]

## Candidate learnings
"""
        self.vault.path("episodes/2026-09-02-claude-code-unclear.md").write_text(body, encoding="utf-8")
        tally = engine._tally_from_episodes(self.vault)
        self.assertEqual(tally["validation-order"].fb.unclear, 1)
        # a used line with no outcome token defaults to unclear (never to held)
        self.assertEqual(tally["cs-optional-properties"].fb.unclear, 1)
        engine.run_lint(self.vault, now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc))
        meta, _ = fm_parse(self.vault.path("knowledge/patterns/validation-order.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["feedback"], {"served": 3, "held": 2, "failed": 0, "unclear": 1})
        self.assertEqual(meta["confidence"], "medium")  # unclear neither helps nor harms

    def test_lint_writes_feedback_and_last_verified(self):
        from datetime import datetime, timezone

        # zero out the note's feedback, then lint restores it from episodes
        p = self.vault.path("knowledge/patterns/validation-order.md")
        text = p.read_text(encoding="utf-8").replace(
            "feedback: {served: 2, held: 2, failed: 0, unclear: 0}",
            "feedback: {served: 0, held: 0, failed: 0, unclear: 0}",
        ).replace("last_verified: 2026-09-01", "last_verified: null")
        p.write_text(text, encoding="utf-8")
        engine.run_lint(self.vault, now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc))
        meta, _ = fm_parse(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["feedback"], {"served": 2, "held": 2, "failed": 0, "unclear": 0})
        self.assertEqual(meta["last_verified"], "2026-09-01")
        self.assertEqual(meta["confidence"], "medium")  # held 2 < 3


if __name__ == "__main__":
    unittest.main()
