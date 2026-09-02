import unittest
from datetime import datetime, timezone

from helpers import make_vault

from memory_mesh import config
from memory_mesh.curator import engine
from memory_mesh.curator.review import parse_review_file, pending_review_files
from memory_mesh.frontmatter import parse as fm_parse
from memory_mesh.notes import load_note

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _episode_with_outcome(vault, name, ref, outcome, reason, captured="2026-09-02T10:00:00+05:30"):
    body = f"""---
type: episode
tool: copilot-studio
domains: [copilot-studio]
captured: {captured}
trust: first-party
sensitivity: checked
status: summarised
session_ref: t-2
---

# Session: contradiction test

## Goal
test

## What happened
- exercised the note

## Decisions

## Problems

## Knowledge retrieved
- [[{ref}]]

## Knowledge used
- [[{ref}]] — {outcome} — {reason}

## Candidate learnings
"""
    p = vault.path(f"episodes/{name}.md")
    p.write_text(body, encoding="utf-8")
    return p


class TestContradiction(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_single_same_version_failure_holds_and_drops_confidence(self):
        _episode_with_outcome(self.vault, "2026-09-02-cs-fail1", "cs-optional-properties",
                              "failed", "behaviour appears changed on this build")
        engine.run_compile(self.vault, now=NOW)  # mines the episode
        report = engine.run_lint(self.vault, now=NOW)
        holds = [d for d in report.decisions if d.kind == "HOLD" and d.target_ref.endswith("cs-optional-properties")]
        self.assertTrue(holds, msg="\n".join(f"{d.kind} {d.target_ref}" for d in report.decisions))
        meta, _ = fm_parse(self.vault.path("knowledge/tools/cs-optional-properties.md").read_text(encoding="utf-8"))
        # held 1 + failed 1 → medium base, then failure drop → low
        self.assertEqual(meta["confidence"], "low")
        self.assertEqual(meta["feedback"]["failed"], 1)
        # no destructive action happened
        self.assertEqual(meta["status"], "validated")

    def test_repeated_same_version_failure_proposes_supersede(self):
        for i, day in enumerate(("02", "03")):
            _episode_with_outcome(self.vault, f"2026-09-{day}-cs-fail{i}", "cs-optional-properties",
                                  "failed", "still broken", captured=f"2026-09-{day}T10:00:00+05:30")
        engine.run_compile(self.vault, now=NOW)
        report = engine.run_lint(self.vault, now=NOW)
        props = [d for d in report.decisions if d.kind == "SUPERSEDE" and "cs-optional-properties" in d.target_ref]
        self.assertTrue(props)
        # gated: nothing applied yet
        meta, _ = fm_parse(self.vault.path("knowledge/tools/cs-optional-properties.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "validated")

    def test_different_version_failure_routes_to_supersede(self):
        _episode_with_outcome(self.vault, "2026-09-02-cs-fail2", "cs-optional-properties",
                              "failed", "fails on the 2026-09 build")
        engine.run_compile(self.vault, now=NOW)
        report = engine.run_lint(self.vault, now=NOW)
        props = [d for d in report.decisions if d.kind == "SUPERSEDE" and "different version" in d.rationale]
        self.assertTrue(props)

    def test_supersede_no_dangling_reference(self):
        # a supersession with no successor note must not point superseded_by
        # at a note that was never created (§6: history stays navigable)
        self.test_repeated_same_version_failure_proposes_supersede()
        f = pending_review_files(self.vault)[0]
        f.write_text(f.read_text(encoding="utf-8").replace("[ ] approve   [ ] hold", "[x] approve   [ ] hold"), encoding="utf-8")
        engine.run_compile(self.vault, now=NOW)
        meta, _ = fm_parse(self.vault.path("knowledge/tools/cs-optional-properties.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "superseded")
        ref = meta.get("superseded_by")
        self.assertIsNone(ref, f"superseded_by should be null, got {ref!r}")
        from memory_mesh.notes import resolve_ref

        for di_name in ("copilot-studio",):
            from memory_mesh.indexes import parse_index

            di = parse_index(self.vault.path(f"knowledge/_index/{di_name}.md"), self.vault)
            for _s, e in di.all_entries():
                self.assertIsNotNone(resolve_ref(self.vault, e.ref), f"index links dangling ref {e.ref}")

    def test_approved_supersede_closes_window_and_keeps_history(self):
        self.test_repeated_same_version_failure_proposes_supersede()
        f = pending_review_files(self.vault)[0]
        f.write_text(f.read_text(encoding="utf-8").replace("[ ] approve   [ ] hold", "[x] approve   [ ] hold"), encoding="utf-8")
        engine.run_compile(self.vault, now=NOW)
        p = self.vault.path("knowledge/tools/cs-optional-properties.md")
        self.assertTrue(p.exists())  # old notes are never deleted
        meta, _ = fm_parse(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "superseded")
        self.assertEqual(meta["applies_to"].get("to"), "2026-09-02")
        # moved out of live index sections into Recently changed
        idx = self.vault.path("knowledge/_index/copilot-studio.md").read_text(encoding="utf-8")
        from memory_mesh.indexes import parse_index

        di = parse_index(self.vault.path("knowledge/_index/copilot-studio.md"), self.vault)
        live = [e.ref for s in ("Read first", "Current workarounds") for e in di.sections.get(s, [])]
        self.assertNotIn("cs-optional-properties", live)
        changed = [e.ref for e in di.sections.get("Recently changed", [])]
        self.assertIn("cs-optional-properties", changed)


if __name__ == "__main__":
    unittest.main()
