"""Vault location and layout.

The vault is the repository root. Nothing here touches the network.
"""

from __future__ import annotations

import os
from pathlib import Path

# Canonical tiers (P2). Only the curator writes under knowledge/.
INBOX = "00-inbox"
EPISODES = "episodes"
EPISODE_SUMMARIES = "episodes/_summaries"
EPISODE_UNREVIEWED = "episodes/_unreviewed"
KNOWLEDGE = "knowledge"
KNOWLEDGE_FOLDERS = (
    "knowledge/patterns",
    "knowledge/tools",
    "knowledge/workarounds",
    "knowledge/failures",
    "knowledge/references",
    "knowledge/_index",
)
INDEX_DIR = "knowledge/_index"
ROUTER = "knowledge/_index/_domains.md"
GENERAL_INDEX = "knowledge/_index/_general.md"
PROJECTS = "projects"
SKILLS = "skills"
CONTEXT_PACKS = "outputs/context"
META = "_meta"
REDACT_FILE = "_meta/redact.txt"
CURATION_LOG = "_meta/curation-log.md"
GRADUATION_FILE = "_meta/graduation-candidates.md"
RECALL_LOG = "_meta/recall-log.tsv"
REVIEW_DIR = "_meta/review"
REVIEW_ARCHIVE = "_meta/review/archive"
SESSION_STATE = "_meta/session-state"
HOOKS_DIR = "_meta/hooks"
TEMPLATES_DIR = "_meta/templates"

SCAFFOLD_DIRS = (
    INBOX,
    EPISODES,
    EPISODE_SUMMARIES,
    EPISODE_UNREVIEWED,
    *KNOWLEDGE_FOLDERS,
    PROJECTS,
    SKILLS,
    CONTEXT_PACKS,
    META,
    REVIEW_DIR,
    REVIEW_ARCHIVE,
    SESSION_STATE,
    HOOKS_DIR,
    TEMPLATES_DIR,
)

# Directories any agent (or the user) may write into. Everything else is
# curator-only or human-only (P4 / G6).
AGENT_WRITABLE = (INBOX, EPISODES, PROJECTS, SESSION_STATE)

# Directories the curator may write into. It never edits skills/ bodies
# (curator.md §9) and it owns knowledge/, indexes, packs and its own logs.
CURATOR_WRITABLE = (
    KNOWLEDGE,
    EPISODES,  # status flips raw→summarised→mined, redaction, _summaries
    INBOX,  # `processed:` marks and redaction only
    CONTEXT_PACKS,
    "_meta/curation-log.md",
    "_meta/graduation-candidates.md",
    REVIEW_DIR,
)

TOKEN_BUDGET_ROUTER = 300
TOKEN_BUDGET_INDEX = 400
TOKEN_BUDGET_RECALL = 2000
TOKEN_BUDGET_PACK = 2000
RECALL_MAX_NOTES = 6
INDEX_MAX_LINKS = 12
EPISODE_WORD_BUDGET = 400
PACK_VALID_DAYS = 7
INBOX_PRESSURE_COUNT = 30
INBOX_PRESSURE_AGE_DAYS = 60


class VaultError(Exception):
    pass


class Vault:
    """A handle on the vault root; the single way code addresses paths."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def path(self, rel: str) -> Path:
        return self.root / rel

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def scaffold(self) -> list[str]:
        """Create any missing vault directories. Returns what was created."""
        created = []
        for rel in SCAFFOLD_DIRS:
            p = self.path(rel)
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                created.append(rel)
        return created


def find_vault(start: Path | None = None) -> Vault:
    """Resolve the vault root: $MEMORY_MESH_ROOT, else walk up from `start`
    looking for the router or the frozen spec directory."""
    env = os.environ.get("MEMORY_MESH_ROOT")
    if env:
        return Vault(Path(env))
    cur = Path(start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ROUTER).exists() or (candidate / "_meta" / "spec").is_dir():
            return Vault(candidate)
    raise VaultError(
        "not inside a Memory Mesh vault (no knowledge/_index/_domains.md or "
        "_meta/spec found); set MEMORY_MESH_ROOT or run `memory doctor --fix` "
        "from the vault root"
    )
