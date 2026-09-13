import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import make_vault

from memory_mesh import frontmatter, recall


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
            self.assertIn("do not wait for the user", instruction)
            for name in ("memory-recall", "memory-learn", "memory-episode"):
                skill = home / "skills" / name / "SKILL.md"
                self.assertTrue(skill.exists())
                self.assertIn(str(ROOT / "integrations" / "github-copilot" / "memory.py"), skill.read_text(encoding="utf-8"))
            learn_skill = (home / "skills" / "memory-learn" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(" --structured --tool github-copilot", learn_skill)
            self.assertIn(
                str(ROOT),
                (home / "skills" / "memory-episode" / "SKILL.md").read_text(encoding="utf-8"),
            )

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

    def test_installer_refuses_new_path_collision_during_upgrade(self):
        with tempfile.TemporaryDirectory(prefix="mm-copilot-home-") as td:
            home = Path(td)
            first = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            manifest_path = home / "memory-mesh-install.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rel = "skills/memory-learn/SKILL.md"
            manifest["files"].pop(rel)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            upgrade = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(upgrade.returncode, 1)
            self.assertIn("newly managed existing files", upgrade.stderr)

    def test_uninstaller_rejects_manifest_path_escape(self):
        with tempfile.TemporaryDirectory(prefix="mm-copilot-home-") as td:
            base = Path(td)
            home = base / "copilot"
            home.mkdir()
            victim = base / "victim.txt"
            victim.write_text("keep", encoding="utf-8")
            (home / "memory-mesh-install.json").write_text(json.dumps({
                "version": 1,
                "files": {"../victim.txt": "not-relevant"},
            }), encoding="utf-8")

            remove = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(remove.returncode, 1)
            self.assertIn("escapes Copilot home", remove.stderr)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

    def test_installer_rejects_symlinked_managed_directory(self):
        with tempfile.TemporaryDirectory(prefix="mm-copilot-home-") as td:
            base = Path(td)
            home = base / "copilot"
            outside = base / "outside"
            home.mkdir()
            outside.mkdir()
            try:
                (home / "hooks").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            install = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(install.returncode, 1)
            self.assertIn("contains a symlink", install.stderr)
            self.assertFalse((outside / "memory-mesh.json").exists())

    def test_uninstaller_rejects_symlinked_managed_file(self):
        with tempfile.TemporaryDirectory(prefix="mm-copilot-home-") as td:
            home = Path(td) / "copilot"
            install = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            hook = home / "hooks" / "memory-mesh.json"
            target = home / "target.json"
            target.write_text(hook.read_text(encoding="utf-8"), encoding="utf-8")
            hook.unlink()
            try:
                hook.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            remove = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(remove.returncode, 1)
            self.assertIn("contains a symlink", remove.stderr)
            self.assertTrue(target.exists())


class TestRepositorySkills(unittest.TestCase):
    SKILLS = ("idea-refine", "interview-me", "spec-driven-development")
    SOURCE_COMMIT = "be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39"

    def test_skill_manifests_and_attribution(self):
        for name in self.SKILLS:
            with self.subTest(skill=name):
                directory = ROOT / ".github" / "skills" / name
                meta, body = frontmatter.parse(
                    (directory / "SKILL.md").read_text(encoding="utf-8")
                )
                self.assertEqual(meta["name"], name)
                self.assertIsInstance(meta["description"], str)
                self.assertTrue(0 < len(meta["description"]) <= 1024)
                self.assertIn(f"/{self.SOURCE_COMMIT}/skills/{name}", body)
                self.assertIn("[LICENSE](LICENSE)", body)
                license_text = (directory / "LICENSE").read_text(encoding="utf-8")
                self.assertIn("MIT License", license_text)
                self.assertIn("Copyright (c) 2025 Addy Osmani", license_text)
                self.assertIn("THE SOFTWARE IS PROVIDED", license_text)

    def test_idea_refine_supporting_files_are_bundled(self):
        directory = ROOT / ".github" / "skills" / "idea-refine"
        body = (directory / "SKILL.md").read_text(encoding="utf-8")
        for filename in ("examples.md", "frameworks.md", "refinement-criteria.md"):
            with self.subTest(file=filename):
                self.assertIn(f"`{filename}`", body)
                self.assertTrue((directory / filename).read_text(encoding="utf-8").strip())

    def test_skills_have_no_executable_or_unavailable_tool_requirements(self):
        for name in self.SKILLS:
            with self.subTest(skill=name):
                directory = ROOT / ".github" / "skills" / name
                for path in directory.rglob("*"):
                    if path.is_file():
                        self.assertTrue(path.suffix == ".md" or path.name == "LICENSE")
                body = (directory / "SKILL.md").read_text(encoding="utf-8")
                self.assertNotIn("AskUserQuestion", body)
                self.assertNotIn("$ARGUMENTS", body)
                self.assertNotIn("scripts/idea-refine.sh", body)
                self.assertNotIn("skills/incremental-implementation/SKILL.md", body)


if __name__ == "__main__":
    unittest.main()
