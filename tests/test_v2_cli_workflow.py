import io
import json
import platform
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from helpers import make_vault
from test_v2_curation import approve_pending
from memory_mesh import cli, tokens


class TestV2CLIWorkflow(unittest.TestCase):
    def setUp(self):
        self.vault, holder = make_vault()
        self.addCleanup(holder.cleanup)
        work = tempfile.TemporaryDirectory(prefix="mm-public-workflow-")
        self.addCleanup(work.cleanup)
        self.workspace = Path(work.name)
        (self.workspace / "test_runtime.py").write_text(
            "import unittest\nclass Check(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )

    def command(self, args, data=None):
        output = io.StringIO()
        text = json.dumps(data) if data is not None else ""
        with patch("sys.stdin", io.StringIO(text)), redirect_stdout(output), redirect_stderr(output):
            code = cli.main(["--root", str(self.vault.root), *args])
        self.assertEqual(code, 0, output.getvalue())
        return output.getvalue()

    def task(self, task_id, project):
        return {
            "task_id": task_id, "event_id": "start", "project": project,
            "tool": "python", "version": platform.python_version(),
            "goal": "Validate this repo runtime",
            "checks": {"runtime": "The current runtime executes the declared check."},
            "facts": ["runtime-version-declared"],
        }

    def test_public_workflow_reaches_native_session_bound_recall(self):
        self.command(["v2", "profile", "strict"])
        self.command(["v2", "task", "start", "--session", "source-session"], self.task("source", "project-a"))
        self.command([
            "v2", "check", "source", "--event-id", "run", "--revision", "1",
            "--check-id", "runtime", "--workspace", str(self.workspace),
            "--artifact", "test_runtime.py",
        ])
        proposal = {
            "proposal_id": "lesson", "task_revision": 1,
            "title": "Run checks in the declared runtime", "domain": "coding-agents",
            "action": "Use the declared runtime when executing validation.",
            "conditions": ["runtime-version-declared"], "evidence_ids": ["run"],
            "projects": ["project-a", "project-b"],
            "limitations": ["This is a synthetic workflow fixture."],
            "rationale": "Avoid checking a different runtime.",
            "expected_outcome": "passed",
        }
        staged = json.loads(self.command(["v2", "propose", "source"], proposal))
        self.assertEqual(staged["outcome"], "review")
        self.command(["compile"])
        approve_pending(self.vault)
        self.command(["compile"])
        self.command(["v2", "task", "start", "--session", "target-session"], self.task("target", "project-b"))
        result = json.loads(self.command(["recall", "repo runtime", "--session", "target-session", "--json"]))
        self.assertEqual(result["mode"], "strict")
        self.assertEqual(len(result["notes"]), 1)
        self.assertIn(proposal["action"], result["context"])
        self.assertLessEqual(tokens.estimate(json.dumps(result, indent=2)), 2000)
        feedback = json.loads(self.command([
            "v2", "feedback", "target", "--note", result["notes"][0]["ref"],
            "--lesson-revision", result["notes"][0]["revision"], "--event-id", "use-1",
            "--outcome", "failed", "--reason", "The prior conclusion is not sufficient.",
        ]))
        self.assertTrue(feedback["recorded"])
        held = json.loads(self.command(["v2", "recall", "target", "--query", "repo runtime"]))
        self.assertEqual(held["notes"], [])
        self.command(["v2", "profile", "off"])
        disabled = json.loads(self.command(["recall", "repo", "--session", "target-session", "--json"]))
        self.assertEqual(disabled["notes"], [])
        self.assertEqual(disabled["abstention"], "memory_disabled")

    def test_strict_session_start_never_injects_generic_router_content(self):
        self.command(["v2", "profile", "strict"])
        text = self.command(["session-start", "--session", "new-session"])
        self.assertNotIn("| domain |", text)
        self.assertIn("task", text.lower())

    def test_capabilities_do_not_claim_automatic_host_observation(self):
        result = json.loads(self.command(["v2", "capabilities"]))
        self.assertEqual(result["grade"], "assisted")
        self.assertFalse(result["automatic_task_observation"])
        self.assertFalse(result["executes_recalled_commands"])
