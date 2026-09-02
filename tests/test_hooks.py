import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import make_vault

from memory_mesh import cli, config, recall


def run_cli(vault, *argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["--root", str(vault.root), *argv])
    return rc, buf.getvalue()


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.vault, self._tmp = make_vault()

    def tearDown(self):
        if self._tmp:
            self._tmp.cleanup()

    def test_session_start_prints_router_and_project(self):
        rc, out = run_cli(self.vault, "session-start", "--session", "s1", "--cwd", str(self.vault.root / "memory-mesh" / "src"))
        self.assertEqual(rc, 0)
        self.assertIn("| copilot-studio |", out)  # the router table
        self.assertIn("Copilot Studio validation skills", out)  # project note via working_dir match

    def test_recall_once_per_session(self):
        rc, out1 = run_cli(self.vault, "session-prompt", "Build a Copilot Studio validation agent", "--session", "s2")
        self.assertEqual(rc, 0)
        self.assertIn("validation-order", out1)
        rc, out2 = run_cli(self.vault, "session-prompt", "another copilot studio prompt", "--session", "s2")
        self.assertEqual(rc, 0)
        self.assertEqual(out2.strip(), "")  # budget spent: silent no-op

    def test_session_end_writes_stub_from_state(self):
        run_cli(self.vault, "session-prompt", "Build a Copilot Studio validation agent", "--session", "s3")
        rc, out = run_cli(self.vault, "session-end", "--session", "s3", "--slug", "cs-agent", "--tool", "claude-code")
        self.assertEqual(rc, 0)
        self.assertIn("episode stub", out)
        stubs = [p for p in self.vault.path("episodes").glob("*cs-agent*.md")]
        self.assertEqual(len(stubs), 1)
        text = stubs[0].read_text(encoding="utf-8")
        self.assertIn("status: raw", text)
        self.assertIn("[[validation-order]]", text)
        self.assertIn("domains: [copilot-studio]", text)

    def test_session_end_without_retrieval_skips_episode(self):
        rc, out = run_cli(self.vault, "session-end", "--session", "never-recalled")
        self.assertEqual(rc, 0)
        self.assertIn("skipping", out)

    def test_checkpoint_parks_in_state_then_lands_in_stub(self):
        run_cli(self.vault, "session-prompt", "copilot studio work", "--session", "s4")
        run_cli(self.vault, "episode", "checkpoint", "--session", "s4", "--text", "long session checkpoint marker")
        run_cli(self.vault, "session-end", "--session", "s4", "--slug", "chk")
        stubs = list(self.vault.path("episodes").glob("*chk*.md"))
        self.assertTrue(stubs)
        self.assertIn("checkpoint", stubs[0].read_text(encoding="utf-8"))

    def test_hook_scripts_run_as_processes(self):
        # the real mechanism: run the SessionStart hook script with JSON stdin
        hooks_dir = Path(__file__).resolve().parents[1] / "_meta" / "hooks"
        script = hooks_dir / "recall_start.py"
        if not script.exists():
            self.skipTest("hooks not installed in repo checkout")
        payload = json.dumps({"session_id": "hk1", "cwd": str(self.vault.root)})
        env = {"MEMORY_MESH_ROOT": str(self.vault.root)}
        import os

        full_env = {**os.environ, **env}
        r = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, text=True,
                           cwd=str(hooks_dir), env=full_env, timeout=60)
        # hook resolves the vault from its own location (repo), not the temp
        # vault, so just prove it runs and prints a router table
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| domain | scope | match |", r.stdout)

    def test_status_and_doctor(self):
        rc, out = run_cli(self.vault, "status")
        self.assertEqual(rc, 0)
        self.assertIn("knowledge:", out)
        rc, out = run_cli(self.vault, "doctor")
        self.assertIn(rc, (0, 1))  # git missing in temp vault is a reported problem


if __name__ == "__main__":
    unittest.main()
