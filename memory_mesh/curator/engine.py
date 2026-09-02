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
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import config, frontmatter, fsutil, gitutil, packs, redact
from ..config import Vault
from ..confidence import (
    FeedbackState,
    decay_due,
    derive_confidence,
    drop_one_level,
    graduation_ready,
    never_exercised_flag,
)
from ..episodes import mark_mined, parse_episode
from ..indexes import (
    LINK_SECTIONS,
    DomainIndex,
    index_path,
    list_domain_indexes,
    load_index,
    render_index,
)
from ..notes import Note, iter_notes, knowledge_notes, load_note, resolve_ref, section
from ..router import load_domains, match as router_match
from .adapter import NullAdapter, ReasoningAdapter
from .decisions import Decision
from .neighbours import find_neighbours, jaccard, keywords
from .review import (
    SUPPRESSIONS,
    archive_review_file,
    is_fully_decided,
    load_suppressions,
    parse_review_file,
    pending_review_files,
    record_suppression,
    review_path,
    suppression_key,
    write_review_file,
)

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
    adapter = adapter or NullAdapter()
    report = RunReport(_run_id(now))
    today = _today(now)

    _apply_approved_reviews(vault, report, today)

    inbox_items = []
    held_items = []
    for n in iter_notes(vault, config.INBOX):
        if n.type not in ("candidate", None) or "processed" in n.meta:
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
        if n.type == "episode" and n.status == "summarised"
    ]

    # §2.1 redaction BEFORE anything is read for meaning
    inbox_items = [_redaction_pass(vault, n, report) for n in inbox_items]
    episodes_ready = [_redaction_pass(vault, n, report) for n in episodes_ready]

    known_hashes = _existing_hashes(vault)
    declared_domains = [d.name for d in load_domains(vault)]

    for item in inbox_items:
        if item.parse_error:
            # malformed frontmatter is reportable, never fatal: the item was
            # still redacted in place above, it just cannot be read for meaning
            report.warnings.append(f"{item.rel}: unreadable frontmatter ({item.parse_error}); skipped, fix and re-run")
            continue
        _scan_injection(item, report)
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
        claims = _claims_from_episode(vault, ep, declared_domains, adapter)
        produced = _decide_claims(vault, claims, known_hashes, adapter, report, today)
        mark_mined(vault, ep.path, produced)
        report.touched.add(ep.rel)
        report.log("MINED", ep.ref, f"claims {len(claims)}")

    if held_items:
        report.warnings.append(f"{len(held_items)} inbox item(s) on hold await new evidence or review")

    _promotion_pass(vault, report, today)
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
        h = n.meta.get("content_hash")
        if isinstance(h, str):
            hashes[h] = n.ref
    return hashes


def _claims_from_inbox(vault: Vault, item: Note, declared: list[str]) -> list[Claim]:
    text = " ".join(fact for _, fact in item.observations()) or item.title
    return [_build_claim(text, item, "inbox", declared)]


def _claims_from_episode(vault: Vault, ep: Note, declared: list[str], adapter: ReasoningAdapter) -> list[Claim]:
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
    return [_build_claim(t, ep, "episode", declared) for t in texts]


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
    neigh = find_neighbours(vault, c.text, c.domains, c.tools, c.note_type)
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
    for cat, fact in note.observations():
        if cat in ("command", "error", "repro", "fix") or "`" in fact:
            return True
    return False


def _promotion_pass(vault: Vault, report: RunReport, today: date) -> None:
    """curator.md §4 promotion rule. Deterministic; runs every compile."""
    for note in knowledge_notes(vault):
        if note.status != "candidate" or note.type not in _TYPE_DIR:
            continue
        trust = str(note.meta.get("trust") or "unknown")
        if trust in ("third-party", "unknown"):
            continue  # never promotes without a first-party observation
        evidence = [e for e in (note.meta.get("evidence") or []) if isinstance(e, str)]
        distinct = {e.split("/")[-1] for e in evidence if resolve_ref(vault, e) is not None}
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


def _index_add_note(vault: Vault, note: Note, report: RunReport, today: date) -> None:
    """Same-run index update on promotion (spec: same commit)."""
    sec = _INDEX_SECTION_FOR_TYPE.get(note.type or "", "Read first")
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
        di.add(sec, note.path.stem, gloss)
        _write_index(vault, di, report, today)
        report.log("INDEX", f"{domain} += {note.path.stem}", sec)


def _write_index(vault: Vault, di: DomainIndex, report: RunReport, today: date) -> None:
    fsutil.curator_write(vault, di.path, render_index(di, today.isoformat()))
    report.touched.add(vault.rel(di.path))


# ================================================================= lint


def run_lint(vault: Vault, now: datetime | None = None) -> RunReport:
    report = RunReport(_run_id(now))
    today = _today(now)

    tally = _tally_from_episodes(vault)
    _feedback_and_confidence_pass(vault, tally, report, today)
    _decay_pass(vault, report, today)
    _contradiction_pass(vault, tally, report, today)
    _duplicate_pass(vault, report)
    _orphan_pass(vault, report, today)
    _index_hygiene_pass(vault, tally, report, today)
    _inbox_pressure_pass(vault, report, today)
    _graduation_pass(vault, tally, report)
    _compaction_pass(vault, report, today)

    _finalise_run(vault, report, today, f"curator lint {report.run_id}")
    return report


@dataclass
class _Tally:
    fb: FeedbackState = field(default_factory=FeedbackState)
    last_verified: str | None = None
    last_outcome: str | None = None
    last_outcome_date: str | None = None
    fail_reasons: list[str] = field(default_factory=list)
    fail_episodes: list[str] = field(default_factory=list)


def _tally_from_episodes(vault: Vault) -> dict[str, _Tally]:
    """Reconstruct served/held/failed/unclear for every referenced note from
    ALL episodes (issues.md I-007) — recall-log.tsv plays no part (P1)."""
    tallies: dict[str, _Tally] = {}
    for ep in iter_notes(vault, config.EPISODES):
        if ep.type != "episode" or ep.rel.startswith(config.EPISODE_UNREVIEWED):
            continue
        parsed = parse_episode(ep)
        ep_date = str(ep.meta.get("captured", ""))[:10]
        served_refs = {r.split("/")[-1] for r in parsed.retrieved} | {u.ref.split("/")[-1] for u in parsed.used}
        for key in served_refs:
            t = tallies.setdefault(key, _Tally())
            t.fb = FeedbackState(t.fb.served + 1, t.fb.held, t.fb.failed, t.fb.unclear)
        for use in parsed.used:
            key = use.ref.split("/")[-1]
            t = tallies.setdefault(key, _Tally())
            held, failed, unclear = t.fb.held, t.fb.failed, t.fb.unclear
            if use.outcome == "held":
                held += 1
                if not t.last_verified or ep_date > t.last_verified:
                    t.last_verified = ep_date
            elif use.outcome == "failed":
                failed += 1
                t.fail_reasons.append(use.reason)
                t.fail_episodes.append(ep.ref)
            elif use.outcome == "unclear":
                unclear += 1
            t.fb = FeedbackState(t.fb.served, held, failed, unclear)
            if use.outcome != "not-applicable" and (not t.last_outcome_date or ep_date >= t.last_outcome_date):
                t.last_outcome, t.last_outcome_date = use.outcome, ep_date
    return tallies


def _feedback_and_confidence_pass(vault: Vault, tally: dict[str, _Tally], report: RunReport, today: date) -> None:
    for note in knowledge_notes(vault):
        if note.type not in _TYPE_DIR or note.parse_error:
            continue
        t = tally.get(note.path.stem, _Tally())
        meta = dict(note.meta)
        new_fb = {"served": t.fb.served, "held": t.fb.held, "failed": t.fb.failed, "unclear": t.fb.unclear}
        conf = derive_confidence(t.fb, t.last_verified or meta.get("last_verified"), str(meta.get("trust") or "unknown"), str(meta.get("status") or "candidate"), today)
        if t.last_outcome == "failed":
            conf = drop_one_level(conf)  # §5: same-version failure drops one level immediately
        changed = meta.get("feedback") != new_fb or meta.get("confidence") != conf or (
            t.last_verified and meta.get("last_verified") != t.last_verified
        )
        if not changed:
            continue
        meta["feedback"] = new_fb
        meta["confidence"] = conf
        if t.last_verified:
            meta["last_verified"] = t.last_verified
        fsutil.curator_write(vault, note.path, frontmatter.compose(meta, note.body))
        report.touched.add(note.rel)
        report.log("FEEDBACK", note.ref, f"served {t.fb.served} held {t.fb.held} failed {t.fb.failed} → {conf}")
        if never_exercised_flag(t.fb, meta.get("first_observed"), today):
            report.decisions.append(Decision("FLAG", "served but never exercised for 90 days: still true, or never relevant?", target_ref=note.ref))


def _decay_pass(vault: Vault, report: RunReport, today: date) -> None:
    for note in knowledge_notes(vault):
        if note.parse_error or not decay_due(str(note.type), str(note.status), note.meta.get("last_verified"), note.meta.get("first_observed"), today):
            continue
        meta = dict(note.meta)
        meta["status"] = "stale"
        fsutil.curator_write(vault, note.path, frontmatter.compose(meta, note.body))
        report.touched.add(note.rel)
        report.log("STALE", note.ref, "no held outcome within the decay window")
        _index_move_to_changed(vault, note, f"stale {today.isoformat()}", report, today)


def _index_move_to_changed(vault: Vault, note: Note, reason: str, report: RunReport, today: date) -> None:
    for domain in note.meta.get("domains") or []:
        di = load_index(vault, domain)
        if di is None or not di.find(note.path.stem):
            continue
        di.remove(note.path.stem)
        di.add("Recently changed", note.path.stem, reason)
        _write_index(vault, di, report, today)


def _contradiction_pass(vault: Vault, tally: dict[str, _Tally], report: RunReport, today: date) -> None:
    """curator.md §6: single same-version failure → HOLD; repeated → gated
    SUPERSEDE/REJECT; different-version evidence arrives via compile."""
    suppressed = load_suppressions(vault)
    for note in knowledge_notes(vault):
        if note.parse_error or note.status not in ("validated", "candidate"):
            continue
        t = tally.get(note.path.stem)
        if not t or t.fb.failed == 0:
            continue
        if suppression_key("SUPERSEDE", note.rel) in suppressed:
            continue  # human held this one; new evidence re-opens it via compile
        note_from = str((note.meta.get("applies_to") or {}).get("from") or "")
        different_version = any(
            (vm := _VERSION_RE.search(reason)) and note_from and vm.group(1) != note_from
            for reason in t.fail_reasons
        )
        if different_version:
            report.decisions.append(
                Decision(
                    "SUPERSEDE",
                    "failed outcome names a different version than applies_to.from — behaviour likely changed",
                    target_ref=note.ref,
                    payload={
                        "target": note.rel,
                        # no replacement note exists yet, so no `superseded_by`
                        # is recorded — a dangling ref would break §6's promise
                        # that history stays navigable. The window is closed and
                        # the successor arrives with its own evidence.
                        "new_ref": "",
                        "new_content": "",
                        "close_to": today.isoformat(),
                        "diff": f"failures: {'; '.join(t.fail_reasons[:3])}",
                    },
                )
            )
        elif t.fb.failed == 1:
            report.decisions.append(
                Decision("HOLD", f"one failed outcome at the applicable version ({t.fail_episodes[0] if t.fail_episodes else '?'}) — validation queue", target_ref=note.ref)
            )
        else:
            report.decisions.append(
                Decision(
                    "SUPERSEDE",
                    f"{t.fb.failed} failed outcomes at the applicable version — supersede or reject",
                    target_ref=note.ref,
                    payload={
                        "target": note.rel,
                        "new_ref": "",
                        "new_content": "",
                        "close_to": today.isoformat(),
                        "diff": f"failures: {'; '.join(t.fail_reasons[:3])}",
                    },
                )
            )


def _duplicate_pass(vault: Vault, report: RunReport) -> None:
    validated = [n for n in knowledge_notes(vault) if n.status == "validated" and not n.parse_error]
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
        if note.status != "validated" or note.path.stem in linked:
            continue
        _index_add_note(vault, note, report, today)
        still_linked = any(load_index(vault, d) and load_index(vault, d).find(note.path.stem) for d in note.meta.get("domains") or [])
        if not still_linked and suppression_key("REJECT", note.rel) not in load_suppressions(vault):
            report.decisions.append(
                Decision("REJECT", "validated note linked from no index and no index has room", target_ref=note.ref, payload={"target": note.rel})
            )


def _index_hygiene_pass(vault: Vault, tally: dict[str, _Tally], report: RunReport, today: date) -> None:
    for di in list_domain_indexes(vault):
        changed = False
        for s in list(di.sections):
            for e in list(di.sections[s]):
                target = resolve_ref(vault, e.ref)
                if target is None:
                    di.sections[s].remove(e)
                    di.add("Recently changed", e.ref, "target missing")
                    changed = True
                    report.log("INDEX-FIX", di.domain, f"[[{e.ref}]] unresolved → Recently changed")
                    continue
                status = load_note(target, vault).status
                if s in ("Read first", "Current workarounds") and status not in ("validated",):
                    di.sections[s].remove(e)
                    di.add("Recently changed", e.ref, f"{status} {today.isoformat()}")
                    changed = True
                    report.log("INDEX-FIX", di.domain, f"[[{e.ref}]] {status} → Recently changed")
                elif s == "Known failures" and status in ("resolved", "superseded", "stale", "rejected"):
                    di.sections[s].remove(e)
                    di.add("Recently changed", e.ref, f"{status} {today.isoformat()}")
                    changed = True
                    report.log("INDEX-FIX", di.domain, f"[[{e.ref}]] {status} → Recently changed")
        # refresh Recently verified (held within 30 days)
        recent: list[tuple[str, str]] = []
        for key, t in tally.items():
            if t.last_verified:
                try:
                    dd = (today - datetime.strptime(t.last_verified, "%Y-%m-%d").date()).days
                except ValueError:
                    continue
                if 0 <= dd <= 30 and di.find(key):
                    recent.append((key, t.last_verified))
        new_rv = [f"{k}|held {d}" for k, d in sorted(recent)]
        old_rv = [f"{e.ref.split('/')[-1]}|{e.gloss}" for e in di.sections.get("Recently verified (30 days)", [])]
        if new_rv != old_rv:
            di.sections["Recently verified (30 days)"] = [_entry(k, f"held {d}") for k, d in sorted(recent)]
            changed = True
        if missing := [s for s in ("Read first", "Known failures", "Current workarounds", "Active project", "Recently verified (30 days)", "Recently changed") if s not in di.sections]:
            for s in missing:
                di.sections[s] = []
            changed = True
        declared = di.meta.get("links")
        if isinstance(declared, int) and declared != di.link_count():
            changed = True
        if di.link_count() > config.INDEX_MAX_LINKS:
            report.decisions.append(Decision("FLAG", f"index {di.domain} has {di.link_count()} links (max {config.INDEX_MAX_LINKS}) — one must leave", target_ref=di.domain))
        if changed:
            _write_index(vault, di, report, today)


def _entry(ref: str, gloss: str):
    from ..indexes import Entry

    return Entry(ref, gloss)


def _inbox_pressure_pass(vault: Vault, report: RunReport, today: date) -> None:
    unprocessed = [n for n in iter_notes(vault, config.INBOX) if "processed" not in n.meta]

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
        n.path.unlink()
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


def _graduation_pass(vault: Vault, tally: dict[str, _Tally], report: RunReport) -> None:
    lines: list[str] = []
    for note in knowledge_notes(vault):
        if note.parse_error:
            continue
        t = tally.get(note.path.stem, _Tally())
        has_procedure = any(cat in ("procedure", "fix", "command", "step") for cat, _ in note.observations())
        if graduation_ready(t.fb, str(note.status), has_procedure):
            lines.append(f"- [[{note.ref}]] — held {t.fb.held}, failed 0 — propose a skill (curator never edits skills/ itself)")
    if not lines:
        return
    path = vault.path(config.GRADUATION_FILE)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Graduation candidates\n"
    new_lines = [l for l in lines if l.split(" — ")[0] not in existing]
    if new_lines:
        fsutil.curator_write(vault, path, existing.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n")
        report.touched.add(config.GRADUATION_FILE)
        for l in new_lines:
            report.log("GRADUATE?", l.split("—")[0].strip("- [] "), "added to graduation candidates")


# ====================================================== review application


def _apply_approved_reviews(vault: Vault, report: RunReport, today: date) -> None:
    for path in pending_review_files(vault):
        items = parse_review_file(path)
        for item in items:
            if item.kind in ("MERGE", "SUPERSEDE", "REJECT") and item.approved:
                try:
                    _apply_review_item(vault, item, report, today)
                except Exception as e:  # a broken payload must not halt the run
                    report.warnings.append(f"review item failed: {item.kind} {item.header}: {e}")
            elif item.choice:
                # the human chose an alternative: record it so the proposal is
                # not regenerated every run (curator.md §7 / §10 time budget)
                p = item.payload or {}
                refs = [str(p[k]) for k in ("target", "other") if p.get(k)] or [item.header]
                record_suppression(vault, suppression_key(item.kind, *refs), item.choice, today.isoformat())
                report.touched.add(SUPPRESSIONS)
                report.log(item.kind, item.header[:60], f"human chose `{item.choice}` — not re-proposed")
        if is_fully_decided(items):
            archived = archive_review_file(vault, path)
            report.touched.add(vault.rel(archived))
            report.touched.add(vault.rel(path))
            report.log("ARCHIVE", vault.rel(path))


def _apply_review_item(vault: Vault, item, report: RunReport, today: date) -> None:
    p = item.payload or {}
    if item.kind == "REJECT":
        target = p.get("target") or item.header
        path = vault.path(target) if (vault.root / target).exists() else resolve_ref(vault, target)
        if path is None or not Path(path).exists():
            report.warnings.append(f"REJECT target missing: {target}")
            return
        note = load_note(Path(path), vault)
        meta = dict(note.meta)
        meta["status"] = "rejected"
        if note.rel.startswith(config.INBOX):
            meta["processed"] = report.run_id
        fsutil.curator_write(vault, Path(path), frontmatter.compose(meta, note.body))
        report.touched.add(note.rel)
        _remove_from_indexes(vault, Path(path).stem, "rejected", report, today)
        report.log("REJECT", note.ref, "approved in review")
    elif item.kind == "SUPERSEDE":
        target = p.get("target", "")
        old_path = vault.path(target)
        if not old_path.exists():
            report.warnings.append(f"SUPERSEDE target missing: {target}")
            return
        new_ref = p.get("new_ref", "")
        if p.get("new_content") and new_ref:
            new_path = vault.path(new_ref + ".md")
            fsutil.curator_write(vault, new_path, p["new_content"])
            report.touched.add(vault.rel(new_path))
        old = load_note(old_path, vault)
        meta = dict(old.meta)
        meta["status"] = "superseded"
        meta["superseded_by"] = new_ref or None
        ap = dict(meta.get("applies_to") or {})
        ap["to"] = p.get("close_to", today.isoformat())
        meta["applies_to"] = ap
        fsutil.curator_write(vault, old_path, frontmatter.compose(meta, old.body))
        report.touched.add(old.rel)
        _remove_from_indexes(vault, old_path.stem, f"superseded {today.isoformat()}" + (f" → [[{new_ref.split('/')[-1]}]]" if new_ref else ""), report, today)
        report.log("SUPERSEDE", old.ref, f"→ {new_ref or 'closed'}")
    elif item.kind == "MERGE":
        target, other = p.get("target", ""), p.get("other", "")
        tp, op = vault.path(target), vault.path(other)
        if not tp.exists() or not op.exists():
            report.warnings.append(f"MERGE targets missing: {target} / {other}")
            return
        tnote, onote = load_note(tp, vault), load_note(op, vault)
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
        _remove_from_indexes(vault, op.stem, f"merged into [[{tp.stem}]]", report, today)
        report.log("MERGE", f"{tnote.ref} ← {onote.ref}", "approved in review")


def _remove_from_indexes(vault: Vault, stem: str, reason: str, report: RunReport, today: date) -> None:
    for di in list_domain_indexes(vault):
        if di.find(stem):
            di.remove(stem)
            di.add("Recently changed", stem, reason)
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

    if report.touched:
        report.commit = gitutil.commit_paths(vault, sorted(report.touched), f"{message}\n\nOne curator run, one logical change set.")
        if not report.commit.committed:
            report.warnings.append(report.commit.message)
