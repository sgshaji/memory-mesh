"""Curator engine: compile (records → candidates → decisions) and lint
(keeping the canon honest). Deterministic layer 1; an optional adapter adds
judgement but is never required (mandate §J, curator.md).

Safety posture (§9 / mandate §M): every inbox/episode body is untrusted DATA.
Instruction-like sentences are logged and ignored. Redaction runs before
anything is read for meaning. No network. All canonical writes go through
`fsutil.curator_write` (boundary-enforced, atomic) and land in one Git commit
per run with author `curator`.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .. import config, frontmatter, fsutil, gitutil, packs, redact
from ..config import Vault, VaultError
from ..episodes import mark_mined, parse_episode
from ..indexes import (
    DomainIndex,
    eligible_for_section,
    index_path,
    list_domain_indexes,
    load_index,
    write_index_if_changed,
)
from ..notes import Note, iter_notes, knowledge_notes, load_note, resolve_ref, section
from ..router import load_domains, match as router_match
from . import analytics, feedback
from .adapter import NullAdapter, ReasoningAdapter
from .decisions import Decision
from .neighbours import find_neighbours, jaccard, keywords
from .review import (
    ReviewItem,
    SUPPRESSIONS,
    archive_review_file,
    is_fully_decided,
    load_suppressions,
    parse_review_file,
    pending_review_files,
    record_suppression,
    review_path,
    review_input_paths,
    retire_review_items,
    suppression_key,
    write_review_file,
)
from .transaction import CurationConflict, curation_transaction, current_transaction

_TYPE_DIR = {
    "pattern": "knowledge/patterns",
    "tool-behaviour": "knowledge/tools",
    "workaround": "knowledge/workarounds",
    "failure": "knowledge/failures",
    "reference": "knowledge/references",
}
_INDEX_SECTION_FOR_TYPE = {
    "failure": "Known failures",
    "workaround": "Current workarounds",
}
_VERSION_RE = re.compile(r"\b(\d{4}-\d{2}(?:-\d{2})?|v\d+(?:\.\d+)+[\w.-]*)\b")
_NEGATION_RE = re.compile(r"\b(no longer|not|never|stopped|broken|fails?|failed|doesn't|does not|isn't|is not)\b", re.I)


@dataclass
class Claim:
    text: str
    source: Note  # inbox item or episode
    source_kind: str  # "inbox" | "episode"
    domains: list[str] = field(default_factory=list)
    trust: str = "unknown"
    tools: list[str] = field(default_factory=list)
    version: str | None = None
    note_type: str = "pattern"
    hash: str = ""


@dataclass
class RunReport:
    run_id: str
    decisions: list[Decision] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    touched: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    commit: gitutil.CommitResult | None = None
    candidate_priorities: list[analytics.CandidatePriority] = field(default_factory=list)

    def log(self, kind: str, target: str, detail: str = "") -> None:
        self.log_lines.append(f"{kind}  {target}" + (f"  {detail}" if detail else ""))


def _hash_text(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text.strip().lower()).encode("utf-8")).hexdigest()[:16]


def _today(now: datetime | None) -> date:
    return (now or datetime.now().astimezone()).date()


def _run_id(now: datetime | None) -> str:
    return "run-" + (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")


# =============================================================== compile


def run_compile(vault: Vault, adapter: ReasoningAdapter | None = None, now: datetime | None = None) -> RunReport:
    """Compile legacy inputs in one recoverable transaction.

    An active transaction is reused; strict V2 retains its own lock/boundary.
    Git failures abort that boundary. No Git remains local-only and is reported
    through CommitResult.manual_commit_required, never as publication success.
    """
    from ..experience import get_mode

    mode = get_mode(vault)
    if mode == "strict":
        from .v2 import run_compile as run_v2_compile

        return run_v2_compile(vault, now)
    if mode in ("shadow", "off"):
        report = RunReport(_run_id(now))
        report.warnings.append(f"curator publication is disabled in {mode} mode")
        return report
    adapter = adapter or NullAdapter()
    report = RunReport(_run_id(now))
    active = current_transaction(vault)
    boundary = nullcontext(active) if active is not None else curation_transaction(vault, run_id=report.run_id)
    with boundary:
        if get_mode(vault) != "legacy":
            raise VaultError("profile changed while waiting for curation; retry with the current profile")
        return _run_legacy_compile(vault, adapter, report, _today(now), now=now)


def _run_legacy_compile(
    vault: Vault, adapter: ReasoningAdapter, report: RunReport, today: date,
    *, now: datetime | None = None,
) -> RunReport:
    _apply_approved_reviews(vault, report, today)

    inbox_items = []
    held_items = []
    all_inbox = list(iter_notes(vault, config.INBOX))
    for n in all_inbox:
        if n.type not in ("candidate", "gap", None) or "processed" in n.meta:
            continue
        if n.meta.get("v2_admission"):
            report.warnings.append("V2 candidate requires the strict profile; left unchanged")
            continue
        if "hold_hash" in n.meta:
            if _hold_hash(n) == n.meta.get("hold_hash"):
                held_items.append(n)  # unchanged since the HOLD — still waiting
                continue
            # §4 HOLD: "re-evaluated on the next evidence" — the item changed,
            # so it re-enters the pipeline with its hold marks cleared
            n = _release_hold(vault, n, report)
        inbox_items.append(n)
    episodes_ready = [
        n for n in iter_notes(vault, config.EPISODES)
        if n.type == "episode" and n.status == "summarised" and not n.meta.get("v2_evidence")
    ]

    # §2.1 redaction BEFORE anything is read for meaning
    inbox_items = [_redaction_pass(vault, n, report) for n in inbox_items]
    episodes_ready = [_redaction_pass(vault, n, report) for n in episodes_ready]
    report.candidate_priorities = analytics.rank_candidates(vault, now=now, diagnostics=report.warnings)
    priorities = {item.ref: item for item in report.candidate_priorities}
    positions = {item.ref: position for position, item in enumerate(report.candidate_priorities)}
    inbox_items.sort(key=lambda note: (positions.get(note.ref, len(positions)), note.ref))
    ignore_learning = feedback.inbox_reference_filter(all_inbox)

    known_hashes = _existing_hashes(vault)
    declared_domains = [d.name for d in load_domains(vault)]

    for item in inbox_items:
        if item.parse_error:
            # malformed frontmatter is reportable, never fatal: the item was
            # still redacted in place above, it just cannot be read for meaning
            report.warnings.append(f"{item.rel}: unreadable frontmatter ({item.parse_error}); skipped, fix and re-run")
            continue
        _scan_injection(item, report)
        if item.type == "gap":
            feedback.queue_gap(report, item, priorities.get(item.ref))
            continue
        if item.type not in ("candidate", None):
            report.warnings.append(f"{item.rel}: redacted item has an invalid candidate type; left for review")
            continue
        if _reference_fallback(vault, item, report, today):
            continue  # §2.1: content that cannot be redacted meaningfully
        claims = _claims_from_inbox(vault, item, declared_domains)
        produced = _decide_claims(vault, claims, known_hashes, adapter, report, today)
        _mark_inbox_processed(vault, item, report, produced)

    for ep in episodes_ready:
        if ep.parse_error:
            report.warnings.append(f"{ep.rel}: unreadable frontmatter ({ep.parse_error}); skipped, fix and re-run")
            continue
        _scan_injection(ep, report)
        claims = _claims_from_episode(vault, ep, declared_domains, adapter, ignore_learning=ignore_learning)
        produced = _decide_claims(vault, claims, known_hashes, adapter, report, today)
        mark_mined(vault, ep.path, produced)
        report.touched.add(ep.rel)
        report.log("MINED", ep.ref, f"claims {len(claims)}")

    if held_items:
        report.warnings.append(f"{len(held_items)} inbox item(s) on hold await new evidence or review")

    _promotion_pass(vault, report, today)
    snapshot = feedback.apply_knowledge_feedback(vault, report, now=now)
    _graduation_pass(vault, snapshot.assessments, report)
    feedback.complete_attention(vault, report, snapshot)
    _finalise_run(vault, report, today, f"curator compile {report.run_id}")
    return report


def _hold_hash(note: Note) -> str:
    """Hash covering frontmatter and body, minus the hold marks themselves —
    a domain fix lives in the frontmatter, so a body-only hash would miss the
    very edit the HOLD asked for."""
    meta = {k: v for k, v in note.meta.items() if k not in ("hold_hash", "hold_reason")}
    return _hash_text(frontmatter.compose(meta, note.body))


def _release_hold(vault: Vault, note: Note, report: RunReport) -> Note:
    meta = {k: v for k, v in note.meta.items() if k not in ("hold_hash", "hold_reason")}
    fsutil.curator_write(vault, note.path, frontmatter.compose(meta, note.body))
    report.touched.add(note.rel)
    report.log("UNHOLD", note.ref, "item changed since the hold — re-evaluating")
    return load_note(note.path, vault)


def _redaction_pass(vault: Vault, note: Note, report: RunReport) -> Note:
    """Redact in place before anything is read for meaning (§2.1).

    Redaction must survive malformed input: an item whose frontmatter will not
    parse is still written back redacted, then reported — never allowed to
    abort the run and leave the secret on disk.
    """
    text = note.path.read_text(encoding="utf-8")
    clean, findings = redact.redact(text, vault)
    if not findings:
        return note
    try:
        meta, body = frontmatter.parse(clean)
        meta["sensitivity"] = "redacted"
        out = frontmatter.compose(meta, body)
    except frontmatter.FrontmatterError as e:
        out = clean  # unparseable: preserve the file verbatim, minus the secrets
        report.warnings.append(f"{note.rel}: redacted in place but frontmatter is malformed ({e})")
    fsutil.curator_write(vault, note.path, out)
    report.touched.add(note.rel)
    report.log("REDACT", note.ref, ", ".join(f.rule for f in findings))
    return load_note(note.path, vault)


_REDACTION_TOKEN_RE = re.compile(r"\[(?:redacted[a-z-]*|customer|tenant|internal-url|email)\]")


def _reference_fallback(vault: Vault, item: Note, report: RunReport, today: date) -> bool:
    """§2.1: content that cannot be redacted meaningfully becomes a Reference
    note pointing at the original location, instead of a claim built out of
    redaction tokens. Returns True when the item was handled this way."""
    text = " ".join(fact for _, fact in item.observations()) or item.title
    tokens_found = _REDACTION_TOKEN_RE.findall(text)
    words = max(len(text.split()), 1)
    if len(tokens_found) < 3 or len(tokens_found) / words <= 0.2:
        return False
    title = str(item.meta.get("title") or item.path.stem)
    title = _REDACTION_TOKEN_RE.sub("", title).strip() or item.path.stem
    meta = {
        "type": "reference",
        "title": f"Source: {title}"[:120],
        "domains": [d for d in (item.meta.get("domains") or []) if d][:3] or ["unclassified"],
        "status": "candidate",
        "trust": str(item.meta.get("trust") or "unknown"),
        "confidence": "low",
        "first_observed": str(item.meta.get("captured", today.isoformat()))[:10],
        "evidence": [],
        "superseded_by": None,
        "source": str(item.meta.get("source") or item.ref),
    }
    body = (
        "## Observations\n"
        f"- [pointer] the substance stayed at its original location; see `{item.meta.get('source') or item.ref}`\n"
        "- [reason] too much of this item was customer, tenant or credential material to admit as a claim\n"
    )
    path = fsutil.unique_path(vault.path("knowledge/references") / f"{fsutil.safe_slug(title, 48)}.md")
    fsutil.curator_write(vault, path, frontmatter.compose(meta, body))
    report.touched.add(vault.rel(path))
    report.log("REFERENCE", vault.rel(path)[:-3], f"from {item.ref} (too sensitive to admit as a claim)")
    meta_item = dict(item.meta)
    meta_item["processed"] = report.run_id
    fsutil.curator_write(vault, item.path, frontmatter.compose(meta_item, item.body))
    report.touched.add(item.rel)
    return True


def _scan_injection(note: Note, report: RunReport) -> None:
    markers = redact.injection_markers(note.body + " " + str(note.meta.get("title", "")))
    for m in markers:
        report.log("IGNORED-INSTRUCTION", note.ref, f'"{m}" treated as data')


def _existing_hashes(vault: Vault) -> dict[str, str]:
    """content hash → note ref, for idempotence and evidence routing."""
    hashes: dict[str, str] = {}
    for n in knowledge_notes(vault):
        if "v2_admission" in n.meta:
            continue
        h = n.meta.get("content_hash")
        if isinstance(h, str):
            hashes[h] = n.ref
    return hashes


def _claims_from_inbox(vault: Vault, item: Note, declared: list[str]) -> list[Claim]:
    text = " ".join(fact for _, fact in item.observations()) or item.title
    return [_build_claim(text, item, "inbox", declared)]


def _claims_from_episode(
    vault: Vault, ep: Note, declared: list[str], adapter: ReasoningAdapter,
    *, ignore_learning: Callable[[str], bool] | None = None,
) -> list[Claim]:
    parsed = parse_episode(ep)
    texts = list(parsed.candidate_learnings)
    tool = str(ep.meta.get("tool", "")).lower()
    for bullet in parsed.decisions + parsed.problems:
        if tool and tool in bullet.lower() and bullet not in texts:
            texts.append(bullet)
    extra = adapter.extract_claims(ep.body)
    for t in extra or []:
        if t not in texts:
            texts.append(t)
    return [
        _build_claim(text, ep, "episode", declared) for text in texts
        if ignore_learning is None or not ignore_learning(text)
    ]


def _build_claim(text: str, source: Note, kind: str, declared: list[str]) -> Claim:
    c = Claim(text=text.strip(), source=source, source_kind=kind)
    c.hash = _hash_text(c.text)
    c.trust = str(source.meta.get("trust") or "unknown")

    # trailing "(tool, version)" per episode.md's candidate-learning convention
    m = re.search(r"\(([a-z0-9 ._-]+),\s*([^)]+)\)\s*$", c.text, re.I)
    tool_hint = None
    if m:
        tool_hint = m.group(1).strip().lower()
        vm = _VERSION_RE.search(m.group(2))
        if vm:
            c.version = vm.group(1)
    if c.version is None:
        vm = _VERSION_RE.search(c.text)
        c.version = vm.group(1) if vm else None

    src_tool = str(source.meta.get("tool") or "").lower()
    c.tools = [t for t in dict.fromkeys([tool_hint, src_tool]) if t]

    low = c.text.lower()
    fix_words = re.search(r"\b(workaround|fix|fixes|instead|fallback|mitigate|removes|prevents|avoids|resolves|declare|until)\b", low)
    fail_words = re.search(r"\b(fail|fails|failed|failure|broken|does not work|doesn't work|error)\b", low)
    if fix_words:
        c.note_type = "workaround"
    elif fail_words:
        c.note_type = "failure"
    elif c.tools and c.version:
        c.note_type = "tool-behaviour"
    else:
        c.note_type = "pattern"

    src_domains = [d for d in (source.meta.get("domains") or []) if d in declared]
    c.domains = src_domains[:3]
    return c


def _route_claim_domains(vault: Vault, c: Claim) -> None:
    matched = router_match(c.text, load_domains(vault), limit=3)
    for d in matched:
        if d not in c.domains:
            c.domains.append(d)
    c.domains = c.domains[:3]


def _decide_claims(
    vault: Vault,
    claims: list[Claim],
    known_hashes: dict[str, str],
    adapter: ReasoningAdapter,
    report: RunReport,
    today: date,
) -> list[str]:
    produced: list[str] = []
    for c in claims:
        _route_claim_domains(vault, c)
        if c.hash in known_hashes:
            # Same claim, different episode = new supporting evidence
            # (promotion needs two independent episodes). Same claim from a
            # non-episode source is a true duplicate.
            target = known_hashes[c.hash]
            if c.source_kind == "episode" and resolve_ref(vault, target) is not None:
                d = Decision("UPDATE", "identical claim from a new episode — supporting evidence", claim=c.text, source_ref=c.source.ref, target_ref=target)
                report.decisions.append(d)
                _apply_update(vault, c, target, report, today)
                produced.append(target)
            else:
                report.log("SKIP", c.source.ref, f"duplicate content hash {c.hash}")
            continue
        if not c.domains:
            d = Decision("HOLD", "no declared domain matches — add a domain or classify manually", claim=c.text, source_ref=c.source.ref)
            report.decisions.append(d)
            report.log("HOLD", c.source.ref, "unclassified domain")
            continue
        decision = _decide_one(vault, c, adapter, report, today)
        report.decisions.append(decision)
        if decision.kind == "CREATE":
            ref = _apply_create(vault, c, report, today)
            produced.append(ref)
            known_hashes[c.hash] = ref
        elif decision.kind == "UPDATE":
            _apply_update(vault, c, decision.target_ref, report, today)
            produced.append(decision.target_ref)
            known_hashes[c.hash] = decision.target_ref
        else:
            report.log(decision.kind, decision.target_ref or c.source.ref, decision.rationale)
    return produced


def _decide_one(vault: Vault, c: Claim, adapter: ReasoningAdapter, report: RunReport, today: date) -> Decision:
    neigh = [
        item for item in find_neighbours(vault, c.text, c.domains, c.tools, c.note_type)
        if "v2_admission" not in item.note.meta
    ]
    best = neigh[0] if neigh else None
    if best is None or best.similarity < 0.25:
        return Decision("CREATE", "no neighbour covers the claim", claim=c.text, source_ref=c.source.ref)

    contradicts = _contradicts(c.text, best.note)
    if contradicts and best.similarity >= 0.3:
        note_from = (best.note.meta.get("applies_to") or {}).get("from")
        if c.version and note_from and str(c.version) != str(note_from):
            return _supersede_proposal(vault, c, best.note, today)
        return Decision(
            "HOLD",
            f"single contradicting observation against [[{best.note.ref}]] at the same version — validation queue",
            claim=c.text,
            source_ref=c.source.ref,
            target_ref=best.note.ref,
        )

    if best.similarity >= 0.6:
        return Decision(
            "UPDATE",
            f"neighbour [[{best.note.ref}]] covers the claim; adding evidence",
            claim=c.text,
            source_ref=c.source.ref,
            target_ref=best.note.ref,
        )

    verdict = adapter.same_claim(c.text, best.note.title + "\n" + best.note.body)
    if verdict is True:
        return Decision("UPDATE", f"adapter judged same claim as [[{best.note.ref}]]", claim=c.text, source_ref=c.source.ref, target_ref=best.note.ref)
    if verdict is False:
        return Decision("CREATE", "adapter judged distinct claim", claim=c.text, source_ref=c.source.ref)
    return Decision(
        "HOLD",
        f"possibly the same claim as [[{best.note.ref}]] (similarity {best.similarity:.2f}); no model to judge — review needed",
        claim=c.text,
        source_ref=c.source.ref,
        target_ref=best.note.ref,
    )


def _contradicts(claim_text: str, note: Note) -> bool:
    claim_neg = bool(_NEGATION_RE.search(claim_text))
    note_text = " ".join(f for _, f in note.observations())
    note_neg = bool(_NEGATION_RE.search(note_text))
    return claim_neg != note_neg


def _supersede_proposal(vault: Vault, c: Claim, old: Note, today: date) -> Decision:
    new_ref = f"{_TYPE_DIR[c.note_type]}/{fsutil.safe_slug(c.text, 48)}-{(c.version or today.isoformat())[:7]}"
    new_content = _render_new_note(c, today, extra_relations=[("supersedes", old.ref)])
    return Decision(
        "SUPERSEDE",
        f"claim holds for {c.version or 'a newer version'}; [[{old.ref}]] documents {(old.meta.get('applies_to') or {}).get('from') or 'an earlier version'}",
        claim=c.text,
        source_ref=c.source.ref,
        target_ref=old.ref,
        payload={
            "target": old.rel,
            "new_ref": new_ref,
            "new_content": new_content,
            "close_to": str(c.version or today.isoformat()),
            "diff": f"old from={(old.meta.get('applies_to') or {}).get('from')} → new from={c.version}",
        },
    )


def _render_new_note(c: Claim, today: date, extra_relations: list[tuple[str, str]] | None = None) -> str:
    ep_date = str(c.source.meta.get("captured", today.isoformat()))[:10]
    applies: dict = {}
    if c.tools:
        applies["tools"] = c.tools
    applies["from"] = c.version or ep_date[:7]
    meta = {
        "type": c.note_type,
        "title": c.text[:120],
        "domains": c.domains,
        "status": "candidate",
        "trust": c.trust,
        "confidence": "low",
        "applies_to": applies,
        "first_observed": ep_date,
        "last_verified": None,
        "feedback": {"served": 0, "held": 0, "failed": 0, "unclear": 0},
        "evidence": [c.source.ref] if c.source_kind == "episode" else [],
        "superseded_by": None,
        "source": f"{c.source_kind}: {c.source.ref}",
        "content_hash": c.hash,
    }
    obs_cat = {"failure": "behaviour", "workaround": "fix", "tool-behaviour": "behaviour", "pattern": "behaviour"}[c.note_type]
    lines = ["## Observations", f"- [{obs_cat}] {c.text}"]
    relations = [("derived_from", c.source.ref)] if c.source_kind == "episode" else []
    relations += extra_relations or []
    if relations:
        lines += ["", "## Relations"] + [f"- {rel} [[{ref}]]" for rel, ref in relations]
    return frontmatter.compose(meta, "\n".join(lines))


def _apply_create(vault: Vault, c: Claim, report: RunReport, today: date) -> str:
    rel_dir = _TYPE_DIR[c.note_type]
    path = fsutil.unique_path(vault.path(rel_dir) / f"{fsutil.safe_slug(c.text, 48)}.md")
    fsutil.curator_write(vault, path, _render_new_note(c, today))
    rel = vault.rel(path)
    report.touched.add(rel)
    ref = rel[:-3]
    report.log("CREATE", ref, f"from {c.source.ref}")
    return ref


def _apply_update(vault: Vault, c: Claim, target_ref: str, report: RunReport, today: date) -> None:
    path = resolve_ref(vault, target_ref)
    if path is None:
        report.warnings.append(f"UPDATE target vanished: {target_ref}")
        return
    note = load_note(path, vault)
    meta = dict(note.meta)
    body = note.body
    if c.source_kind == "episode":
        ev = list(meta.get("evidence") or [])
        if c.source.ref not in ev:
            ev.append(c.source.ref)
        meta["evidence"] = ev
    ap = dict(meta.get("applies_to") or {})
    tools = [str(t) for t in (ap.get("tools") or [])]
    for t in c.tools:
        if t not in [x.lower() for x in tools]:
            tools.append(t)
    if tools:
        ap["tools"] = tools
    if c.version and not ap.get("from"):
        ap["from"] = c.version
    meta["applies_to"] = ap
    existing_obs = {re.sub(r"\s+", " ", f.lower()) for _, f in note.observations()}
    if re.sub(r"\s+", " ", c.text.lower()) not in existing_obs:
        obs_sec = section(body, "Observations")
        new_line = f"- [example] {c.text}"
        if obs_sec:
            body = body.replace("## Observations\n" + obs_sec, "## Observations\n" + obs_sec + "\n" + new_line, 1)
        else:
            body = "## Observations\n" + new_line + "\n\n" + body
    fsutil.curator_write(vault, path, frontmatter.compose(meta, body))
    report.touched.add(note.rel)
    report.log("UPDATE", target_ref, f"+evidence {c.source.ref}")


def _mark_inbox_processed(vault: Vault, item: Note, report: RunReport, produced: list[str]) -> None:
    note = load_note(item.path, vault)
    holds = [d for d in report.decisions if d.source_ref == item.ref and d.kind == "HOLD"]
    gated = [d for d in report.decisions if d.source_ref == item.ref and d.gated]
    meta = dict(note.meta)
    if holds and not produced and not gated:
        # stays candidate, re-evaluated as soon as the item changes (§4 HOLD)
        meta["hold_hash"] = _hold_hash(note)
        meta["hold_reason"] = holds[0].rationale[:160]
    else:
        meta["processed"] = report.run_id
    fsutil.curator_write(vault, item.path, frontmatter.compose(meta, note.body))
    report.touched.add(item.rel)


# ============================================================= promotion


def _has_reproducible_evidence(note: Note) -> bool:
    """Recognise concrete reported V1 evidence, not execution attestation.

    A fix/error tag, success claim or code-formatted identifier is insufficient.
    Require a literal command/reproducer with evidence context or an observed
    result, or an explicit evidence artifact that resolves inside the vault.
    Unrecognised prose stays on the ordinary multi-episode promotion path.
    """
    from ..notes import WIKILINK_RE

    evidence_kinds = {"command", "repro", "test", "execution", "evidence", "artifact", "verified-observation"}
    for cat, fact in note.observations():
        observed = bool(re.search(
            r"\b(?:passed|passes|failed|fails|returned|exited|observed|recorded|reproduced|reproduces)\b",
            fact, re.I,
        ))
        literals = re.findall(r"(?<!`)`([^`\r\n]+)`(?!`)", fact)
        for literal in literals:
            words = literal.strip().split()
            command_hint = bool(re.search(
                r"(?:^|\s)(?:--?[A-Za-z][\w-]*|export|import|run|test|check|build|validate|exec"
                r"|\S+\.(?:py|ps1|sh|js|ts|exe|cmd|bat))(?:[=\s]|$)",
                literal, re.I,
            ))
            command = (
                len(words) >= 2
                and re.fullmatch(r"[A-Za-z0-9_./\\:+-]+", words[0]) is not None
                and (cat in ("command", "repro") or command_hint)
            )
            if command and (cat in evidence_kinds or observed):
                return True
        if cat in evidence_kinds and observed and note.vault is not None:
            references = [match.group(1).strip() for match in WIKILINK_RE.finditer(fact)]
            references.extend(literal.strip() for literal in literals if literal.strip().endswith(".md"))
            for ref in references:
                artifact = resolve_ref(note.vault, ref)
                if artifact is not None and artifact != note.path.resolve():
                    return True
    return False


def _promotion_pass(vault: Vault, report: RunReport, today: date) -> None:
    """curator.md §4 promotion rule. Deterministic; runs every compile."""
    for note in knowledge_notes(vault):
        if note.status != "candidate" or note.type not in _TYPE_DIR or "v2_admission" in note.meta:
            continue
        trust = str(note.meta.get("trust") or "unknown")
        if trust in ("third-party", "unknown"):
            continue  # never promotes without a first-party observation
        evidence = [e for e in (note.meta.get("evidence") or []) if isinstance(e, str)]
        distinct = set()
        for ref in evidence:
            path = resolve_ref(vault, ref)
            if path is None:
                continue
            episode = load_note(path, vault)
            if episode.type == "episode" and episode.status in ("summarised", "mined") and not episode.meta.get("v2_evidence"):
                session = episode.meta.get("session_id")
                distinct.add(f"session:{session}" if isinstance(session, str) and session else episode.ref)
        ap = note.meta.get("applies_to") or {}
        reproducible = (
            len(distinct) >= 1
            and _has_reproducible_evidence(note)
            and ap.get("from") is not None
            and (ap.get("tools") or [])
        )
        if len(distinct) >= 2 or reproducible:
            meta = dict(note.meta)
            meta["status"] = "validated"
            if not meta.get("first_observed"):
                meta["first_observed"] = today.isoformat()
            fsutil.curator_write(vault, note.path, frontmatter.compose(meta, note.body))
            report.touched.add(note.rel)
            why = "two independent episodes" if len(distinct) >= 2 else "reproducible evidence + tool version"
            report.log("PROMOTE", note.ref, why)
            _index_add_note(vault, load_note(note.path, vault), report, today)


def _index_add_note(
    vault: Vault, note: Note, report: RunReport, today: date, *, task_bound: bool = False,
) -> None:
    """Same-run index update on promotion (spec: same commit)."""
    if type(task_bound) is not bool:
        raise VaultError("task-bound index authorization must be explicit")
    if task_bound:
        from ..learning_flow import validate_note_binding

        validate_note_binding(vault, note)
    sec = _INDEX_SECTION_FOR_TYPE.get(note.type or "", "Read first")
    if not eligible_for_section(note, sec, now=today, task_bound=task_bound):
        return
    gloss = " ".join(note.title.split()[:12])
    declared = {d.name for d in load_domains(vault)}
    for domain in note.meta.get("domains") or []:
        di = load_index(vault, domain)
        if di is None and domain in declared:
            # a declared domain earns its index the moment content exists
            # (empty sections stay — they tell the agent there is nothing known)
            from ..indexes import DomainIndex as _DI, SECTIONS as _SECS, index_path as _ipath

            di = _DI(domain=domain, path=_ipath(vault, domain), title=domain.replace("-", " ").title())
            for s in _SECS:
                di.sections[s] = []
            report.log("INDEX-CREATE", domain, "index created for declared domain")
        if di is None:
            report.warnings.append(f"no index for domain `{domain}`; [[{note.ref}]] not linked")
            continue
        if di.find(note.ref):
            continue
        if di.link_count() >= config.INDEX_MAX_LINKS:
            report.decisions.append(
                Decision("FLAG", f"index {domain} is full ({config.INDEX_MAX_LINKS} links); decide which note leaves", target_ref=note.ref)
            )
            continue
        di.add(sec, note.ref, gloss)
        _write_index(vault, di, report, today)
        report.log("INDEX", f"{domain} += {note.path.stem}", sec)


def _write_index(vault: Vault, di: DomainIndex, report: RunReport, today: date) -> None:
    if write_index_if_changed(vault, di, today.isoformat()):
        report.touched.add(vault.rel(di.path))


# ================================================================= lint


def run_lint(vault: Vault, now: datetime | None = None) -> RunReport:
    """Run legacy housekeeping transactionally; non-legacy inspection is read-only."""
    report = RunReport(_run_id(now))
    today = _today(now)
    from ..experience import get_mode

    mode = get_mode(vault)
    if mode != "legacy":
        if mode == "strict":
            from ..learning_flow import validate_note_binding

            for note in knowledge_notes(vault):
                if note.meta.get("v2_admission"):
                    try:
                        validate_note_binding(vault, note)
                    except VaultError as exc:
                        report.warnings.append(f"V2 lesson requires review: {exc}")
        else:
            report.warnings.append(f"curator publication is disabled in {mode} mode")
        return report

    active = current_transaction(vault)
    boundary = nullcontext(active) if active is not None else curation_transaction(vault, run_id=report.run_id)
    with boundary:
        if get_mode(vault) != "legacy":
            raise VaultError("profile changed while waiting for curation; retry with the current profile")
        return _run_legacy_lint(vault, report, today, now=now)


def _run_legacy_lint(
    vault: Vault, report: RunReport, today: date, *, now: datetime | None = None,
) -> RunReport:
    snapshot = feedback.apply_knowledge_feedback(vault, report, now=now)
    _duplicate_pass(vault, report)
    _orphan_pass(vault, report, today)
    _inbox_pressure_pass(vault, report, today)
    _graduation_pass(vault, snapshot.assessments, report)
    _compaction_pass(vault, report, today)
    feedback.complete_attention(vault, report, snapshot)

    _finalise_run(vault, report, today, f"curator lint {report.run_id}")
    return report


def _duplicate_pass(vault: Vault, report: RunReport) -> None:
    validated = [
        n for n in knowledge_notes(vault)
        if n.status == "validated" and not n.parse_error and "v2_admission" not in n.meta
    ]
    suppressed = load_suppressions(vault)
    for i, a in enumerate(validated):
        for b in validated[i + 1 :]:
            if a.type != b.type:
                continue
            if not set(a.meta.get("domains") or []) & set(b.meta.get("domains") or []):
                continue
            if suppression_key("MERGE", a.rel, b.rel) in suppressed:
                continue  # human said "keep both" — do not ask again
            obs_a = keywords(" ".join(f for _, f in a.observations()))
            obs_b = keywords(" ".join(f for _, f in b.observations()))
            if jaccard(obs_a, obs_b) >= 0.4:
                report.decisions.append(
                    Decision(
                        "MERGE",
                        "same claim in different words; overlapping observations; both validated",
                        target_ref=a.ref,
                        other_ref=b.ref,
                        payload={"target": a.rel, "other": b.rel, "draft": f"union of observations of {a.path.stem} and {b.path.stem}; every distinct condition kept"},
                    )
                )


def _orphan_pass(vault: Vault, report: RunReport, today: date) -> None:
    linked: set[str] = set()
    for di in list_domain_indexes(vault):
        linked.update(e.ref.split("/")[-1] for _, e in di.all_entries())
    gp = vault.path(config.GENERAL_INDEX)
    if gp.exists():
        from ..indexes import parse_index

        linked.update(e.ref.split("/")[-1] for _, e in parse_index(gp, vault).all_entries())
    for note in knowledge_notes(vault):
        section_name = _INDEX_SECTION_FOR_TYPE.get(note.type or "", "Read first")
        if note.status != "validated" or note.path.stem in linked or not eligible_for_section(note, section_name, now=today):
            continue
        _index_add_note(vault, note, report, today)
        still_linked = any(load_index(vault, d) and load_index(vault, d).find(note.path.stem) for d in note.meta.get("domains") or [])
        if not still_linked and suppression_key("REJECT", note.rel) not in load_suppressions(vault):
            report.decisions.append(
                Decision("REJECT", "validated note linked from no index and no index has room", target_ref=note.ref, payload={"target": note.rel})
            )


def _inbox_pressure_pass(vault: Vault, report: RunReport, today: date) -> None:
    unprocessed = [
        n for n in iter_notes(vault, config.INBOX)
        if n.type in ("candidate", None) and "processed" not in n.meta and "v2_admission" not in n.meta
    ]

    def age_days(n: Note) -> int:
        cap = str(n.meta.get("captured", ""))[:10]
        try:
            return (today - datetime.strptime(cap, "%Y-%m-%d").date()).days
        except ValueError:
            return 0

    overage = [n for n in unprocessed if age_days(n) > config.INBOX_PRESSURE_AGE_DAYS]
    to_move = list(overage)
    if len(unprocessed) > config.INBOX_PRESSURE_COUNT:
        by_age = sorted(unprocessed, key=age_days, reverse=True)
        for n in by_age:
            if len(unprocessed) - len(to_move) <= config.INBOX_PRESSURE_COUNT:
                break
            if n not in to_move:
                to_move.append(n)
    for n in to_move:
        meta = dict(n.meta)
        meta["status"] = "unreviewed"
        dest = fsutil.unique_path(vault.path(config.EPISODE_UNREVIEWED) / n.path.name)
        fsutil.curator_write(vault, dest, frontmatter.compose(meta, n.body))
        fsutil.curator_unlink(vault, n.path)
        report.touched.add(vault.rel(dest))
        report.touched.add(n.rel)
        report.log("PARK", n.ref, "inbox pressure → episodes/_unreviewed")


def _compaction_pass(vault: Vault, report: RunReport, today: date) -> None:
    """episode.md rule 6: monthly, the curator writes
    `episodes/_summaries/YYYY-MM.md`. Raw episodes stay.

    Deterministic aggregation, not summarisation (mandate §G): the digest
    carries each episode's goal line, decisions, problems and knowledge
    outcomes verbatim. Only complete months are compacted, and an existing
    summary is never rewritten.
    """
    current_month = today.strftime("%Y-%m")
    by_month: dict[str, list[Note]] = {}
    for ep in iter_notes(vault, config.EPISODES):
        if ep.type != "episode" or ep.parse_error:
            continue
        if ep.rel.startswith((config.EPISODE_SUMMARIES, config.EPISODE_UNREVIEWED)):
            continue
        if ep.status != "mined":
            continue  # only settled episodes compact
        month = str(ep.meta.get("captured", ""))[:7]
        if len(month) != 7 or month >= current_month:
            continue
        by_month.setdefault(month, []).append(ep)

    for month, eps in sorted(by_month.items()):
        out = vault.path(config.EPISODE_SUMMARIES) / f"{month}.md"
        if out.exists():
            continue
        lines = [f"# Episodes — {month}", "", f"{len(eps)} mined episode(s). Raw episodes stay; this digest is derived."]
        for ep in sorted(eps, key=lambda e: str(e.meta.get("captured", ""))):
            parsed = parse_episode(ep)
            lines += ["", f"## [[{ep.ref}]]", f"- [goal] {section(ep.body, 'Goal').strip().splitlines()[0] if section(ep.body, 'Goal').strip() else '(none recorded)'}"]
            for d in parsed.decisions:
                lines.append(f"- [decision] {d}")
            for p in parsed.problems:
                lines.append(f"- [problem] {p}")
            for u in parsed.used:
                lines.append(f"- [outcome] [[{u.ref}]] — {u.outcome}")
        meta = {
            "type": "episode-summary",
            "title": f"Episodes {month}",
            "month": month,
            "episodes": len(eps),
            "generated": today.isoformat(),
        }
        fsutil.curator_write(vault, out, frontmatter.compose(meta, "\n".join(lines)))
        report.touched.add(vault.rel(out))
        report.log("COMPACT", vault.rel(out)[:-3], f"{len(eps)} episode(s)")


def _graduation_pass(
    vault: Vault, assessments: dict[str, analytics.KnowledgeAssessment], report: RunReport,
) -> None:
    feedback.graduation_candidates(vault, assessments, report)


# ====================================================== review application


def _apply_approved_reviews(vault: Vault, report: RunReport, today: date) -> None:
    for path in pending_review_files(vault):
        items = parse_review_file(path)
        errors = [item.error for item in items if item.error]
        if errors:
            report.warnings.extend(f"{vault.rel(path)}: review remains pending: {error}" for error in errors)
            continue
        if any(item.kind == "ADMIT" for item in items):
            report.warnings.append(f"{vault.rel(path)}: V2 admission review requires the strict profile; left pending")
            continue
        try:
            for item in items:
                if item.kind in ("MERGE", "SUPERSEDE", "REJECT") and item.approved:
                    _review_preconditions(vault, item)
        except ValueError as exc:
            report.warnings.append(f"{vault.rel(path)}: review remains pending: {exc}")
            continue
        retired: set[int] = set()
        for position, item in enumerate(items):
            if item.kind in ("MERGE", "SUPERSEDE", "REJECT") and item.approved:
                try:
                    _apply_review_item(vault, item, report, today)
                except CurationConflict:
                    raise
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise VaultError(f"review item failed: {item.kind} {item.header}: {exc}; review remains pending") from exc
                retired.add(position)
            elif item.choice:
                # the human chose an alternative: record it so the proposal is
                # not regenerated every run (curator.md §7 / §10 time budget)
                p = item.payload or {}
                refs = [str(p[k]) for k in ("target", "other") if p.get(k)] or [item.header]
                key = (
                    "ATTENTION\t" + p["review_key"] if p.get("review_only") is True
                    and isinstance(p.get("review_key"), str) else suppression_key(item.kind, *refs)
                )
                record_suppression(vault, key, item.choice, today.isoformat())
                report.touched.add(SUPPRESSIONS)
                report.log(item.kind, item.header[:60], f"human chose `{item.choice}` — not re-proposed")
                retired.add(position)
        if archived := retire_review_items(vault, path, retired):
            report.touched.add(vault.rel(archived))
            report.touched.add(vault.rel(path))
            report.log("ARCHIVE", vault.rel(path), "completed review items retired")


def _review_preconditions(vault: Vault, item: ReviewItem) -> tuple[dict, dict[str, Path]]:
    p = item.payload or {}
    if p.get("review_only") is True:
        raise ValueError("attention suggestions cannot be approved as factual knowledge actions")
    expected = p.get("expected_hashes")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("expected_hashes are missing; regenerate the proposal and approve its fresh snapshot")
    paths = review_input_paths(vault, p)
    required = {"target"}
    if item.kind == "MERGE":
        required.add("other")
    if item.kind == "SUPERSEDE" and p.get("new_content"):
        required.add("new_ref")
    if not required.issubset(paths):
        raise ValueError("review payload is missing a required target reference")
    if not {vault.rel(path) for path in paths.values()}.issubset(expected):
        raise ValueError("expected_hashes do not cover every reviewed input; regenerate and approve a fresh proposal")
    return expected, paths


def _review_note(vault: Vault, path: Path) -> Note:
    note = load_note(path, vault)
    if note.parse_error:
        raise ValueError(f"{note.rel}: reviewed note has malformed frontmatter")
    if note.type == "gap" or "v2_admission" in note.meta:
        raise ValueError(f"{note.rel}: gap or V2 knowledge cannot receive legacy factual review actions")
    return note


def _apply_review_item(vault: Vault, item: ReviewItem, report: RunReport, today: date) -> None:
    p = item.payload or {}
    expected, paths = _review_preconditions(vault, item)
    tx = current_transaction(vault)
    if tx is None:
        raise VaultError("review application requires an active curation transaction")
    tx.expect_hashes(expected, decision=p)
    if item.kind == "REJECT":
        path = paths["target"]
        note = _review_note(vault, path)
        meta = dict(note.meta)
        meta["status"] = "rejected"
        if note.rel.startswith(config.INBOX):
            meta["processed"] = report.run_id
        fsutil.curator_write(vault, path, frontmatter.compose(meta, note.body))
        report.touched.add(note.rel)
        _remove_from_indexes(vault, note.ref, "rejected", report, today)
        report.log("REJECT", note.ref, "approved in review")
    elif item.kind == "SUPERSEDE":
        old_path = paths["target"]
        old = _review_note(vault, old_path)
        new_ref = p.get("new_ref", "")
        if p.get("new_content") and new_ref:
            new_path = paths["new_ref"]
            fsutil.curator_write(vault, new_path, p["new_content"])
            report.touched.add(vault.rel(new_path))
        meta = dict(old.meta)
        meta["status"] = "superseded"
        meta["superseded_by"] = new_ref or None
        ap = dict(meta.get("applies_to") or {})
        ap["to"] = p.get("close_to", today.isoformat())
        meta["applies_to"] = ap
        fsutil.curator_write(vault, old_path, frontmatter.compose(meta, old.body))
        report.touched.add(old.rel)
        _remove_from_indexes(vault, old.ref, f"superseded {today.isoformat()}" + (f" → [[{new_ref.split('/')[-1]}]]" if new_ref else ""), report, today)
        report.log("SUPERSEDE", old.ref, f"→ {new_ref or 'closed'}")
    elif item.kind == "MERGE":
        tp, op = paths["target"], paths["other"]
        tnote, onote = _review_note(vault, tp), _review_note(vault, op)
        meta, body = dict(tnote.meta), tnote.body
        existing = {re.sub(r"\s+", " ", f.lower()) for _, f in tnote.observations()}
        add_lines = [
            f"- [{cat}] {fact}"
            for cat, fact in onote.observations()
            if re.sub(r"\s+", " ", fact.lower()) not in existing  # every distinct condition kept (§4 MERGE rule)
        ]
        if add_lines:
            obs = section(body, "Observations")
            body = body.replace("## Observations\n" + obs, "## Observations\n" + obs + "\n" + "\n".join(add_lines), 1) if obs else body + "\n## Observations\n" + "\n".join(add_lines)
        ev = list(meta.get("evidence") or [])
        for e in onote.meta.get("evidence") or []:
            if e not in ev:
                ev.append(e)
        meta["evidence"] = ev
        fsutil.curator_write(vault, tp, frontmatter.compose(meta, body))
        ometa = dict(onote.meta)
        ometa["status"] = "superseded"
        ometa["superseded_by"] = tnote.ref
        fsutil.curator_write(vault, op, frontmatter.compose(ometa, onote.body))
        report.touched.update({tnote.rel, onote.rel})
        _remove_from_indexes(vault, onote.ref, f"merged into [[{tnote.ref}]]", report, today)
        report.log("MERGE", f"{tnote.ref} ← {onote.ref}", "approved in review")


def _remove_from_indexes(vault: Vault, ref: str, reason: str, report: RunReport, today: date) -> None:
    for di in list_domain_indexes(vault):
        if di.find(ref):
            di.remove(ref)
            di.add("Recently changed", ref, reason)
            _write_index(vault, di, report, today)


# ============================================================== finalise


def _finalise_run(vault: Vault, report: RunReport, today: date, message: str) -> None:
    review = write_review_file(vault, report.run_id, today, report.decisions)
    if review is not None:
        report.touched.add(vault.rel(review))

    if report.log_lines:
        log_path = vault.path(config.CURATION_LOG)
        for line in report.log_lines:
            fsutil.append_line(log_path, f"{today.isoformat()}  {report.run_id}  {line}")
        report.touched.add(config.CURATION_LOG)

    # Regenerate packs (derived, gitignored, disposable — P1/Q4).
    try:
        packs.compile_all(vault)
    except packs.PackError as e:
        report.warnings.append(str(e))

    tx = current_transaction(vault)
    if tx is not None:
        report.touched.update(tx.publishable_paths)
    if report.touched:
        report.commit = gitutil.commit_paths(vault, sorted(report.touched), f"{message}\n\nOne curator run, one logical change set.")
        if report.commit.failed:
            if tx is None:
                raise VaultError(f"curation publication failed: {report.commit.message}")
            tx.fail_publication(report.commit.message)
        if not report.commit.committed:
            report.warnings.append(report.commit.message)
