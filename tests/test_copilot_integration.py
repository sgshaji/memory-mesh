import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import make_vault

from memory_mesh import recall


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "integrations" / "github-copilot" / "hook.py"
INSTALLER = ROOT / "integrations" / "github-copilot" / "install.py"


def run_hook(vault, action, payload, extra_env=None):
    env = {**os.environ, "MEMORY_MESH_ROOT": str(vault.root), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, str(HOOK), action],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        env=env,
        timeout=30,
    )


class TestCopilotIntegration(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_session_lifecycle_hooks(self):
        start = run_hook(self.vault, "session-start", {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "source": "new",
            "timestamp": 1,
        })
        self.assertEqual(start.returncode, 0, start.stderr)
        self.assertIn("| domain | scope | match |", json.loads(start.stdout)["additionalContext"])
        duplicate_start = run_hook(self.vault, "session-start", {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "source": "new",
            "timestamp": 1,
        })
        self.assertEqual(json.loads(duplicate_start.stdout), {})

        prompt = {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "prompt": "Build a Copilot Studio validation agent",
            "transformedPrompt": "Build a Copilot Studio validation agent",
        }
        first = run_hook(self.vault, "session-prompt", prompt)
        self.assertEqual(first.returncode, 0, first.stderr)
        transformed = json.loads(first.stdout)["modifiedTransformedPrompt"]
        self.assertIn("Memory Mesh session id: copilot-1", transformed)
        self.assertIn("validation-order", transformed)
        self.assertTrue(transformed.endswith(prompt["transformedPrompt"]))

        second = run_hook(self.vault, "session-prompt", prompt)
        self.assertEqual(json.loads(second.stdout), {})

        compact = run_hook(self.vault, "pre-compact", {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "trigger": "auto",
            "timestamp": 2,
        })
        self.assertEqual(compact.returncode, 0, compact.stderr)
        duplicate_compact = run_hook(self.vault, "pre-compact", {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "trigger": "auto",
            "timestamp": 2,
        })
        self.assertEqual(json.loads(duplicate_compact.stdout), {})
        state = recall.load_session_state(self.vault, "copilot-1")
        self.assertEqual(len(state["checkpoints"]), 1)
        self.assertIn("context compacted (auto)", state["checkpoints"][0]["text"])

        end = run_hook(self.vault, "session-end", {
            "sessionId": "copilot-1",
            "cwd": str(self.vault.root),
            "reason": "complete",
        })
        self.assertEqual(end.returncode, 0, end.stderr)
        self.assertEqual(json.loads(end.stdout), {})
        self.assertFalse(recall.session_state_path(self.vault, "copilot-1").exists())
        stubs = list(self.vault.path("episodes").glob("*copilot-session*.md"))
        self.assertEqual(len(stubs), 1)
        self.assertIn("[[validation-order]]", stubs[0].read_text(encoding="utf-8"))

    def test_cloud_agent_environment_is_noop(self):
        result = run_hook(
            self.vault,
            "session-start",
            {"sessionId": "cloud", "cwd": str(self.vault.root)},
            {
                "GITHUB_COPILOT_API_TOKEN": "present",
                "GITHUB_COPILOT_GIT_TOKEN": "present",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertFalse(recall.session_state_path(self.vault, "cloud").exists())

    def test_invalid_hook_payload_fails_explicitly(self):
        result = subprocess.run(
            [sys.executable, str(HOOK), "session-start"],
            input="not-json",
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "MEMORY_MESH_ROOT": str(self.vault.root)},
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid hook input", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_hook_configuration_is_complete(self):
        config = json.loads((ROOT / ".github" / "hooks" / "memory-mesh.json").read_text(encoding="utf-8"))
        self.assertEqual(config["version"], 1)
        self.assertEqual(
            set(config["hooks"]),
            {"sessionStart", "userPromptTransformed", "preCompact", "sessionEnd"},
        )
        for entries in config["hooks"].values():
            self.assertIn("bash", entries[0])
            self.assertIn("powershell", entries[0])

    def test_user_installer_and_uninstaller(self):
        with tempfile.TemporaryDirectory(prefix="mm-copilot-home-") as td:
            home = Path(td)
            install = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                timeout=30,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertTrue((home / "memory-mesh-install.json").exists())
            hook_config = json.loads((home / "hooks" / "memory-mesh.json").read_text(encoding="utf-8"))
            self.assertEqual(hook_config["version"], 1)
            instruction = (home / "instructions" / "memory-mesh.instructions.md").read_text(encoding="utf-8")
            self.assertIn(str(ROOT), instruction)
            for name in ("memory-recall", "memory-learn", "memory-episode"):
                skill = home / "skills" / name / "SKILL.md"
                self.assertTrue(skill.exists())
                self.assertIn(str(ROOT / "integrations" / "github-copilot" / "memory.py"), skill.read_text(encoding="utf-8"))

            resource = home / "skills" / "memory-recall" / "user-resource.txt"
            resource.write_text("keep", encoding="utf-8")
            remove = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                timeout=30,
            )
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertFalse((home / "hooks" / "memory-mesh.json").exists())
            self.assertFalse((home / "instructions" / "memory-mesh.instructions.md").exists())
            self.assertTrue(resource.exists())
            self.assertFalse((home / "memory-mesh-install.json").exists())


if __name__ == "__main__":
    unittest.main()
