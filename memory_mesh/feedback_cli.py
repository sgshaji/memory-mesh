"""Small CLI adapters for the common reported-outcome contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Vault, VaultError
from .outcome_types import FAILURE_REASONS, SUBJECT_OUTCOMES, parse_timestamp


def _context(args: argparse.Namespace) -> dict[str, str]:
    return {
        key: getattr(args, key)
        for key in ("tool", "product", "version", "project")
        if getattr(args, key, None)
    }


def _append_session_fact(vault: Vault, session_id: str, fact_id: str, text: str, timestamp: str) -> None:
    from . import recall, redact

    state = recall.load_session_state(vault, session_id)
    checkpoints = state.get("checkpoints", [])
    if not isinstance(checkpoints, list):
        raise VaultError("session checkpoints must be a list")
    if any(isinstance(item, dict) and item.get("fact_id") == fact_id for item in checkpoints):
        return
    clean, _ = redact.redact(text, vault)
    state["checkpoints"] = [
        *checkpoints, {"fact_id": fact_id, "text": clean, "at": timestamp, "source": "observed-record"},
    ]
    recall.save_session_state(vault, session_id, state)


def capture_gap_for_session(
    vault: Vault, need: str, *, domain: str, session_id: str | None = None,
    source_episode: str = "",
) -> Path:
    from .routing_diagnostics import create_gap_candidate

    path = create_gap_candidate(
        vault, need, domain=domain, source_episode=source_episode, session_id=session_id,
    )
    if session_id is not None:
        reference = vault.rel(path).removesuffix(".md")
        _append_session_fact(
            vault, session_id, "gap:" + reference,
            f"Referenced research gap [[{reference}]]; no factual claim was asserted.",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    return path


def cmd_feedback(args: argparse.Namespace) -> int:
    from .cli import _print, _vault
    from .outcomes import record_outcome

    event = record_outcome(
        _vault(args), session_id=args.session, subject_type=args.subject,
        subject_id=args.reference, outcome=args.outcome, reason=args.reason,
        context=_context(args), domain=args.domain or "", source="cli",
        detail=args.detail or "", event_id=args.event_id,
    )
    if args.json:
        _print(json.dumps(event.as_dict(), indent=2))
    else:
        _print(f"outcome stored: {event.event_id} ({event.subject_id}: {event.outcome})")
    return 0


def cmd_recall_quality(args: argparse.Namespace) -> int:
    from .cli import _print, _vault
    from .recall import load_session_state
    from .outcomes import record_outcome
    from .routing_diagnostics import read_attempt, read_attempts

    vault = _vault(args)
    attempt_id = args.attempt or load_session_state(vault, args.session).get("last_recall_attempt")
    if attempt_id:
        attempt = read_attempt(vault, attempt_id)
    else:
        diagnostics: list[str] = []
        attempts = read_attempts(vault, session_id=args.session, diagnostics=diagnostics)
        for message in diagnostics:
            _print(f"warning: {message}")
        if not attempts:
            raise VaultError("no recall attempt for this session; run recall with --session first")
        attempt = max(attempts, key=lambda item: (parse_timestamp(item.timestamp), item.attempt_id))
    if attempt.session_id != args.session:
        raise VaultError("recall attempt does not belong to this session")
    event = record_outcome(
        vault, session_id=args.session, subject_type="recall",
        subject_id=attempt.attempt_id, outcome=args.outcome,
        domain=attempt.domains[0] if attempt.domains else "unclassified",
        context={"route": attempt.route}, detail=args.detail or "",
        source="cli", event_id=args.event_id,
    )
    _print(f"recall quality stored: {event.event_id} ({event.outcome})")
    return 0


def cmd_gap(args: argparse.Namespace) -> int:
    from .cli import _print, _vault

    vault = _vault(args)
    path = capture_gap_for_session(
        vault, args.need, domain=args.domain,
        source_episode=args.episode or "", session_id=args.session,
    )
    _print(f"research gap captured: {vault.rel(path)} (not a factual knowledge claim)")
    return 0


def cmd_curation_recover(args: argparse.Namespace) -> int:
    from .cli import _print, _vault
    from .curator.transaction import (
        acknowledge_curation_conflict, inspect_curation_transactions,
        recover_curation_transactions,
    )

    vault = _vault(args)
    if args.confirm_git_stopped and (args.inspect or args.acknowledge):
        raise VaultError("--confirm-git-stopped applies only when performing recovery")
    if args.acknowledge:
        path = acknowledge_curation_conflict(vault, args.acknowledge)
        _print(f"conflict acknowledged; current files retained: {vault.rel(path)}")
        return 0
    results = (
        inspect_curation_transactions(vault) if args.inspect
        else recover_curation_transactions(vault, confirmed_git_stopped=args.confirm_git_stopped)
    )
    _print(json.dumps([
        {
            "transaction_id": item.transaction_id, "state": item.state,
            "journal": vault.rel(item.journal), "conflicts": list(item.conflicts),
        }
        for item in results
    ], indent=2))
    return 1 if not args.inspect and any(item.state == "conflict" for item in results) else 0


def cmd_explain(args: argparse.Namespace) -> int:
    from .cli import _print, _vault
    from .outcomes import collect_evidence

    vault = _vault(args)
    context = _context(args)
    diagnostics: list[str] = []
    if args.usage and args.subject != "knowledge":
        raise VaultError("--usage applies only to knowledge explanations")
    if args.subject in ("candidate", "routing") and context:
        raise VaultError("context options apply only to knowledge or skill applicability")
    if args.subject == "routing":
        from .router import load_domains, match_evidence

        matches = match_evidence(args.reference, load_domains(vault))
        data = {
            "subject_type": "routing", "selected": [item.domain for item in matches[:2]],
            "fallback": "_general" if not matches else None,
            "matches": [
                {"domain": item.domain, "score": item.score, "terms": list(item.terms)}
                for item in matches
            ],
        }
    elif args.subject == "candidate":
        from .curator.analytics import rank_candidates

        reference = args.reference.strip().removesuffix(".md")
        ranked = rank_candidates(vault)
        matches = [
            (position, item) for position, item in enumerate(ranked, 1)
            if reference == item.ref or ("/" not in reference and reference == item.path.stem)
        ]
        if len(matches) != 1:
            raise VaultError("candidate reference is missing or ambiguous; use its full inbox reference")
        position, candidate = matches[0]
        data = {
            "subject_type": "candidate", "subject_id": candidate.ref,
            "rank": position, "evaluation": candidate.as_dict(),
            "authority": "attention only; not truth or approval",
        }
    elif args.subject == "skill":
        from .skill_health import assess_skill

        health = assess_skill(
            vault, args.reference, context=context or None,
            events=collect_evidence(vault, diagnostics=diagnostics),
        )
        data = {
            "subject_type": "skill", "subject_id": health.reference,
            "evaluation": health.as_dict(), "authority": "read-only health; no skill changes",
        }
    else:
        from .applicability import match_applicability
        from .curator.feedback import assess_knowledge
        from .notes import load_note, resolve_ref
        from .schema import KNOWLEDGE_TYPES

        path = resolve_ref(vault, args.reference)
        if path is None:
            raise VaultError("knowledge reference was not found")
        note = load_note(path, vault)
        if note.type not in KNOWLEDGE_TYPES:
            raise VaultError("knowledge explanation requires a canonical knowledge reference")
        assessment = assess_knowledge(vault, note, events=collect_evidence(vault, diagnostics=diagnostics))
        data = {
            "subject_type": "knowledge", "subject_id": note.ref,
            "canonical_status": note.status,
            "canonical_confidence": note.meta.get("confidence"),
            "evaluation": assessment.as_dict(),
            "current_applicability": match_applicability(note.meta.get("applies_to"), context or None).as_dict(),
            "authority": "reported diagnostics; canonical state remains curator-owned",
        }
        if args.usage:
            from .curator.analytics import recall_usage

            usage = recall_usage(vault)
            recorded = usage.by_ref.get(note.ref)
            data["usage"] = recorded.as_dict() if recorded is not None else None
            diagnostics.extend(usage.warnings)
    data["warnings"] = diagnostics
    _print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def add_parsers(subparsers) -> None:
    explain = subparsers.add_parser("explain", help="explain knowledge, skill, candidate or routing decisions")
    explain.add_argument("reference", help="record reference, or task text for routing")
    explain.add_argument("--subject", choices=("knowledge", "skill", "candidate", "routing"), default="knowledge")
    explain.add_argument("--tool")
    explain.add_argument("--product")
    explain.add_argument("--version")
    explain.add_argument("--project")
    explain.add_argument("--usage", action="store_true", help="include observed 30/90-day recall counts (not confidence evidence)")
    explain.set_defaults(fn=cmd_explain)

    feedback = subparsers.add_parser("feedback", help="record an idempotent knowledge, skill or recall outcome")
    feedback.add_argument("reference", help="knowledge/skill reference, or recall/routing subject ID")
    feedback.add_argument("outcome", help="held/#held, failed/#failed, unclear/#unclear; skill: succeeded/failed/partial")
    feedback.add_argument("--subject", choices=tuple(SUBJECT_OUTCOMES), default="knowledge")
    feedback.add_argument("--session", required=True, help="session identifier (reused for retry deduplication)")
    feedback.add_argument("--event-id", help="stable ID for an independent trial; reuse on retries")
    feedback.add_argument("--reason", choices=FAILURE_REASONS)
    feedback.add_argument("--detail", help="short factual explanation; redacted before capture")
    feedback.add_argument("--domain")
    feedback.add_argument("--tool")
    feedback.add_argument("--product")
    feedback.add_argument("--version")
    feedback.add_argument("--project")
    feedback.add_argument("--json", action="store_true")
    feedback.set_defaults(fn=cmd_feedback)

    quality = subparsers.add_parser("recall-quality", help="rate the most recent recall in a session")
    quality.add_argument("outcome", choices=SUBJECT_OUTCOMES["recall"])
    quality.add_argument("--session", required=True)
    quality.add_argument("--attempt", help="rate this attempt instead of the latest")
    quality.add_argument("--event-id")
    quality.add_argument("--detail")
    quality.set_defaults(fn=cmd_recall_quality)

    gap = subparsers.add_parser("gap", help="capture a research need without asserting a factual claim")
    gap.add_argument("need")
    gap.add_argument("--domain", required=True)
    gap.add_argument("--session")
    gap.add_argument("--episode", help="source episode reference, when known")
    gap.set_defaults(fn=cmd_gap)

    recover = subparsers.add_parser("curation-recover", help="inspect or recover interrupted curation")
    actions = recover.add_mutually_exclusive_group()
    actions.add_argument("--inspect", action="store_true", help="read recovery state without changing anything")
    actions.add_argument("--acknowledge", metavar="TRANSACTION_ID", help="after human review, retain current files and clear this conflict")
    recover.add_argument(
        "--confirm-git-stopped", action="store_true",
        help="operator assertion: all potentially involved native Git processes have stopped",
    )
    recover.set_defaults(fn=cmd_curation_recover)
