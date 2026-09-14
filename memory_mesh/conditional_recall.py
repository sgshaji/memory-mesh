"""Permission-first, bounded V2 briefs reconstructed from reviewed records."""

from __future__ import annotations

import json
from datetime import datetime

from . import config, fsutil, router, tokens
from .confidence import decay_due
from .config import Vault, VaultError
from .experience import get_task
from .experience_store import RecordStore
from .experience_types import version_matches
from .indexes import load_index
from .learning_flow import validate_note_binding
from .notes import load_note, resolve_ref
from .recall import RecallResult, ServedNote, _SECTION_PRIORITY

MAX_NOTE_BYTES = 16_384


def _reason(result: RecallResult, reason: str) -> None:
    result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1


def _render(result: RecallResult) -> None:
    if result.abstention:
        result.brief = f"<!-- Memory Mesh: {result.abstention}; no knowledge injected. -->"
    else:
        result.brief = (
            "# Reviewed task context\n\n"
            "Context facts are caller-declared. Verify the listed conditions before applying a lesson.\n\n"
            + "\n\n".join(note.text for note in result.notes)
        )
    if result.reason_counts:
        result.brief += "\n\n<!-- Omitted: " + ", ".join(
            f"{reason}={count}" for reason, count in sorted(result.reason_counts.items())
        ) + " -->"
    # Bound the exact JSON envelope as well as its smaller Markdown projection.
    for _ in range(4):
        estimate = tokens.estimate(json.dumps(result.as_payload(), indent=2) + "\n")
        if estimate == result.token_total:
            break
        result.token_total = estimate


def recall_for_task(
    vault: Vault, query: str, task_id: str | None, *,
    mode: str, now: datetime | None = None,
) -> RecallResult:
    result = RecallResult([], True, [], mode=mode)
    if mode != "strict":
        result.abstention = "memory_disabled" if mode == "off" else "shadow_profile"
        _render(result)
        return result
    if task_id is None:
        result.abstention = "missing_task_context"
        _render(result)
        return result
    with RecordStore(vault).transaction():
        task = get_task(vault, task_id)
        result.domains = router.match(query or task.goal, router.load_domains(vault), limit=2)
        result.unclassified = not result.domains
        if not result.domains:
            result.abstention = "no_matching_domain"
            _render(result)
            return result
        for domain in result.domains:
            index = load_index(vault, domain)
            if index is not None:
                result.indexes.append(index)
            else:
                _reason(result, "missing_domain_index")
        seen = set()
        today = (now or datetime.now().astimezone()).date()
        for section in _SECTION_PRIORITY:
            for index in result.indexes:
                for entry in index.sections.get(section, []):
                    if len(result.notes) >= config.RECALL_MAX_NOTES:
                        break
                    path = resolve_ref(vault, entry.ref)
                    if path is None:
                        _reason(result, "missing_note")
                        continue
                    try:
                        resolved = fsutil.ensure_within(vault, path)
                        resolved.relative_to(vault.root / config.KNOWLEDGE)
                        if resolved.is_symlink() or resolved.stat().st_size > MAX_NOTE_BYTES:
                            _reason(result, "note_size_or_path")
                            continue
                        note = load_note(resolved, vault)
                        if not note.meta.get("v2_admission"):
                            _reason(result, "legacy_note")
                            continue
                        if note.status != "validated":
                            _reason(result, "inactive_note")
                            continue
                        lesson = validate_note_binding(vault, note)
                    except (VaultError, OSError, ValueError, fsutil.PathTraversalError):
                        _reason(result, "invalid_or_held_admission")
                        continue
                    key = (lesson.binding["task_id"], lesson.binding["proposal_id"])
                    if key in seen:
                        continue
                    proposal = lesson.proposal
                    if task.project not in proposal.projects:
                        _reason(result, "project_scope")
                        continue
                    if task.tool != lesson.source["tool"] or not version_matches(lesson.runtime_version, task.version):
                        _reason(result, "runtime_scope")
                        continue
                    if not set(proposal.conditions).issubset(task.facts):
                        _reason(result, "unknown_conditions")
                        continue
                    observed = lesson.receipt["observed_at"][:10]
                    if decay_due(note.type or "", "validated", observed, observed, today):
                        _reason(result, "stale_evidence")
                        continue
                    text = (
                        f"## {proposal.title}\n"
                        f"Source: [[{note.ref}]]; revision {lesson.binding['proposal_hash']}.\n"
                        f"Runtime: {lesson.source['tool']} {lesson.runtime_version}.\n"
                        f"Conditions: {', '.join(proposal.conditions)}.\n"
                        f"Action: {proposal.action}\n"
                        f"Limitations: {'; '.join(proposal.limitations) or 'No broader behavior established.'}\n"
                        f"Evidence: [[{lesson.receipt['episode_ref']}]]."
                    )
                    served = ServedNote(
                        note.ref, resolved, index.domain, section, tokens.estimate(text),
                        text, lesson.binding["proposal_hash"],
                    )
                    result.notes.append(served)
                    _render(result)
                    if result.token_total > config.TOKEN_BUDGET_RECALL:
                        result.notes.pop()
                        _reason(result, "whole_brief_budget")
                    else:
                        seen.add(key)
        if not result.notes:
            result.abstention = "no_applicable_knowledge"
        _render(result)
        while result.token_total > config.TOKEN_BUDGET_RECALL and result.notes:
            result.notes.pop()
            _reason(result, "whole_brief_budget")
            if not result.notes:
                result.abstention = "no_applicable_knowledge"
            _render(result)
        return result
