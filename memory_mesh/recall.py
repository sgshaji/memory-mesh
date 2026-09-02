"""Bounded recall: task → router → 1-2 domain indexes → 3-6 curated links →
stop (P6, session-lifecycle.md budgets). Never "search the vault and hope".

recall-log.tsv is DERIVED telemetry (4 columns, per domain-index.md). Losing
it loses nothing canonical; `served` is reconstructed from episodes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, fsutil, router, tokens
from .config import Vault
from .indexes import LINK_SECTIONS, DomainIndex, load_index
from .notes import load_note, resolve_ref

# Priority of index sections when the note budget forces a cut.
_SECTION_PRIORITY = ("Read first", "Known failures", "Current workarounds", "Active project")
_EXCLUDED_STATUSES = ("stale", "superseded", "rejected", "resolved")


@dataclass
class ServedNote:
    ref: str
    path: Path
    domain: str
    section: str
    tokens: int
    text: str


@dataclass
class RecallResult:
    domains: list[str]
    unclassified: bool
    indexes: list[DomainIndex]
    notes: list[ServedNote] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    token_total: int = 0

    def context_markdown(self) -> str:
        parts = []
        for di in self.indexes:
            parts.append(di.path.read_text(encoding="utf-8"))
        for sn in self.notes:
            parts.append(f"\n<!-- recalled: {sn.ref} ({sn.domain}/{sn.section}) -->\n{sn.text}")
        return "\n\n".join(parts)


def recall(
    vault: Vault,
    task_text: str,
    tool: str = "cli",
    now: datetime | None = None,
    log: bool = True,
    session_id: str | None = None,
) -> RecallResult:
    domains_decl = router.load_domains(vault)
    matched = router.match(task_text, domains_decl, limit=2)
    unclassified = not matched
    if unclassified:
        matched_for_index = ["_general"]
        result_domains = ["unclassified"]
    else:
        matched_for_index = matched
        result_domains = matched

    indexes: list[DomainIndex] = []
    for name in matched_for_index:
        di = load_index(vault, name.lstrip("_")) if not name.startswith("_") else None
        if name == "_general":
            p = vault.path(config.GENERAL_INDEX)
            if p.exists():
                from .indexes import parse_index

                di = parse_index(p, vault)
        if di is not None:
            indexes.append(di)

    result = RecallResult(result_domains, unclassified, indexes)

    # Collect candidate links in section-priority order, round-robin across
    # domains so a two-domain task still respects the single shared budget.
    ordered: list[tuple[str, str, str]] = []  # (domain, section, ref)
    for sec in _SECTION_PRIORITY:
        for di in indexes:
            for entry in di.sections.get(sec, []):
                ordered.append((di.domain, sec, entry.ref))

    seen: set[str] = set()
    for domain, sec, ref in ordered:
        if len(result.notes) >= config.RECALL_MAX_NOTES:
            result.skipped.append(f"{ref} (note budget)")
            continue
        key = ref.split("/")[-1]
        if key in seen:
            continue
        path = resolve_ref(vault, ref)
        if path is None:
            result.skipped.append(f"{ref} (unresolved)")
            continue
        note = load_note(path, vault)
        if note.status in _EXCLUDED_STATUSES:
            result.skipped.append(f"{ref} ({note.status})")
            continue
        text = path.read_text(encoding="utf-8")
        t = tokens.estimate(text)
        if result.token_total + t > config.TOKEN_BUDGET_RECALL:
            result.skipped.append(f"{ref} (token budget)")
            continue
        seen.add(key)
        result.notes.append(ServedNote(ref, path, domain, sec, t, text))
        result.token_total += t

    if log:
        _log_served(vault, tool, result, now)
    if session_id:
        _update_session_state(vault, session_id, result)
    return result


def _log_served(vault: Vault, tool: str, result: RecallResult, now: datetime | None) -> None:
    stamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    log_path = vault.path(config.RECALL_LOG)
    for sn in result.notes:
        fsutil.append_line(log_path, f"{stamp}\t{tool}\t{sn.domain}\t{sn.ref.split('/')[-1]}")


# ---------------------------------------------------------- session state
# Disposable per-session scratch (gitignored) used only to assemble the
# episode stub: what was retrieved, which domains matched. Deleting it costs
# telemetry, never knowledge.


def session_state_path(vault: Vault, session_id: str) -> Path:
    return vault.path(config.SESSION_STATE) / f"{fsutil.safe_slug(session_id, 40)}.json"


def load_session_state(vault: Vault, session_id: str) -> dict:
    p = session_state_path(vault, session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_session_state(vault: Vault, session_id: str, state: dict) -> None:
    fsutil.agent_write(vault, session_state_path(vault, session_id), json.dumps(state, indent=2))


def _update_session_state(vault: Vault, session_id: str, result: RecallResult) -> None:
    state = load_session_state(vault, session_id)
    state.setdefault("retrieved", [])
    for sn in result.notes:
        if sn.ref not in state["retrieved"]:
            state["retrieved"].append(sn.ref)
    state.setdefault("domains", [])
    for d in result.domains:
        if d not in state["domains"]:
            state["domains"].append(d)
    state["recalled"] = True
    save_session_state(vault, session_id, state)
