"""Curator-only admission and publication for the experimental strict profile."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import capture, episodes, frontmatter, fsutil
from ..attestations import read_attestation, write_attestation
from ..config import Vault, VaultError
from ..experience import context_digest, execution_proof, get_mode, load_task_record, snapshot
from ..experience_store import RecordStore, exclusive_lock
from ..experience_types import digest, require_id, require_revision
from ..learning_admission import assess, parse_proposal
from ..learning_flow import (
    POLICY_VERSION, admission_key, approved_lesson, claim_text, load_proposal,
    review_decisions, source_snapshot, validate_note_binding,
)
from ..notes import iter_notes, load_note
from .review import archive_review_file, is_fully_decided, parse_review_file, pending_review_files
from .transaction import curation_transaction


def _timestamp(value: object) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError
        return stamp
    except ValueError as exc:
        raise VaultError("invalid evidence timestamp") from exc


def _evidence_episode(vault: Vault, record, proposal, key: str) -> tuple[str, str, str]:
    proofs = [execution_proof(vault, record, event_id) for event_id in proposal.evidence_ids]
    if any(proof is None for proof in proofs):
        raise VaultError("execution evidence disappeared before admission")
    observed = min(_timestamp(proof["completed_at"]) for proof in proofs if proof is not None)
    ref = f"episodes/{observed.date().isoformat()}-memory-mesh-v2-{key[:32]}"
    lines = [
        "# Session: scoped validation evidence", "",
        "## Goal", f"Record the observed checks supporting: {proposal.title}", "",
        "## What happened",
    ]
    for proof in proofs:
        assert proof is not None
        result = proof["result"]
        lines.append(
            f"- Check `{proof['check_id']}`: {result['outcome']}; "
            f"{result['tests_run']} tests, {result['tests_skipped']} skipped, "
            f"{result['expected_failures']} expected failures."
        )
    lines.extend([
        "", "## Decisions", "A separate human admission review governs the scoped lesson.",
        "", "## Problems", "These observations do not establish general correctness or cost savings.",
        "", "## Knowledge retrieved", "", "## Knowledge used", "",
        "## Candidate learnings", "",
    ])
    body = "\n".join(lines)
    if len(body.split()) > 400:
        raise VaultError("validation evidence exceeds the episode budget")
    metadata = {
        "type": "episode", "tool": "memory-mesh", "domains": [proposal.domain],
        "captured": observed.isoformat(timespec="seconds"), "trust": "first-party",
        "sensitivity": "checked", "status": "raw", "session_ref": record["task_id"],
        "v2_evidence": key,
    }
    desired = frontmatter.compose(metadata, body)
    expected_body = frontmatter.parse(desired)[1]
    path = vault.path(ref + ".md")
    if path.exists():
        existing = load_note(path, vault)
        if existing.body != expected_body or existing.meta.get("v2_evidence") != key:
            raise VaultError("validation episode identity has conflicting content")
    else:
        fsutil.agent_write(vault, path, desired)
    if load_note(path, vault).status == "raw":
        episodes.finish(vault, path)
    episode = load_note(path, vault)
    if episode.status not in ("summarised", "mined"):
        raise VaultError("validation episode is not finalized")
    return ref, digest(episode.body), observed.isoformat(timespec="seconds")


def _candidate(vault: Vault, proposal, binding, approved_at: str) -> Path:
    key = admission_key(binding["task_id"], binding["proposal_id"])
    path = vault.path(f"00-inbox/v2-{key}.md")
    claim = claim_text(proposal)
    metadata = {
        "type": "candidate", "title": proposal.title,
        "source": f"curator-reviewed V2 admission {key}", "captured": approved_at,
        "domains": [proposal.domain], "trust": "first-party", "sensitivity": "checked",
        "content_hash": capture._content_hash(claim), "v2_admission": binding,
    }
    text = frontmatter.compose(metadata, f"## Observations\n- [procedure] {claim}\n")
    if path.exists():
        existing = load_note(path, vault)
        if (
            existing.body != frontmatter.parse(text)[1]
            or any(existing.meta.get(field) != value for field, value in metadata.items())
            or set(existing.meta) - {*metadata, "processed"}
        ):
            raise VaultError("reviewed candidate identity has conflicting content")
        return path
    return fsutil.agent_write(vault, path, text)


def _apply_admission(vault: Vault, payload: object, now: datetime) -> list[Path]:
    if not isinstance(payload, dict) or set(payload) != {"task_id", "proposal_id", "revision", "proposal_hash"}:
        raise VaultError("invalid admission review payload")
    task_id = require_id(payload["task_id"], "task_id")
    proposal_id = require_id(payload["proposal_id"], "proposal_id")
    require_revision(payload["revision"])
    store = RecordStore(vault)
    with store.transaction():
        if get_mode(vault) != "strict":
            raise VaultError("admission requires the strict profile")
        record = load_task_record(store, task_id)
        entry = load_proposal(record, proposal_id)
        proposal = parse_proposal(entry["proposal"])
        assert proposal is not None
        binding = {
            "task_id": task_id, "proposal_id": proposal_id,
            "proposal_hash": entry["proposal_hash"],
        }
        if payload["proposal_hash"] != entry["proposal_hash"]:
            raise VaultError("review no longer matches the proposal")
        if entry["state"] == "approved":
            lesson = approved_lesson(vault, binding)
            return [_candidate(vault, proposal, binding, lesson.receipt["approved_at"])]
        if entry["state"] != "pending" or payload["revision"] != record["revision"]:
            raise VaultError("reviewed task revision is no longer current")
        if entry["source"] != source_snapshot(record):
            raise VaultError("reviewed task context has changed")
        decision = assess(snapshot(vault, record), proposal, semantic_approved=True)
        if decision.outcome != "admit":
            raise VaultError("admission evidence no longer qualifies: " + ", ".join(decision.reasons))
        key = admission_key(task_id, proposal_id)
        ref, body_hash, observed_at = _evidence_episode(vault, record, proposal, key)
        previous = read_attestation(vault, "admission", key)
        approved_at = previous["approved_at"] if previous is not None else now.isoformat(timespec="seconds")
        receipt_path = write_attestation(vault, "admission", key, {
            "policy_version": POLICY_VERSION, **binding,
            "source_hash": digest(entry["source"]), "claim_hash": digest(claim_text(proposal)),
            "episode_ref": ref, "episode_body_hash": body_hash,
            "observed_at": observed_at, "approved_at": approved_at,
        })
        candidate = _candidate(vault, proposal, binding, approved_at)
        entry["state"] = "approved"
        entry["admission_key"] = key
        entry["candidate_ref"] = vault.rel(candidate)[:-3]
        task_path = store.save("tasks", task_id, record)
        return [receipt_path, candidate, task_path, vault.path(ref + ".md")]


def _hold(vault: Vault, payload: object) -> Path:
    if not isinstance(payload, dict):
        raise VaultError("invalid admission hold payload")
    store = RecordStore(vault)
    with store.transaction():
        record = load_task_record(store, require_id(payload.get("task_id"), "task_id"))
        entry = load_proposal(record, require_id(payload.get("proposal_id"), "proposal_id"))
        if payload.get("proposal_hash") != entry["proposal_hash"]:
            raise VaultError("hold no longer matches the proposal")
        entry["state"] = "held"
        return store.save("tasks", record["task_id"], record)


def _publish(vault: Vault, note, report, today) -> None:
    from . import engine

    store = RecordStore(vault)
    with store.transaction():
        if get_mode(vault) != "strict":
            raise VaultError("strict publication is disabled")
        lesson = validate_note_binding(vault, note)
        proposal = lesson.proposal
        key = admission_key(lesson.binding["task_id"], lesson.binding["proposal_id"])
        kind = "failure" if proposal.expected_outcome == "failed" else "pattern"
        folder = "failures" if kind == "failure" else "patterns"
        path = vault.path(f"knowledge/{folder}/v2-{key}.md")
        if path.exists():
            existing = load_note(path, vault)
            validate_note_binding(vault, existing)
            if existing.status != "validated":
                raise VaultError("existing V2 lesson is inactive; it cannot be silently republished")
        else:
            observed = _timestamp(lesson.receipt["observed_at"]).date().isoformat()
            metadata = {
                "type": kind, "title": proposal.title, "domains": [proposal.domain],
                "status": "validated", "trust": "first-party", "confidence": "low",
                "applies_to": {"tools": [lesson.source["tool"]], "from": lesson.runtime_version},
                "first_observed": observed, "last_verified": observed,
                "feedback": {"served": 0, "held": 0, "failed": 0, "unclear": 0},
                "evidence": [lesson.receipt["episode_ref"]], "superseded_by": None,
                "source": f"reviewed-v2: {key}", "content_hash": engine._hash_text(claim_text(proposal)),
                "v2_admission": lesson.binding,
            }
            fsutil.curator_write(vault, path, frontmatter.compose(
                metadata,
                f"## Observations\n- [behaviour] {claim_text(proposal)}\n\n"
                f"## Relations\n- derived_from [[{lesson.receipt['episode_ref']}]]\n",
            ))
            report.touched.add(vault.rel(path))
            report.log("CREATE", vault.rel(path), "reviewed V2 lesson; confidence not inferred from speed")
        engine._index_add_note(vault, load_note(path, vault), report, today, task_bound=True)
        metadata = dict(note.meta)
        metadata["processed"] = report.run_id
        fsutil.curator_write(vault, note.path, frontmatter.compose(metadata, note.body))
        report.touched.add(note.rel)


def run_compile(vault: Vault, now: datetime | None = None):
    from . import engine

    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    today = stamp.date()
    with exclusive_lock(vault, "curator"), curation_transaction(vault, existing_lock=True):
        if get_mode(vault) != "strict":
            raise VaultError("profile changed while waiting for strict curation; retry with the current profile")
        report = engine.RunReport(engine._run_id(stamp))
        for path in pending_review_files(vault):
            items = parse_review_file(path)
            retain = False
            for item in items:
                if item.error:
                    retain = True
                    report.warnings.append(f"review action is invalid: {item.error}")
                    continue
                if item.kind != "ADMIT":
                    if item.kind in ("MERGE", "SUPERSEDE", "REJECT"):
                        retain = True
                    continue
                try:
                    if item.approved:
                        touched = _apply_admission(vault, item.payload, stamp)
                        report.touched.update(vault.rel(item) for item in touched)
                        report.log("ADMIT", item.header, "human review applied")
                    elif item.choice:
                        held = _hold(vault, item.payload)
                        report.touched.add(vault.rel(held))
                        report.log("HOLD", item.header, "human review retained the proposal")
                except VaultError as exc:
                    retain = True
                    report.warnings.append(f"V2 review deferred: {exc}")
            if not retain and is_fully_decided(items):
                archived = archive_review_file(vault, path)
                report.touched.update((vault.rel(path), vault.rel(archived)))
        report.decisions.extend(review_decisions(vault))
        legacy_held = 0
        for note in iter_notes(vault, "00-inbox"):
            if "processed" in note.meta:
                continue
            if not note.meta.get("v2_admission"):
                legacy_held += 1
                continue
            try:
                _publish(vault, note, report, today)
            except VaultError as exc:
                report.warnings.append(f"V2 candidate held: {exc}")
        if legacy_held:
            report.warnings.append(f"{legacy_held} legacy inbox item(s) held outside strict admission")
        engine._finalise_run(vault, report, today, f"V2 curator compile {report.run_id}")
        return report
