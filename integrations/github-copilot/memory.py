"""Run the Memory Mesh CLI from any working directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]


def vault_root() -> Path:
    configured = os.environ.get("MEMORY_MESH_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return CODE_ROOT


def main(argv: list[str] | None = None) -> int:
    root = vault_root()
    sys.path.insert(0, str(CODE_ROOT))
    from memory_mesh.cli import main as memory_main

    return memory_main(["--root", str(root), *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
