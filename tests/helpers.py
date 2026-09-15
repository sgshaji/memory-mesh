"""Test scaffolding: build a hermetic temp vault from tests/fixtures/vault."""

from __future__ import annotations

import shutil
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_mesh.config import Vault  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vault"


def directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        destination = str(link).replace("'", "''")
        source = str(target).replace("'", "''")
        command = f"New-Item -ItemType Junction -Path '{destination}' -Target '{source}' | Out-Null"
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("could not create an isolated junction fixture")
    else:
        link.symlink_to(target, target_is_directory=True)


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
            r = subprocess.run(
                ["git", "-C", str(vault.root), *args],
                capture_output=True, text=True, env=os.environ.copy(),
            )
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip()
                raise RuntimeError(f"Git fixture {args[0]} failed ({r.returncode}): {detail}")
        return True
    except FileNotFoundError:
        return False
