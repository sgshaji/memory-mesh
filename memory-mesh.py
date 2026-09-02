#!/usr/bin/env python3
"""Launcher so the vault is usable from any directory without installing:

    python "<vault>/memory.py" recall "some task"

Python puts this file's directory on sys.path, so `memory_mesh` imports
cleanly no matter what the working directory is.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory_mesh.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
