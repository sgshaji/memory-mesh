import json
import platform
import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from test_v2_curation import approve_pending, v2_notes
from v2_helpers import ready_task
from memory_mesh import recall, tokens
from memory_mesh.curator import engine
from memory_mesh.experience import create_task, revise_task, set_mode
from memory_mesh.learning_flow import submit_proposal


class TestConditionalRecall(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-recall-v2-")
        self.addCleanup(work.cleanup)
        self.payload = ready_task(self.vault, Path(work.name))
        submit_proposal(self.vault, "task-1", self.payload)
        engine.run_compile(self.vault)
        approve_pending(self.vault)
        engine.run_compile(self.vault)
        self.note = v2_notes(self.vault)[0]

    def target(self, *, project="project-b", version=None, facts=None):
        return create_task(
            self.vault, task_id="target", event_id="start", project=project,
            tool="python", version=version or platform.python_version(),
            goal="Validate this repo with the declared runtime",
            checks={"runtime": "The declared runtime is exercised."},
            facts=["runtime-version-declared"] if facts is None else facts,
        )

    def recall(self):
        return recall.recall(self.vault, "repo runtime", task_id="target", log=False)

    def test_missing_context_abstains_instead_of_loading_generic_notes(self):
        result = recall.recall(self.vault, "repo", log=False)
        self.assertEqual(result.notes, [])
        self.assertEqual(result.abstention, "missing_task_context")
        self.assertNotIn("validation-order", result.context_markdown())

    def test_matching_second_project_receives_a_bounded_reviewed_brief(self):
        self.target()
        result = self.recall()
        self.assertEqual([note.ref for note in result.notes], [self.note.ref])
        self.assertEqual(result.mode, "strict")
        self.assertIn(self.payload["action"], result.context_markdown())
        self.assertLessEqual(tokens.estimate(result.context_markdown()), 2000)
        self.assertLessEqual(tokens.estimate(json.dumps(result.as_payload(), indent=2)), 2000)
        self.assertLessEqual(result.token_total, 2000)

    def test_unapproved_project_is_not_a_match(self):
        self.target(project="project-c")
        self.assertEqual(self.recall().notes, [])

    def test_wrong_version_is_not_a_match(self):
        self.target(version="3.99.99")
        self.assertEqual(self.recall().notes, [])

    def test_unknown_conditions_are_not_assumed_true(self):
        self.target(facts=[])
        self.assertEqual(self.recall().notes, [])

    def test_later_correction_holds_future_reuse(self):
        self.target()
        revise_task(
            self.vault, "task-1", event_id="correction", expected_revision=1,
            relation="correction", reason="The previous conclusion remains unresolved.",
        )
        self.assertEqual(self.recall().notes, [])

    def test_changed_requirements_do_not_falsify_old_scoped_evidence(self):
        self.target()
        revise_task(
            self.vault, "task-1", event_id="new-requirement", expected_revision=1,
            relation="requirement_change", reason="A new requirement was added.",
            goal="Add an additional output format to this repo",
        )
        self.assertEqual([note.ref for note in self.recall().notes], [self.note.ref])

    def test_modified_canonical_claim_is_not_injected(self):
        self.target()
        self.note.path.write_text(
            self.note.path.read_text(encoding="utf-8").replace(
                self.payload["action"], "An unreviewed replacement action.",
            ),
            encoding="utf-8",
        )
        result = self.recall()
        self.assertEqual(result.notes, [])
        self.assertNotIn("unreviewed replacement", result.context_markdown())

    def test_off_is_not_a_return_to_legacy_recall(self):
        self.target()
        set_mode(self.vault, "off")
        result = self.recall()
        self.assertEqual(result.notes, [])
        self.assertEqual(result.abstention, "memory_disabled")
