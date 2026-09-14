"""Synthetic check/lesson fixtures, not a product-benefit benchmark."""

import platform
from pathlib import Path

from memory_mesh.experience import create_task, set_mode
from memory_mesh.task_execution import execute_check


def ready_task(vault, workspace: Path, *, task_id="task-1", project="project-a", declared_version=None):
    version = platform.python_version()
    expected = tuple(int(part) for part in version.split(".")[:2])
    (workspace / "test_runtime.py").write_text(
        "import sys\nimport unittest\n"
        "class RuntimeCheck(unittest.TestCase):\n"
        "    def test_runtime(self):\n"
        f"        self.assertEqual(sys.version_info[:2], {expected!r})\n",
        encoding="utf-8",
    )
    set_mode(vault, "strict")
    create_task(
        vault, task_id=task_id, event_id="start-1", project=project,
        tool="python", version=declared_version or version,
        goal="Check the declared Python runtime",
        checks={"runtime": "The declared Python major/minor runtime is exercised."},
        facts=["runtime-version-declared"],
    )
    execute_check(
        vault, task_id, event_id="check-1", expected_revision=1,
        check_id="runtime", workspace=workspace, artifacts=["test_runtime.py"],
    )
    return {
        "proposal_id": "lesson-1", "task_revision": 1,
        "title": "Use the declared Python runtime for validation",
        "domain": "coding-agents",
        "action": "Execute validation with the declared Python runtime.",
        "conditions": ["runtime-version-declared"],
        "evidence_ids": ["check-1"],
        "projects": ["project-a", "project-b"],
        "limitations": ["Synthetic fixture; no general performance benefit is established."],
        "rationale": "Avoid validating a different runtime by accident.",
        "expected_outcome": "passed",
    }
