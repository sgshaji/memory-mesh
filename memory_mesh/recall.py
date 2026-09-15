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
from typing import Mapping

from . import config, fsutil, redact, router, tokens
from .config import Vault
from .indexes import LINK_SECTIONS, DomainIndex, load_index, render_index
from .notes import NoteReferenceError, load_note, resolve_ref

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
    revision: str | None = None


@dataclass
class RecallResult:
    domains: list[str]
    unclassified: bool
    indexes: list[DomainIndex]
    notes: list[ServedNote] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    missing_indexes: list[str] = field(default_factory=list)  # declared domains without an index file
    token_total: int = 0
    mode: str = "legacy"
    abstention: str | None = None
    brief: str = ""
    reason_counts: dict[str, int] = field(default_factory=dict)
    candidate_count: int = 0
    attempt_id: str | None = None
    task_revision: int | None = None

    def context_markdown(self) -> str:
        if self.mode != "legacy":
            return self.brief
        parts = ["<!-- Read-only recall index view: only links served below are included. Stored indexes are unchanged. -->"]
        served = {(note.domain, note.ref) for note in self.notes}
        for di in self.indexes:
            view = DomainIndex(
                domain=di.domain, path=di.path, meta=dict(di.meta), title=di.title,
                sections={
                    name: [entry for entry in entries if (di.domain, entry.ref) in served]
                    for name, entries in di.sections.items()
                },
            )
            updated = di.meta.get("updated")
            parts.append(render_index(view, updated if isinstance(updated, str) else "unknown"))
        for sn in self.notes:
            parts.append(f"\n<!-- recalled: {sn.ref} ({sn.domain}/{sn.section}) -->\n{sn.text}")
        return "\n\n".join(parts)

    def as_payload(self) -> dict:
        if self.mode == "legacy":
            return {
                "domains": self.domains, "unclassified": self.unclassified,
                "notes": [
                    {"ref": note.ref, "domain": note.domain, "section": note.section, "tokens": note.tokens}
                    for note in self.notes
                ],
                "skipped": self.skipped, "token_total": self.token_total,
            }
        return {
            "mode": self.mode, "domains": self.domains, "unclassified": self.unclassified,
            "notes": [
                {"ref": note.ref, "revision": note.revision, "tokens": note.tokens}
                for note in self.notes
            ],
            "context": self.brief, "context_basis": "caller-declared",
            "abstention": self.abstention, "reason_counts": self.reason_counts,
            "token_total": self.token_total,
        }


def resolve_index_ref(vault: Vault, ref: str) -> Path | None:
    """Resolve curated index links without recursive discovery.

    Legacy bare slugs address direct children of the fixed V1 lookup tiers.
    Nested notes require qualified references. All validation/containment is
    delegated to the common resolver through exact qualified lookups.
    """
    if not isinstance(ref, str):
        raise NoteReferenceError("index reference must be a string")
    ref = ref.strip().replace("\\", "/")
    if "/" in ref:
        return resolve_ref(vault, ref)
    matches: set[Path] = set()
    for folder in (*config.KNOWLEDGE_FOLDERS, config.PROJECTS, config.EPISODES, config.SKILLS):
        path = resolve_ref(vault, f"{folder}/{ref}")
        if path is not None:
            matches.add(path)
    slug = ref[:-3] if ref.lower().endswith(".md") else ref
    skill = resolve_ref(vault, f"{config.SKILLS}/{slug}/SKILL.md")
    if skill is not None:
        matches.add(skill)
    if len(matches) > 1:
        raise NoteReferenceError("ambiguous index reference; use a full vault-relative path")
    return next(iter(matches), None)


def recall(
    vault: Vault,
    task_text: str,
    tool: str = "cli",
    now: datetime | None = None,
    log: bool = True,
    session_id: str | None = None,
    task_id: str | None = None,
    *,
    context: Mapping[str, str] | None = None,
    attempt_id: str | None = None,
) -> RecallResult:
    """Recall bounded context. ``log=False`` suppresses *all* telemetry/state.

    Identical session/task/result retries share an immutable attempt and TSV
    rows. Supply a fresh explicit ``attempt_id`` for an independent trial.
    Strict recall derives applicability context from its task, not overrides.
    """
    from .applicability import match_applicability
    from .experience import get_mode

    mode = get_mode(vault)
    if mode != "legacy":
        from .conditional_recall import recall_for_task

        result = recall_for_task(vault, task_text, task_id, mode=mode, now=now)
        if log:
            _record_recall(vault, task_text, tool, result, now, session_id, task_id, attempt_id)
        return result
    domains_decl = router.load_domains(vault)
    matched = router.match(task_text, domains_decl, limit=2)
    unclassified = not matched
    result_domains = ["unclassified"] if unclassified else matched

    indexes: list[DomainIndex] = []
    missing: list[str] = []
    for name in matched:
        di = load_index(vault, name)
        if di is not None:
            indexes.append(di)
        else:
            missing.append(name)  # declared domain, no index file — a vault defect lint reports
    if not indexes:
        # nothing matched, or every matched domain lacks an index: serve the
        # general fallback so recall never silently returns nothing
        p = vault.path(config.GENERAL_INDEX)
        if p.exists():
            from .indexes import parse_index

            indexes.append(parse_index(p, vault))

    result = RecallResult(result_domains, unclassified, indexes)
    result.missing_indexes = missing

    # Collect candidate links in section-priority order, round-robin across
    # domains so a two-domain task still respects the single shared budget.
    ordered: list[tuple[str, str, str]] = []  # (domain, section, ref)
    for sec in _SECTION_PRIORITY:
        for di in indexes:
            for entry in di.sections.get(sec, []):
                ordered.append((di.domain, sec, entry.ref))

    result.candidate_count = len({ref for _, _, ref in ordered})
    seen: set[str] = set()
    for domain, sec, ref in ordered:
        if len(result.notes) >= config.RECALL_MAX_NOTES:
            result.skipped.append(f"{ref} (note budget)")
            continue
        try:
            path = resolve_index_ref(vault, ref)
        except NoteReferenceError:
            result.skipped.append(f"{ref} (invalid reference)")
            continue
        if path is None:
            result.skipped.append(f"{ref} (unresolved)")
            continue
        key = vault.rel(path)
        if key in seen:
            continue
        note = load_note(path, vault)
        if note.parse_error:
            result.skipped.append(f"{ref} (malformed note)")
            continue
        if note.meta.get("v2_admission"):
            result.skipped.append(f"{ref} (requires task-bound V2 recall)")
            continue
        if note.status in _EXCLUDED_STATUSES:
            result.skipped.append(f"{ref} ({note.status})")
            continue
        applicability = match_applicability(note.meta.get("applies_to"), context=context, now=now)
        if applicability.state == "mismatch":
            result.skipped.append(f"{ref} (inapplicable)")
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
        _record_recall(vault, task_text, tool, result, now, session_id, task_id, attempt_id)
    return result


def _record_recall(
    vault: Vault, task_text: str, tool: str, result: RecallResult, now: datetime | None,
    session_id: str | None, task_id: str | None, attempt_id: str | None,
) -> None:
    from .outcome_types import parse_timestamp
    from .routing_diagnostics import record_attempt

    attempt, created = record_attempt(
        vault, task_text, result, tool=tool, session_id=session_id,
        task_id=task_id, attempt_id=attempt_id, now=now,
    )
    result.attempt_id = attempt.attempt_id
    if created:
        _log_served(vault, attempt.tool, result, parse_timestamp(attempt.timestamp))
    if session_id:
        _update_session_state(vault, session_id, result)


def _log_served(vault: Vault, tool: str, result: RecallResult, now: datetime | None) -> None:
    stamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    log_path = vault.path(config.RECALL_LOG)
    clean_tool = " ".join(redact.redact(tool, vault)[0].split())
    for sn in result.notes:
        fsutil.append_line(log_path, f"{stamp}\t{clean_tool}\t{sn.domain}\t{sn.path.stem}")


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
            state = json.loads(p.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_session_state(vault: Vault, session_id: str, state: dict) -> None:
    fsutil.agent_write(vault, session_state_path(vault, session_id), json.dumps(state, indent=2))


def clear_session_state(vault: Vault, session_id: str) -> None:
    """Session scratch exists only to assemble the episode stub; once that is
    written it must not linger in the vault tree."""
    p = session_state_path(vault, session_id)
    try:
        p.unlink()
    except (OSError, FileNotFoundError):
        pass


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
    if result.attempt_id:
        state.setdefault("recall_attempts", [])
        if result.attempt_id not in state["recall_attempts"]:
            state["recall_attempts"].append(result.attempt_id)
        state["last_recall_attempt"] = result.attempt_id
    save_session_state(vault, session_id, state)
