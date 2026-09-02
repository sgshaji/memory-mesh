"""Test scaffolding: build a hermetic temp vault from tests/fixtures/vault."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_mesh.config import Vault  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vault"


def make_vault(tmp: Path | None = None) -> tuple[Vault, tempfile.TemporaryDirectory | None]:
    holder = None
    if tmp is None:
        holder = tempfile.TemporaryDirectory(prefix="mm-test-")
        tmp = Path(holder.name)
    root = Path(tmp) / "vault"
    shutil.copytree(FIXTURES, root)
    vault = Vault(root)
    vault.scaffold()
    return vault, holder


def init_git(vault: Vault) -> bool:
    try:
        for args in (
            ["init", "-q"],
            ["config", "user.name", "test"],
            ["config", "user.email", "test@example.com"],
            ["config", "commit.gpgsign", "false"],
            ["add", "-A"],
            ["commit", "-q", "-m", "fixture baseline"],
        ):
            r = subprocess.run(["git", "-C", str(vault.root), *args], capture_output=True, text=True)
            if r.returncode != 0:
                return False
        return True
    except (OSError, FileNotFoundError):
        return False
