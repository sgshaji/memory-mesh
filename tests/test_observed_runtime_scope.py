import platform
import tempfile
import unittest
from pathlib import Path

from helpers import make_vault
from test_v2_curation import approve_pending, v2_notes
from v2_helpers import ready_task
from memory_mesh import recall
from memory_mesh.curator import engine
from memory_mesh.experience import create_task
from memory_mesh.learning_flow import submit_proposal


class TestObservedRuntimeScope(unittest.TestCase):
    def test_minor_version_declaration_does_not_generalize_a_single_observed_patch(self):
        vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-runtime-scope-")
        self.addCleanup(work.cleanup)
        major, minor, patch = platform.python_version().split(".")
        proposal = ready_task(vault, Path(work.name), declared_version=f"{major}.{minor}")
        submit_proposal(vault, "task-1", proposal)
        engine.run_compile(vault)
        approve_pending(vault)
        engine.run_compile(vault)
        note = v2_notes(vault)[0]
        self.assertEqual(note.meta["applies_to"]["from"], platform.python_version())
        create_task(
            vault, task_id="different-patch", event_id="start", project="project-b",
            tool="python", version=f"{major}.{minor}.{int(patch) + 1}",
            goal="Check this repo runtime",
            checks={"runtime": "The declared runtime is exercised."},
            facts=["runtime-version-declared"],
        )
        result = recall.recall(vault, "repo runtime", task_id="different-patch", log=False)
        self.assertEqual(result.notes, [])
