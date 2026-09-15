"""User-visible feedback loops in isolated Git-backed synthetic vaults."""

import io
import json
import platform
import re
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from helpers import init_git, make_vault

from memory_mesh.cli import main
from memory_mesh.frontmatter import compose
from memory_mesh.notes import load_note
from memory_mesh.outcomes import record_outcome
from memory_mesh.indexes import list_domain_indexes, load_index, write_index_if_changed
from memory_mesh.curator.analytics import recall_usage
from memory_mesh.curator.review import parse_review_file, pending_review_files


class FeedbackEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.assertTrue(init_git(self.vault), "the CLI acceptance fixture requires Git")
        self.note_path = self.vault.path("knowledge/patterns/validation-order.md")
        self.today = datetime.now(timezone.utc).date().isoformat()

    def call(self, *args, expected=0):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--root", str(self.vault.root), *args])
        self.assertEqual(result, expected, output.getvalue())
        return output.getvalue()

    def finish_session(self, session):
        text = self.call("session-end", "--session", session, "--tool", "cli", "--slug", session)
        match = re.search(r"episode stub: ([^\r\n]+?\.md)", text)
        self.assertIsNotNone(match, text)
        path = match.group(1)
        self.call("episode", "finish", path)
        return self.vault.path(path)

    def skill(self):
        path = self.vault.path("skills/validation-demo.md")
        path.write_text(compose({
            "type": "skill", "title": "Validation demo", "confidence": "high",
            "last_verified": self.today,
            "depends_on": ["knowledge/patterns/validation-order"],
        }, "Run the deterministic validation check before proceeding."), encoding="utf-8")
        return path

    def configure_note_context(self):
        note = load_note(self.note_path, self.vault)
        note.meta["applies_to"] = {"tools": ["fixture-tool"], "version": ">=1.0"}
        self.note_path.write_bytes(compose(note.meta, note.body).encode("utf-8"))

    def held_reports(self, count, *, days_old=0):
        for number in range(count):
            record_outcome(
                self.vault, session_id=f"support-{number}", subject_type="knowledge",
                subject_id="knowledge/patterns/validation-order", outcome="held",
                context={"tool": "fixture-tool", "version": "1.0"},
                event_id=f"support-{number}",
                now=datetime.now(timezone.utc) - timedelta(days=days_old),
            )

    def review_items(self):
        return [
            item for path in pending_review_files(self.vault)
            for item in parse_review_file(path)
        ]

    def test_a_held_feedback_survives_episode_compile_and_replay_once(self):
        self.call("compile")
        before = load_note(self.note_path, self.vault).meta.get("feedback", {}).get("held", 0)
        canonical = self.note_path.read_bytes()
        self.call("recall", "copilot studio validation", "--session", "scenario-a")
        args = (
            "feedback", "validation-order", "#held", "--session", "scenario-a",
            "--tool", "copilot-studio", "--version", "2026-09", "--event-id", "trial-a",
        )
        self.call(*args)
        self.call(*args)
        self.assertEqual(self.note_path.read_bytes(), canonical)
        episode = self.finish_session("scenario-a")
        self.assertIn("Knowledge used", episode.read_text(encoding="utf-8"))
        self.call("compile")
        first = load_note(self.note_path, self.vault).meta["feedback"]
        self.assertEqual(first["held"], before + 1)
        self.call("compile")
        self.assertEqual(load_note(self.note_path, self.vault).meta["feedback"], first)
        explanation = json.loads(self.call("explain", "validation-order"))
        self.assertIn("weighted_held", json.dumps(explanation))

    def test_d_partial_episode_finishes_and_is_mined_without_invented_goal(self):
        path = self.vault.path("episodes/partial-cli.md")
        path.write_text(compose({
            "type": "episode", "tool": "cli", "domains": ["copilot-studio"],
            "captured": datetime.now(timezone.utc).isoformat(),
            "trust": "first-party", "sensitivity": "checked", "status": "raw",
        }, (
            "## Knowledge used\n"
            "- [[validation-order]] held: a deterministic fixture exercised the rule.\n\n"
            "## Candidate learnings\n"
            "- Keep deterministic checks before reasoning (copilot-studio, 2026-09).\n"
        )), encoding="utf-8")
        self.call("episode", "finish", "episodes/partial-cli.md")
        finished = load_note(path, self.vault)
        self.assertEqual(finished.status, "summarised")
        self.assertNotIn("## Goal", finished.body)
        self.call("compile")
        self.assertEqual(load_note(path, self.vault).status, "mined")

    def test_f_empty_recall_creates_an_observable_non_factual_gap(self):
        index = self.vault.path("knowledge/_index/mcp.md")
        index.write_text(compose(
            {"type": "index", "domain": "mcp", "updated": self.today, "links": 0},
            "# MCP\n\n## Read first\n\n## Known failures\n\n## Current workarounds\n\n"
            "## Active project\n\n## Recently verified (30 days)\n\n## Recently changed\n",
        ), encoding="utf-8")
        self.call("recall", "mcp stdio transport", "--session", "scenario-f", "--capture-gap")
        gaps = [
            load_note(path, self.vault) for path in self.vault.path("00-inbox").glob("*.md")
            if load_note(path, self.vault).type == "gap"
        ]
        self.assertEqual(len(gaps), 1)
        self.assertIn("mcp", gaps[0].meta["domains"])
        self.call("recall-quality", "missed", "--session", "scenario-f")
        status = json.loads(self.call("status", "--json"))
        self.assertGreaterEqual(status["recall"]["empty_recalls"], 1)
        self.assertGreaterEqual(status["recall"]["potential_gaps"], 1)
        self.call("compile")
        self.assertEqual(load_note(gaps[0].path, self.vault).type, "gap")
        self.assertNotIn("confidence", load_note(gaps[0].path, self.vault).meta)

    def test_h_stale_dependency_warns_without_rewriting_a_skill(self):
        skill = self.skill()
        original = skill.read_bytes()
        note = load_note(self.note_path, self.vault)
        note.meta["status"] = "stale"
        self.note_path.write_text(compose(note.meta, note.body), encoding="utf-8")
        result = json.loads(self.call("explain", "skills/validation-demo", "--subject", "skill"))
        self.assertTrue(result["evaluation"]["potentially_stale"])
        self.assertTrue(result["evaluation"]["needs_review"])
        self.call("compile")
        self.assertEqual(skill.read_bytes(), original)
        self.call("curate", "--lint-only")
        first_index = self.vault.path("knowledge/_index/copilot-studio.md").read_text(encoding="utf-8")
        self.call("curate", "--lint-only")
        self.assertEqual(self.vault.path("knowledge/_index/copilot-studio.md").read_text(encoding="utf-8"), first_index)

    def test_skill_outcomes_are_captured_without_editing_skill_bodies(self):
        skill = self.skill()
        original = skill.read_bytes()
        for session in ("skill-one", "skill-two"):
            self.call(
                "feedback", "skills/validation-demo", "failed", "--subject", "skill",
                "--session", session, "--reason", "behaviour_changed",
            )
        result = json.loads(self.call("explain", "skills/validation-demo", "--subject", "skill"))
        self.assertTrue(result["evaluation"]["needs_review"])
        self.assertEqual(skill.read_bytes(), original)

    def test_j_legacy_fixture_and_repeated_status_require_no_migration(self):
        self.call("lint")
        self.call("recall", "copilot studio topics", "--no-log")
        self.call("compile")
        self.call("lint")
        before = {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for folder in ("00-inbox", "episodes", "knowledge", "skills")
            for path in self.vault.path(folder).rglob("*.md")
        }
        first = self.call("status", "--json")
        self.assertEqual(self.call("status", "--json"), first)
        after = {
            str(path.relative_to(self.vault.root)): path.read_bytes()
            for folder in ("00-inbox", "episodes", "knowledge", "skills")
            for path in self.vault.path(folder).rglob("*.md")
        }
        self.assertEqual(before, after)

    def test_b_recent_failures_quarantine_old_evidence_and_propagate_to_skills(self):
        self.configure_note_context()
        self.held_reports(10, days_old=365)
        skill = self.skill()
        skill_before = skill.read_bytes()
        for number in range(2):
            self.call(
                "feedback", "validation-order", "#failed", "--session", f"changed-{number}",
                "--event-id", f"changed-{number}", "--reason", "behaviour_changed",
                "--tool", "fixture-tool", "--version", "1.0",
            )
        self.call("compile")
        note = load_note(self.note_path, self.vault)
        self.assertEqual(note.status, "stale")
        self.assertEqual(note.meta["feedback_quarantine"]["reason"], "behaviour_changed")
        self.assertGreaterEqual(note.meta["feedback"]["held"], 10)
        for index in list_domain_indexes(self.vault):
            for section, entries in index.sections.items():
                if section.startswith(("Read first", "Recently verified", "Known failures")):
                    self.assertFalse(any(entry.ref.rsplit("/", 1)[-1] == "validation-order" for entry in entries))
        result = json.loads(self.call("recall", "copilot studio validation", "--no-log", "--json"))
        self.assertFalse(any(item["ref"].rsplit("/", 1)[-1] == "validation-order" for item in result["notes"]))
        health = json.loads(self.call("explain", "skills/validation-demo", "--subject", "skill"))
        self.assertTrue(health["evaluation"]["potentially_stale"])
        self.assertTrue(health["evaluation"]["needs_review"])
        self.assertEqual(skill.read_bytes(), skill_before)
        self.assertTrue(any(
            item.payload.get("review_only") and item.payload.get("subject_ref") == note.ref
            for item in self.review_items()
        ))
        before = note.meta["feedback"]
        self.call("compile")
        self.assertEqual(load_note(self.note_path, self.vault).meta["feedback"], before)

    def test_c_misapplication_is_weak_evidence_not_automatic_quarantine(self):
        self.configure_note_context()
        self.held_reports(3)
        self.call(
            "feedback", "validation-order", "failed", "--session", "misapplied",
            "--reason", "misapplied", "--tool", "fixture-tool", "--version", "1.0",
        )
        self.call("compile")
        self.assertEqual(load_note(self.note_path, self.vault).status, "validated")
        result = json.loads(self.call("explain", "validation-order"))["evaluation"]
        self.assertFalse(result["possible_behaviour_change"])
        self.assertLess(result["evidence"]["weighted_failed"], 0.2)

    def test_e_off_target_routing_creates_reviewable_suggestions_without_rewrite(self):
        router = self.vault.path("knowledge/_index/_domains.md")
        original = router.read_bytes()
        self.call("recall", "repo refactor", "--session", "off-target")
        self.call("recall-quality", "off-target", "--session", "off-target")
        path = self.finish_session("off-target")
        note = load_note(path, self.vault)
        note.body = note.body.replace(
            "## What happened",
            "## What happened\nWorked on Copilot Studio topics, connectors and agent flows.",
        )
        path.write_bytes(compose(note.meta, note.body).encode("utf-8"))
        self.call("compile")
        status = json.loads(self.call("status", "--json"))
        self.assertTrue(any(
            item["suggested_domain"] == "copilot-studio"
            for item in status["routing"]["suggestions"]
        ))
        self.assertTrue(any(item.payload.get("attention_kind") == "routing" for item in self.review_items()))
        self.assertEqual(router.read_bytes(), original)

    def test_g_priority_increases_attention_without_approving_new_claims(self):
        before = set(self.vault.path("knowledge").rglob("*.md"))
        self.call("learn", "Priority fixture normal preserves the local counter (fixture-tool, 1.0)")
        text = self.call(
            "learn", "Priority fixture high checks a separate local counter (fixture-tool, 1.0)",
            "--signal", "high",
        )
        reference = text.split("captured: ", 1)[1].splitlines()[0]
        ranked = json.loads(self.call("explain", reference, "--subject", "candidate"))
        self.assertEqual(ranked["rank"], 1)
        self.call("compile")
        created = set(self.vault.path("knowledge").rglob("*.md")) - before
        self.assertTrue(created)
        self.assertTrue(all(load_note(path, self.vault).status != "validated" for path in created))

    def test_gap_research_new_evidence_and_future_recall_close_the_loop(self):
        self.vault.path("knowledge/_index/mcp.md").write_bytes(compose(
            {"type": "index", "domain": "mcp", "updated": self.today, "links": 0},
            "# MCP\n\n## Read first\n\n## Known failures\n\n## Current workarounds\n\n"
            "## Active project\n\n## Recently verified (30 days)\n\n## Recently changed\n",
        ).encode("utf-8"))
        gap = json.loads(self.call("recall", "mcp stdio canonical payload", "--session", "research-gap", "--capture-gap", "--json"))
        self.assertEqual(gap["notes"], [])
        self.call("compile")
        self.assertEqual(load_note(self.vault.path(gap["gap_candidate"]), self.vault).type, "gap")
        version = platform.python_version()
        expected = json.dumps({"a": 2, "b": 1}, sort_keys=True)
        for number, payload in enumerate(({"b": 1, "a": 2}, {"a": 2, "b": 1})):
            self.assertEqual(json.dumps(payload, sort_keys=True), expected)
            reference = f"episodes/json-research-{number}.md"
            self.vault.path(reference).write_bytes(compose({
                "type": "episode", "tool": "python", "domains": ["mcp"],
                "captured": datetime.now(timezone.utc).isoformat(), "trust": "first-party",
                "sensitivity": "checked", "status": "raw", "session_ref": f"json-research-{number}",
            }, (
                "## Goal\nResearch canonical JSON for MCP payloads.\n\n"
                "## What happened\nA deterministic json.dumps(sort_keys=True) assertion passed "
                "for a distinct input ordering in this fixture.\n\n"
                "## Candidate learnings\n"
                f"- Sort JSON object keys before comparing MCP payload fingerprints (python, {version}).\n"
            )).encode("utf-8"))
            self.call("episode", "finish", reference)
        self.call("compile")
        recalled = json.loads(self.call("recall", "mcp stdio canonical payload", "--no-log", "--json"))
        self.assertTrue(recalled["notes"])
        self.assertTrue(any(
            "payload fingerprints" in path.read_text(encoding="utf-8")
            for path in self.vault.path("knowledge").rglob("*.md")
        ))

    def test_usage_creates_index_advice_without_automatic_promotion(self):
        self.configure_note_context()
        self.held_reports(3)
        reference = "knowledge/patterns/validation-order"
        prior = recall_usage(self.vault).by_ref.get(reference)
        before_count = prior.last_30_days if prior else 0
        for number in range(5):
            result = json.loads(self.call(
                "recall", "copilot studio validation", "--session", f"usage-{number}", "--json",
            ))
            self.assertTrue(any(item["ref"].rsplit("/", 1)[-1] == "validation-order" for item in result["notes"]))
        usage = recall_usage(self.vault).by_ref[reference]
        self.assertEqual(usage.last_30_days, before_count + 5)
        index = load_index(self.vault, "copilot-studio")
        assert index is not None
        index.remove("validation-order")
        index.add("Recently changed", reference, "Fixture placement awaiting review")
        write_index_if_changed(self.vault, index, self.today)
        self.call("compile")
        current = load_index(self.vault, "copilot-studio")
        self.assertFalse(any(entry.ref.rsplit("/", 1)[-1] == "validation-order" for entry in current.sections["Read first"]))
        self.assertTrue(any(
            item.payload.get("attention_kind") == "index"
            and item.payload.get("subject_ref") == reference
            for item in self.review_items()
        ))


if __name__ == "__main__":
    unittest.main()
