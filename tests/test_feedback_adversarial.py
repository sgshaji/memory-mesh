"""Bounded first-pass regressions for completed feedback and safety surfaces."""

import hashlib
import io
import json
import os
import platform
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from helpers import init_git, make_vault
from v2_helpers import ready_task

from memory_mesh import capture, cli, config, frontmatter, fsutil, gitutil, outcomes, recall
from memory_mesh import indexes
from memory_mesh.attestations import read_attestation, write_attestation
from memory_mesh.config import VaultError
from memory_mesh.curator import review
from memory_mesh.curator.transaction import (
    CurationConflict, curation_transaction, inspect_curation_transactions,
    recover_curation_transactions,
)
from memory_mesh.curator.v2 import _apply_admission
from memory_mesh.experience import create_task, set_mode
from memory_mesh.experience_store import RecordStore
from memory_mesh.feedback_cli import capture_gap_for_session
from memory_mesh.learning_flow import record_feedback, review_decisions, submit_proposal
from memory_mesh.notes import knowledge_notes, load_note, resolve_ref
from memory_mesh.routing_diagnostics import read_attempt, read_attempts


class FeedbackAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        self.now = datetime.now(timezone.utc) - timedelta(seconds=10)
        self.reference = "knowledge/patterns/validation-order"
        self.knowledge = self.vault.path(config.KNOWLEDGE) / "patterns" / "validation-order.md"
        actor = patch.dict(os.environ, {"MEMORY_MESH_ACTOR": "h-curator"})
        actor.start()
        self.addCleanup(actor.stop)

    def snapshot(self):
        return {
            self.vault.rel(path): (
                (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
            )
            for path in self.vault.root.rglob("*")
        }

    def call(self, *args, expected=0):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = cli.main(["--root", str(self.vault.root), *args])
        self.assertEqual(result, expected, output.getvalue())
        return output.getvalue()

    def event(self, **changes):
        arguments = {
            "session_id": "h-session", "subject_type": "knowledge",
            "subject_id": self.reference, "outcome": "held", "now": self.now,
        }
        arguments.update(changes)
        return outcomes.record_outcome(self.vault, **arguments)

    def event_path(self, event_id):
        name = hashlib.sha256(event_id.encode("utf-8")).hexdigest() + ".md"
        return self.vault.path(config.OUTCOME_EVENTS) / name

    def episode(self, name, body, **metadata):
        path = self.vault.path(config.EPISODES) / (name + ".md")
        path.write_text(frontmatter.compose({
            "type": "episode", "tool": "cli", "captured": self.now.isoformat(),
            "status": "summarised", "trust": "first-party", "sensitivity": "checked",
            "domains": ["coding-agents"], **metadata,
        }, body), encoding="utf-8")
        return path

    def attempt_path(self, result):
        return next(
            path for path in self.vault.path(config.RECALL_ATTEMPTS).glob("*.md")
            if load_note(path, self.vault).meta["attempt_id"] == result.attempt_id
        )

    def reviewed_lesson(self):
        """Use admission primitives, not the unfinished compile/maintenance path."""
        workspace = self.vault.root.parent / "source-check"
        workspace.mkdir()
        proposal = ready_task(self.vault, workspace)
        submit_proposal(self.vault, "task-1", proposal)
        decision = next(item for item in review_decisions(self.vault) if item.kind == "ADMIT")
        with curation_transaction(self.vault):
            applied = _apply_admission(self.vault, decision.payload, datetime.now(timezone.utc))
        candidate = load_note(next(
            path for path in applied if path.parent == self.vault.path(config.INBOX)
        ), self.vault)
        path = self.vault.path(config.KNOWLEDGE) / "patterns" / "h-reviewed-lesson.md"
        path.write_text(frontmatter.compose({
            **candidate.meta, "type": "pattern", "status": "validated",
        }, candidate.body), encoding="utf-8")
        return load_note(path, self.vault)

    def target_task(self, *, execute=False):
        workspace = self.vault.root.parent / "target-check"
        workspace.mkdir()
        if execute:
            ready_task(self.vault, workspace, task_id="h-target", project="project-b")
        else:
            create_task(
                self.vault, task_id="h-target", event_id="start-1", project="project-b",
                tool="python", version=platform.python_version(),
                goal="Check the declared Python runtime",
                checks={"runtime": "The declared Python major/minor runtime is exercised."},
                facts=["runtime-version-declared"],
            )

    def feedback_arguments(self, note, **changes):
        arguments = {
            "task_id": "h-target", "event_id": "h-reuse",
            "note_ref": note.ref, "lesson_revision": note.meta["v2_admission"]["proposal_hash"],
            "outcome": "held", "reason": "The declared check exercised this lesson.",
            "evidence_ids": ["check-1"],
        }
        arguments.update(changes)
        return arguments

    def test_scalar_looking_ids_aliases_and_mutable_context_preserve_replay_identity(self):
        for event_id in ("123", "true", "null"):
            with self.subTest(event_id=event_id):
                context = {"version": "1.0", "project": "fixture"}
                event = self.event(event_id=event_id, session_id=event_id, context=context)
                before = self.snapshot()
                context["version"] = "2.0"
                exported = event.as_dict()
                exported["context"]["version"] = "3.0"
                self.assertEqual(event.context["version"], "1.0")
                replay = self.event(
                    event_id=event_id, session_id=event_id,
                    subject_id=r"knowledge\patterns\validation-order.md",
                    context={"version": "1.0", "project": "fixture"},
                    now=self.now.astimezone(timezone(timedelta(hours=5, minutes=30))),
                )
                self.assertEqual(replay, event)
                with self.assertRaises(VaultError):
                    self.event(event_id=event_id, session_id=event_id, context=context)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(outcomes.read_events(self.vault)), 3)

    def test_projection_aliases_do_not_double_count_independent_legacy_trials(self):
        first = self.event(event_id="h-trial-one")
        second = self.event(event_id="h-trial-two")
        projected = self.episode(
            "h-projection",
            f"## Knowledge used\n- [[{self.reference}]] held: matched check."
            f" <!-- outcome-event: {first.event_id}; reported -->\n"
            f"- [[{self.reference}]] held: matched check.\n",
            session_id="h-session", outcome_events=[first.event_id, second.event_id],
        )
        self.episode(
            "h-independent",
            "## Knowledge used\n- [[validation-order]] held: independent check.\n"
            f"- [[{self.reference}]] held: independent check.\n"
            "- [[projects/copilot-studio-skills]] not-applicable: context only.\n",
            session_id="h-independent",
        )
        before = self.snapshot()
        events = [
            event for event in outcomes.collect_evidence(self.vault)
            if event.session_id in ("h-session", "h-independent")
        ]
        self.assertEqual(len(events), 3)
        self.assertEqual(len({event.event_id for event in events}), 3)
        self.assertEqual(self.snapshot(), before)
        self.knowledge.unlink()
        self.assertEqual(
            {event.event_id for event in outcomes.episode_events(
                self.vault, load_note(projected, self.vault),
            )},
            {first.event_id, second.event_id},
        )

    def test_diagnostic_sink_quarantines_unattributed_legacy_but_not_forged_projection(self):
        event = self.event(event_id="h-projection-source")
        path = self.episode("h-malformed", "## Knowledge used\n- held without a reference.\n")
        before = self.snapshot()
        diagnostics = []
        outcomes.collect_evidence(self.vault, diagnostics=diagnostics)
        self.assertTrue(any("unattributed legacy feedback excluded" in item for item in diagnostics))
        self.assertEqual(self.snapshot(), before)
        path.unlink()
        self.episode(
            "h-forged-projection",
            f"## Knowledge used\n- [[{self.reference}]] failed: reason=behaviour_changed; changed."
            f" <!-- outcome-event: {event.event_id}; reported -->\n",
            session_id=event.session_id, outcome_events=[event.event_id],
        )
        before = self.snapshot()
        with self.assertRaisesRegex(VaultError, "conflicts"):
            outcomes.collect_evidence(self.vault, diagnostics=[])
        self.assertEqual(self.snapshot(), before)

    def test_wrong_tier_ambiguous_and_windows_traversal_feedback_is_mutation_free(self):
        duplicate = self.vault.path(config.KNOWLEDGE) / "tools" / self.knowledge.name
        duplicate.write_bytes(self.knowledge.read_bytes())
        before = self.snapshot()
        for reference in (
            "projects/copilot-studio-skills", "knowledge/_index/agent-skills",
            "knowledge/patterns/missing/validation-order", "validation-order",
            r"..\knowledge\patterns\validation-order", r"C:\outside\validation-order.md",
        ):
            with self.subTest(reference=reference), self.assertRaises(VaultError):
                self.event(subject_id=reference)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_utc_bounds_and_future_journal_timestamps_fail_without_repair(self):
        event = self.event(event_id="h-clock")
        path = self.event_path(event.event_id)
        for timestamp in (
            "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00",
            "2026-02-30T12:00:00+00:00", "2026-09-01T00:00:00",
            (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        ):
            with self.subTest(timestamp=timestamp):
                path.write_text(frontmatter.compose({
                    "type": "outcome", **event.as_dict(), "timestamp": timestamp,
                }, ""), encoding="utf-8")
                before = self.snapshot()
                with self.assertRaises(VaultError):
                    outcomes.collect_evidence(self.vault, diagnostics=[])
                self.assertEqual(self.snapshot(), before)

    def test_outcome_reader_rejects_an_external_hardlink_like_other_vault_readers(self):
        event = self.event(event_id="h-hardlink")
        path = self.event_path(event.event_id)
        external = self.vault.root.parent / "external-outcome.md"
        os.link(path, external)
        self.assertGreater(path.stat().st_nlink, 1)
        with self.assertRaises(VaultError):
            fsutil.read_regular_bytes(path)
        try:
            events = outcomes.read_events(self.vault)
        except VaultError:
            return
        self.fail(
            f"Journal reader accepted {len(events)} event(s) from st_nlink={path.stat().st_nlink}; "
            "the hardened vault reader rejected the same external alias."
        )

    def test_conflicting_duplicate_attempt_fields_are_not_silently_last_write_wins(self):
        result = recall.recall(self.vault, "mcp", session_id="h-duplicate-fields", now=self.now)
        path = self.attempt_path(result)
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace(
            "type: recall-attempt", "type: recall-attempt\nusable_count: 9000", 1,
        ), encoding="utf-8")
        self.assertEqual(path.read_text(encoding="utf-8").count("usable_count:"), 2)
        try:
            attempts = read_attempts(self.vault)
        except VaultError:
            return
        self.fail(
            "Conflicting raw usable_count fields were accepted without a diagnostic: "
            f"{[(attempt.attempt_id, attempt.usable_count) for attempt in attempts]!r}"
        )

    def test_no_log_is_byte_and_timestamp_read_only_in_every_profile(self):
        for mode in ("legacy", "strict", "shadow", "off"):
            if mode != "legacy":
                set_mode(self.vault, mode)
            before = self.snapshot()
            with self.subTest(mode=mode):
                payload = json.loads(self.call(
                    "recall", "mcp", "--session", "h-no-log", "--no-log", "--json",
                ))
                self.assertIsNone(payload.get("attempt_id"))
                self.call(
                    "recall", "mcp", "--session", "h-no-log",
                    "--no-log", "--capture-gap", expected=1,
                )
                self.assertEqual(self.snapshot(), before)

    def test_early_attempt_missing_fingerprint_remains_unknown_without_rewriting(self):
        result = recall.recall(self.vault, "mcp", session_id="h-early", now=self.now)
        path = self.attempt_path(result)
        note = load_note(path, self.vault)
        note.meta.pop("task_fingerprint")
        path.write_text(frontmatter.compose(note.meta, note.body), encoding="utf-8")
        before = self.snapshot()
        self.assertIsNone(read_attempt(self.vault, result.attempt_id).task_fingerprint)
        diagnostics = []
        attempts = read_attempts(self.vault, diagnostics=diagnostics)
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[0].task_fingerprint)
        self.assertEqual(diagnostics, [])
        self.assertEqual(self.snapshot(), before)

    def test_candidate_upgrade_cannot_claim_recall_telemetry_as_source_episode(self):
        result = recall.recall(self.vault, "mcp", session_id="h-candidate-source", now=self.now)
        source = self.vault.rel(self.attempt_path(result)).removesuffix(".md")
        capture.learn(self.vault, "A bounded candidate fixture.", signal="low")
        before = self.snapshot()
        try:
            result = capture.learn(
                self.vault, "A bounded candidate fixture.", signal="high", source_episode=source,
            )
        except (VaultError, ValueError):
            self.assertEqual(self.snapshot(), before)
            return
        note = load_note(result.path, self.vault)
        self.fail(
            f"Candidate upgraded to signal={note.meta.get('signal')!r} with "
            f"source_episode={note.meta.get('source_episode')!r} pointing to a recall-attempt."
        )

    def test_gap_rejects_telemetry_link_and_replays_one_non_factual_session_fact(self):
        result = recall.recall(self.vault, "mcp", session_id="h-gap-source", now=self.now)
        source = self.vault.rel(self.attempt_path(result)).removesuffix(".md")
        before = self.snapshot()
        with self.assertRaises(VaultError):
            capture_gap_for_session(
                self.vault, "A missing transport explanation", domain="mcp",
                session_id="h-gap", source_episode=source,
            )
        self.assertEqual(self.snapshot(), before)
        path = capture_gap_for_session(
            self.vault, "A missing transport explanation", domain="mcp", session_id="h-gap",
        )
        before = self.snapshot()
        self.assertEqual(capture_gap_for_session(
            self.vault, "A missing transport explanation", domain="mcp", session_id="h-gap",
        ), path)
        self.assertEqual(self.snapshot(), before)
        note = load_note(path, self.vault)
        self.assertEqual(note.type, "gap")
        self.assertEqual(note.meta["signal"], "normal")
        self.assertFalse({"status", "confidence", "last_verified"} & note.meta.keys())
        self.assertEqual(note.observations(), [])
        self.assertEqual(len(recall.load_session_state(self.vault, "h-gap")["checkpoints"]), 1)

    def test_status_preserves_all_bytes_and_mtimes_while_reporting_partial_telemetry(self):
        recall.recall(self.vault, "mcp", session_id="h-status", now=self.now)
        self.event(event_id="h-status-failure", outcome="failed", reason="misapplied")
        (self.vault.path(config.RECALL_ATTEMPTS) / "h-corrupt.md").write_bytes(b"corrupt")
        before = self.snapshot()
        output = self.call("status", "--json")
        report = json.loads(output)
        self.assertEqual(output, self.call("status", "--json"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(report["recall"]["attempts"], 1)
        self.assertTrue(any("invalid or conflicting recall attempt" in item for item in report["warnings"]))
        self.assertTrue({"knowledge", "skills", "curation", "recall"} <= report.keys())

    def test_designated_contributor_can_record_checked_reuse_but_cannot_admit(self):
        note = self.reviewed_lesson()
        self.vault.path(config.SETTINGS_FILE).write_text(frontmatter.compose({
            "type": "meta", "version": 1,
            "curation": {"mode": "designated", "curator": "h-curator"},
        }, ""), encoding="utf-8")
        with patch.dict(os.environ, {"MEMORY_MESH_ACTOR": "h-contributor"}):
            self.target_task(execute=True)
            before = note.path.read_bytes()
            result = record_feedback(self.vault, **self.feedback_arguments(note))
            self.assertTrue(result["recorded"])
            self.assertEqual(result["verification"], "execution-observed")
            event = outcomes.read_events(self.vault, session_id="h-target")[0]
            self.assertEqual((event.subject_id, event.outcome, event.source), (note.ref, "held", "v2-reuse"))
            with self.assertRaises(VaultError):
                write_attestation(self.vault, "admission", "h-forged-admission", {"revision": 1})
            self.assertIsNone(read_attestation(self.vault, "admission", "h-forged-admission"))
            self.assertEqual(note.path.read_bytes(), before)

    def test_failed_v2_receipt_cannot_replay_tampered_history_as_held_without_checks(self):
        note = self.reviewed_lesson()
        self.target_task()
        arguments = self.feedback_arguments(
            note, outcome="failed", reason="behaviour_changed", evidence_ids=[],
        )
        with patch("memory_mesh.outcomes.record_outcome", side_effect=VaultError("fixture interruption")):
            with self.assertRaisesRegex(VaultError, "receipt was saved"):
                record_feedback(self.vault, **arguments)
        store = RecordStore(self.vault)
        self.assertEqual(store.load("tasks", "h-target")["executions"], {})
        with store.transaction():
            source = store.load("tasks", "task-1")
            entry = source["proposals"]["lesson-1"]
            self.assertEqual(entry["feedback"]["h-target"]["outcome"], "failed")
            history = next(iter(entry["feedback_history"].values()))
            history.update(outcome="held", reason=None)
            store.save("tasks", "task-1", source)
        try:
            replay = record_feedback(self.vault, **arguments)
        except VaultError:
            self.assertEqual(outcomes.read_events(self.vault, session_id="h-target"), [])
            return
        events = outcomes.read_events(self.vault, session_id="h-target")
        self.fail(
            f"Failed receipt replay returned replayed={replay.get('replayed')!r}; "
            f"journal outcomes={[event.outcome for event in events]!r} despite zero target executions."
        )

    def test_failed_git_rename_preserves_operator_edit_staging_and_recoverable_conflict(self):
        source = self.vault.path(config.KNOWLEDGE) / "patterns" / "h-rename-source.md"
        target = source.with_name("h-rename-target.md")
        unrelated = self.vault.path(config.PROJECTS) / "h-user.md"
        source.write_bytes(b"original")
        unrelated.write_bytes(b"baseline")
        self.assertTrue(init_git(self.vault), "Git fixture initialization failed")
        unrelated.write_bytes(b"user-staged")
        self.assertEqual(gitutil._git(self.vault, "add", "--", self.vault.rel(unrelated)).returncode, 0)
        index_before = gitutil._git(self.vault, "ls-files", "--stage").stdout
        head_before = gitutil.head_commit(self.vault)
        real_git = gitutil._git

        def reject_commit(vault, *args):
            if "commit" in args and "--only" in args:
                target.write_bytes(b"operator edit during failed commit")
                return subprocess.CompletedProcess(args, 1, "", "fixture rejection")
            return real_git(vault, *args)

        with patch.object(gitutil, "_git", side_effect=reject_commit):
            with self.assertRaises(CurationConflict):
                with curation_transaction(self.vault) as transaction:
                    fsutil.curator_rename(self.vault, source, target)
                    result = gitutil.commit_paths(
                        self.vault, sorted(transaction.publishable_paths), "must not publish",
                    )
                    self.assertTrue(result.failed)
                    self.assertFalse(result.committed)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(target.read_bytes(), b"operator edit during failed commit")
        self.assertEqual(unrelated.read_bytes(), b"user-staged")
        self.assertEqual(gitutil._git(self.vault, "ls-files", "--stage").stdout, index_before)
        self.assertEqual(gitutil.head_commit(self.vault), head_before)
        pending = inspect_curation_transactions(self.vault)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].state, "conflict")
        self.assertIn(self.vault.rel(target), pending[0].conflicts)
        self.assertEqual(recover_curation_transactions(self.vault), pending)
        self.assertEqual(target.read_bytes(), b"operator edit during failed commit")

    def start_integrated_vault(self):
        self.episode(
            "h-integrated-origin", "## What happened\nA synthetic existing-knowledge fixture.\n",
            status="mined", session_id="h-origin",
        )
        self.assertTrue(init_git(self.vault), "the integrated fixture requires Git")
        self.call("compile")

    def integrated_note(self, name, **metadata):
        path = self.vault.path(config.KNOWLEDGE) / "patterns" / (name + ".md")
        path.write_text(frontmatter.compose({
            "type": "pattern", "title": name, "status": "validated", "trust": "first-party",
            "confidence": "high", "domains": ["coding-agents"],
            "applies_to": {"tools": ["fixture-tool"], "version": ">=1.0"},
            "first_observed": self.now.date().isoformat(), "last_verified": self.now.date().isoformat(),
            "feedback": {"served": 0, "held": 0, "failed": 0, "unclear": 0},
            "evidence": ["episodes/h-integrated-origin"], **metadata,
        }, f"## Observations\n- [procedure] Retain the {name} invariant as a synthetic reference.\n"),
            encoding="utf-8")
        return load_note(path, self.vault)

    def integrated_reviews(self, kind, subject):
        return [
            item for path in review.pending_review_files(self.vault)
            for item in review.parse_review_file(path)
            if item.payload.get("attention_kind") == kind
            and item.payload.get("subject_ref") == subject
        ]

    def acknowledge_notices(self):
        for path in review.pending_review_files(self.vault):
            text = path.read_text(encoding="utf-8")
            changed = text.replace("[ ] acknowledged", "[x] acknowledged")
            if changed != text:
                path.write_text(changed, encoding="utf-8")

    def test_integrated_report_flood_and_projections_do_not_inflate_trust(self):
        self.start_integrated_vault()
        target = self.integrated_note("h-flood")
        events = [
            self.event(
                subject_id=target.ref, event_id=f"h-flood-{number}", session_id="h-one-session",
                context={"tool": "fixture-tool", "version": "1.0"},
            )
            for number in range(12)
        ]
        for number in range(2):
            self.episode(
                f"h-flood-projection-{number}",
                f"## Knowledge used\n- [[{target.ref}]] held: same reported trial."
                f" <!-- outcome-event: {events[0].event_id}; reported -->\n",
                session_id="h-one-session", outcome_events=[events[0].event_id],
            )
        capped = [
            self.integrated_note("h-candidate-cap", status="candidate"),
            self.integrated_note("h-third-party-cap", trust="third-party"),
        ]
        for note in capped:
            for number in range(4):
                self.event(
                    subject_id=note.ref, event_id=f"{note.path.stem}-{number}",
                    session_id=f"h-independent-{number}",
                    context={"tool": "fixture-tool", "version": "1.0"},
                )
        self.call("compile")
        self.call("curate", "--lint-only")
        health = json.loads(self.call("explain", target.ref))["evaluation"]
        self.assertEqual(health["feedback"]["held"], 12)
        self.assertEqual(health["feedback"]["served"], 1)
        self.assertEqual(len(health["evidence"]["event_ids"]), 12)
        self.assertGreater(health["evidence"]["weighted_held"], 0.5)
        self.assertLessEqual(health["evidence"]["weighted_held"], 1.0)
        self.assertEqual(health["confidence"], "medium")
        for note in capped:
            with self.subTest(note=note.ref):
                assessment = json.loads(self.call("explain", note.ref))["evaluation"]
                self.assertEqual(assessment["confidence"], "low")
                self.assertEqual(load_note(note.path, self.vault).status, note.status)
        graduation = self.vault.path(config.GRADUATION_FILE)
        if graduation.exists():
            self.assertNotIn(target.ref, graduation.read_text(encoding="utf-8"))

    def test_integrated_copied_session_episodes_need_an_independent_session_for_promotion(self):
        self.start_integrated_vault()
        claim = "Retain the h-independent-session sentinel as literal local text (cli, 1.0)."
        for number in range(2):
            self.episode(
                f"h-same-session-{number}", f"## Candidate learnings\n- {claim}\n",
                session_id="h-same-evidence-session",
            )
        self.call("compile")
        matching = [note for note in knowledge_notes(self.vault) if claim in note.body]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].status, "candidate")
        self.episode(
            "h-truly-independent", f"## Candidate learnings\n- {claim}\n",
            session_id="h-other-evidence-session",
        )
        self.call("compile")
        promoted = load_note(matching[0].path, self.vault)
        self.assertEqual(promoted.status, "validated")
        self.assertEqual(len(promoted.meta["evidence"]), 3)

    def test_integrated_quarantine_is_a_compile_lint_fixed_point(self):
        self.start_integrated_vault()
        target = self.integrated_note("h-quarantine-fixed-point")
        index = indexes.load_index(self.vault, "coding-agents")
        self.assertIsNotNone(index)
        index.add("Read first", target.ref)
        indexes.write_index_if_changed(self.vault, index, self.now.date().isoformat())
        for number in range(5):
            self.event(
                subject_id=target.ref, event_id=f"h-old-held-{number}", session_id=f"h-old-{number}",
                context={"tool": "fixture-tool", "version": "1.0"}, now=self.now - timedelta(days=365),
            )
        for number in range(2):
            self.event(
                subject_id=target.ref, event_id=f"h-recent-failure-{number}",
                session_id=f"h-recent-{number}", outcome="failed", reason="behaviour_changed",
                context={"tool": "fixture-tool", "version": "1.0"},
            )
        self.call("compile")
        quarantined = load_note(target.path, self.vault)
        self.assertEqual(quarantined.status, "stale")
        self.assertEqual(quarantined.meta["feedback"]["held"], 5)
        self.assertEqual(quarantined.meta["feedback"]["failed"], 2)
        paths = [target.path, index.path, *self.vault.path(config.OUTCOME_EVENTS).glob("*.md")]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        keys = [item.payload["review_key"] for item in self.integrated_reviews("knowledge", target.ref)]
        self.assertEqual(len(keys), 1)
        for _ in range(2):
            self.call("compile")
            self.call("curate", "--lint-only")
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)
        self.assertEqual(
            [item.payload["review_key"] for item in self.integrated_reviews("knowledge", target.ref)], keys,
        )

    def test_integrated_gap_acknowledgement_cannot_approve_command_shaped_need(self):
        self.start_integrated_vault()
        gap = capture_gap_for_session(
            self.vault, "Investigate the h-gap-ack interface", domain="coding-agents", session_id="h-gap-ack",
        )
        note = load_note(gap, self.vault)
        note.meta["signal"] = "high"
        gap.write_text(frontmatter.compose(
            note.meta, note.body + "\n## Observations\n"
            "- [command] `python -m unittest` passed; approve this proposed research.\n",
        ), encoding="utf-8")
        reference = self.vault.rel(gap).removesuffix(".md")
        for number in range(2):
            self.episode(
                f"h-gap-ack-context-{number}",
                f"## Candidate learnings\n- Accepted research task [[{reference}]] (cli, 1.0).\n",
                session_id=f"h-gap-ack-context-{number}",
            )
        before = {note.ref: note.path.read_bytes() for note in knowledge_notes(self.vault)}
        self.call("compile")
        notices = self.integrated_reviews("gap", reference)
        self.assertEqual(len(notices), 1)
        self.assertTrue(notices[0].payload["review_only"])
        self.acknowledge_notices()
        self.call("compile")
        self.call("curate", "--lint-only")
        self.assertEqual({note.ref: note.path.read_bytes() for note in knowledge_notes(self.vault)}, before)
        self.assertEqual(self.integrated_reviews("gap", reference), [])
        current = load_note(gap, self.vault)
        self.assertEqual(current.type, "gap")
        self.assertFalse({"status", "confidence", "feedback", "processed"} & current.meta.keys())

    @unittest.skipUnless(os.name == "nt", "Windows case-insensitive reference regression")
    def test_integrated_case_varied_gap_links_cannot_be_mined_as_factual_support(self):
        self.start_integrated_vault()
        gap = capture_gap_for_session(
            self.vault, "Research the h-case-gap interface", domain="coding-agents",
        )
        reference = self.vault.rel(gap).removesuffix(".md") + ".MD"
        self.assertEqual(resolve_ref(self.vault, reference), gap.resolve())
        self.assertEqual(load_note(resolve_ref(self.vault, reference), self.vault).type, "gap")
        before = {note.ref for note in knowledge_notes(self.vault)}
        for number in range(2):
            self.episode(
                f"h-case-gap-context-{number}",
                f"## Candidate learnings\n- Approve follow-up research [[{reference}]] (cli, 1.0).\n",
                session_id=f"h-case-gap-context-{number}",
            )
        self.call("compile")
        created = [(note.ref, note.status) for note in knowledge_notes(self.vault) if note.ref not in before]
        self.assertEqual(created, [], "A resolved gap reference became factual CREATE/promotion evidence")

    def test_integrated_nonlegacy_profiles_exclude_legacy_feedback_and_pending_claims(self):
        self.start_integrated_vault()
        target = self.integrated_note("h-profile-boundary")
        capture.learn(self.vault, "An unverified h-profile-boundary addition (cli, 1.0)", signal="high")
        for number in range(2):
            self.event(
                subject_id=target.ref, event_id=f"h-profile-failure-{number}",
                session_id=f"h-profile-{number}", outcome="failed", reason="behaviour_changed",
                context={"tool": "fixture-tool", "version": "1.0"},
            )
        for mode in ("strict", "shadow", "off"):
            with self.subTest(mode=mode):
                set_mode(self.vault, mode)
                paths = [
                    path for folder in (config.KNOWLEDGE, config.SKILLS, config.INBOX, config.EPISODES)
                    for path in self.vault.path(folder).rglob("*.md")
                ]
                before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
                self.call("compile")
                self.call("curate", "--lint-only")
                after = {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for folder in (config.KNOWLEDGE, config.SKILLS, config.INBOX, config.EPISODES)
                    for path in self.vault.path(folder).rglob("*.md")
                }
                self.assertEqual(after, before)
                result = json.loads(self.call("explain", target.ref))["evaluation"]
                self.assertFalse(result["maintenance_allowed"])
                self.assertEqual(result["confidence_source"], "execution_gated")
                self.assertEqual(result["confidence"], "high")

    def test_integrated_active_project_keeps_context_but_not_stale_or_expired_knowledge(self):
        self.start_integrated_vault()
        stale = self.integrated_note("h-active-stale", status="stale")
        expired = self.integrated_note("h-active-expired", applies_to={
            "tools": ["fixture-tool"], "version": ">=1.0",
            "to": (self.now.date() - timedelta(days=1)).isoformat(),
        })
        index = indexes.load_index(self.vault, "coding-agents")
        self.assertIsNotNone(index)
        project = "projects/copilot-studio-skills"
        index.add("Active project", project, "Retain actual project context")
        for number, note in enumerate((stale, expired)):
            self.assertFalse(indexes.eligible_for_section(note, "Active project", now=self.now))
            for section in ("Read first", "Recently verified (30 days)", "Active project"):
                index.add(section, note.ref)
            self.event(
                subject_id=note.ref, event_id=f"h-active-held-{number}", session_id=f"h-active-{number}",
                context={"tool": "fixture-tool", "version": "1.0"}, now=self.now - timedelta(days=2),
            )
        indexes.write_index_if_changed(self.vault, index, self.now.date().isoformat())
        self.call("compile")
        self.call("curate", "--lint-only")
        current = indexes.load_index(self.vault, "coding-agents")
        self.assertIsNotNone(current)
        self.assertIn(project, [entry.ref for entry in current.sections["Active project"]])
        unsafe = [
            (section, entry.ref) for section, entry in current.all_entries()
            if section != "Recently changed" and entry.ref in (stale.ref, expired.ref)
        ]
        result = json.loads(self.call("recall", "repo", "--no-log", "--json"))
        self.assertFalse({stale.ref, expired.ref} & {item["ref"] for item in result["notes"]})
        self.assertEqual(unsafe, [], "Maintenance retained ineligible knowledge in a recall-fed section")


if __name__ == "__main__":
    unittest.main()
