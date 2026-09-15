"""Partial session summaries and provenanced projections of reported feedback.

Scaffolding records retrieved references and observable checkpoint captures.
Journal outcomes remain explicitly reported, never execution attestations.
Finishing validates available evidence without fabricating missing sections.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, frontmatter, fsutil, redact
from .config import Vault, VaultError
from .experience_types import require_id, require_text
from .notes import Note, load_note, section
from .outcome_types import FAILURE_REASONS, SUBJECT_OUTCOMES, OutcomeEvent, parse_timestamp

REQUIRED_SECTIONS = (
    "Goal",
    "What happened",
    "Decisions",
    "Problems",
    "Knowledge retrieved",
    "Knowledge used",
    "Candidate learnings",
)

_USED_RE = re.compile(r"^\s*-\s*\[\[([^\]]+)\]\]\s*(?:[—–-]{1,2}\s*)?(.*)$")
_EVENT_RE = re.compile(r"\s*<!--\s*outcome-event:\s*([^\s;<>]+)\s*;\s*reported\s*-->\s*$")


class EpisodeError(Exception):
    pass


@dataclass
class KnowledgeUse:
    ref: str
    outcome: str
    reason: str = ""
    event_id: str | None = None
    failure_reason: str | None = None


@dataclass
class SkillUse(KnowledgeUse):
    """A reported skill outcome, not proof of invocation."""


@dataclass
class Episode:
    note: Note
    retrieved: list[str] = field(default_factory=list)
    used: list[KnowledgeUse] = field(default_factory=list)
    candidate_learnings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    skill_outcomes: list[SkillUse] = field(default_factory=list)
    recall_quality: str | None = None
    present_sections: set[str] = field(default_factory=set)
    parse_errors: list[str] = field(default_factory=list)


def _bullets(text: str) -> list[str]:
    return [re.sub(r"^\s*-\s*", "", l).strip() for l in text.splitlines() if l.strip().startswith("-")]


def _parse_use(line: str, *, skill: bool = False) -> KnowledgeUse | None:
    match = _USED_RE.match(line)
    if not match:
        return None
    rest = match[2].strip()
    marker = _EVENT_RE.search(rest)
    event_id = marker[1] if marker else None
    if marker:
        rest = rest[:marker.start()].strip()
    parsed = re.match(r"^([A-Za-z#][A-Za-z#-]*)(?:\s*[:—–]\s*|\s+-{1,2}\s*|\s+|$)(.*)$", rest)
    outcome = parsed[1] if parsed else ("" if rest or skill else "unclear")
    detail = parsed[2].strip() if parsed else rest
    reason = None
    reason_match = re.match(r"^reason=([A-Za-z_]+)(?:;\s*|$)", detail)
    if reason_match:
        reason, detail = reason_match[1], detail[reason_match.end():].strip()
    elif outcome == "failed":
        for value in FAILURE_REASONS:
            if detail == value or detail.startswith(value + ":"):
                reason, detail = value, detail[len(value):].lstrip(": ").strip()
                break
    cls = SkillUse if skill else KnowledgeUse
    return cls(match[1].strip(), outcome, detail, event_id, reason)


def parse_episode(note: Note) -> Episode:
    ep = Episode(note)
    ep.present_sections = {m[1].strip() for m in re.finditer(r"^##\s+(.+?)\s*$", note.body, re.M)}
    ep.recall_quality = note.meta.get("recall_quality")
    for line in section(note.body, "Knowledge retrieved").splitlines():
        m = re.search(r"\[\[([^\]]+)\]\]", line)
        if m:
            ep.retrieved.append(m.group(1).strip())
    for heading, skill in (("Knowledge used", False), ("Skill outcomes", True), ("Skills used", True)):
        for line in section(note.body, heading).splitlines():
            use = _parse_use(line, skill=skill)
            if use is not None:
                if "<!-- outcome-event:" in line and not _EVENT_RE.search(line):
                    ep.parse_errors.append(f"malformed outcome event marker in `## {heading}`")
                if isinstance(use, SkillUse):
                    ep.skill_outcomes.append(use)
                else:
                    ep.used.append(use)
            elif line.strip().startswith("-") and _meaningful(line):
                ep.parse_errors.append(f"invalid outcome bullet in `## {heading}`")
    ep.candidate_learnings = _bullets(section(note.body, "Candidate learnings"))
    ep.decisions = _bullets(section(note.body, "Decisions"))
    ep.problems = _bullets(section(note.body, "Problems"))
    return ep


def _meaningful(text: str) -> bool:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    placeholders = {"", "none", "(none)", "n/a", "not applicable", "-", "—"}
    return any(re.sub(r"^\s*-\s*", "", line).strip().casefold() not in placeholders for line in text.splitlines())


def _now(now: datetime | None) -> datetime:
    if now is not None and not isinstance(now, datetime):
        raise EpisodeError("episode time requires a datetime")
    dt = now or datetime.now().astimezone()
    return dt.astimezone() if dt.tzinfo is None else dt


def _clean_content(vault: Vault, meta: dict, body: str) -> tuple[dict, str, list[redact.Finding]]:
    if not isinstance(meta, dict) or not isinstance(body, str):
        raise EpisodeError("episode metadata must be a mapping and body must be text")
    findings: list[redact.Finding] = []

    def clean(value, key: str | None = None):
        if isinstance(value, str):
            prefix = f"{key} = " if key is not None else ""
            result, found = redact.redact(prefix + value, vault)
            findings.extend(found)
            return result[len(prefix):] if prefix and result.startswith(prefix) else result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if not isinstance(key, str) or redact.scan(key, vault):
                    raise EpisodeError("episode metadata keys must not contain sensitive information")
                result[key] = clean(item, key)
            return result
        if value is None or type(value) in (bool, int, float):
            return value
        raise EpisodeError("unsupported episode metadata value")

    clean_meta = clean(meta)
    clean_body = clean(body)
    if findings:
        clean_meta["sensitivity"] = "redacted"
    return clean_meta, clean_body, findings


def _load_episode(vault: Vault, path: Path) -> Note:
    try:
        resolved = fsutil.ensure_within(vault, path)
        if resolved != path or path.is_symlink() or not resolved.is_relative_to(vault.path(config.EPISODES)):
            raise EpisodeError("episode path must not redirect or leave the episode directory")
        if redact.scan(path.name, vault):
            raise EpisodeError("episode filename requires redaction before it can be written")
        note = load_note(resolved, vault)
    except (fsutil.PathTraversalError, OSError, RuntimeError):
        raise EpisodeError("episode path is unsafe or unreadable") from None
    if note.parse_error or note.type != "episode":
        raise EpisodeError("expected an episode with valid frontmatter")
    return note


def _session_state(vault: Vault, session_id: str) -> dict:
    from .recall import session_state_path

    path = session_state_path(vault, session_id)
    try:
        resolved = fsutil.ensure_within(vault, path)
        if resolved != path or path.is_symlink() or not resolved.is_relative_to(vault.path(config.SESSION_STATE)):
            raise EpisodeError("episode prefill requires controlled local session state")
        if not path.exists():
            return {}
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            raise EpisodeError("session state exceeds the bounded prefill limit")
        state = json.loads(path.read_text(encoding="utf-8"))
    except (fsutil.PathTraversalError, OSError, RuntimeError, ValueError):
        raise EpisodeError("session state is unsafe or malformed") from None
    if not isinstance(state, dict):
        raise EpisodeError("session state must be a mapping")
    return state


def _checkpoint_line(vault: Vault, text: str, stamp: str) -> str:
    if not isinstance(text, str):
        raise EpisodeError("checkpoint text must be text")
    clean, _ = redact.redact(text, vault)
    clean = " ".join(clean.split())
    return f"- [checkpoint {stamp}; observed capture] Reported context: {clean}" if clean else ""


def _render_outcome(event: OutcomeEvent) -> str:
    detail = event.detail.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    if event.reason:
        detail = f"reason={event.reason}" + (f"; {detail}" if detail else "")
    return (
        f"- [[{event.subject_id}]] — {event.outcome}"
        + (f" — {detail}" if detail else "")
        + f" <!-- outcome-event: {event.event_id}; reported -->"
    )


def create_stub(
    vault: Vault,
    tool: str,
    slug: str,
    session_ref: str = "",
    retrieved: list[str] | None = None,
    domains: list[str] | None = None,
    project: str | None = None,
    duration_min: int | None = None,
    trust: str = "first-party",
    now: datetime | None = None,
    session_id: str | None = None,
) -> Path:
    """Create a raw, partial scaffold from bounded state and reported events.

    ``session_ref`` is opaque text, never a transcript path to open. A supplied
    ``session_id`` enables controlled session-state and outcome-journal prefill.
    """
    from . import outcomes
    from .schema import TRUST

    dt = _now(now)
    date = dt.strftime("%Y-%m-%d")
    tool = require_text(tool, "tool", 100)
    slug = require_text(slug, "slug", 200)
    trust = require_text(trust, "trust", 100)
    if trust not in TRUST:
        raise EpisodeError("episode trust must use a supported trust value")
    if session_ref is None:
        session_ref = ""
    if not isinstance(session_ref, str):
        raise EpisodeError("session_ref must be text")
    if session_ref:
        session_ref = require_text(session_ref, "session_ref", 1000)
    if project is not None:
        if not isinstance(project, str):
            raise EpisodeError("project must be text")
        if project:
            project = require_text(project, "project", 1000)
    state: dict = {}
    events: list[OutcomeEvent] = []
    checkpoint_redacted = False
    if session_id is not None:
        require_id(session_id, "session_id")
        if redact.scan(session_id, vault):
            raise EpisodeError("session_id must not contain sensitive information")
        state = _session_state(vault, session_id)
        events = outcomes.read_events(vault, session_id=session_id)
    if retrieved is None:
        retrieved = state.get("retrieved", [])
    if not isinstance(retrieved, list) or any(not isinstance(ref, str) for ref in retrieved):
        raise EpisodeError("retrieved references must be a list of strings")
    for ref in retrieved:
        require_text(ref, "retrieved reference", 300)
    if domains is None:
        domains = state.get("domains") or ["unclassified"]
    if not isinstance(domains, list):
        raise EpisodeError("episode domains must be a list")
    for domain in domains:
        require_id(domain, "domain")
    meta: dict = {
        "type": "episode",
        "tool": tool,
        "domains": domains or ["unclassified"],
        "captured": dt.isoformat(timespec="seconds"),
        "trust": trust,
        "sensitivity": "checked",
        "status": "raw",
        "session_ref": session_ref or "none",
        "completeness": "partial",
    }
    if session_id is not None:
        meta["session_id"] = session_id
        attempts = state.get("recall_attempts", [])
        if not isinstance(attempts, list):
            raise EpisodeError("session recall_attempts must be a list")
        for attempt_id in attempts:
            require_id(attempt_id, "recall attempt ID")
        if attempts:
            meta["recall_attempts"] = list(dict.fromkeys(attempts))
    if project:
        meta["project"] = project
    if duration_min is not None:
        if type(duration_min) is not int or duration_min < 0:
            raise EpisodeError("duration_min must be a nonnegative integer")
        meta["duration_min"] = duration_min

    prefilled: dict = {}
    if retrieved:
        from_state = bool(session_id and retrieved == state.get("retrieved"))
        prefilled["knowledge_retrieved"] = {
            "source": "session-state/recall-log" if from_state else "provided-retrievals",
            "evidence": "observed-record" if from_state else "reported",
        }
    happened = []
    checkpoints = state.get("checkpoints", [])
    if not isinstance(checkpoints, list):
        raise EpisodeError("session checkpoints must be a list")
    for checkpoint_data in checkpoints:
        stamp = "time unavailable"
        if isinstance(checkpoint_data, dict):
            stamp_value = checkpoint_data.get("at")
            if stamp_value:
                try:
                    parse_timestamp(stamp_value)
                    stamp = stamp_value
                except VaultError:
                    pass
            text = checkpoint_data.get("text", "")
        else:
            text = checkpoint_data
        if isinstance(text, str) and redact.scan(text, vault):
            checkpoint_redacted = True
        line = _checkpoint_line(vault, text, stamp)
        if line:
            happened.append(line)
    if happened:
        prefilled["what_happened"] = {
            "source": "session-state/checkpoints", "evidence": "observed-capture; reported-content",
        }
    elif state.get("recalled") is True:
        state_refs = state.get("retrieved", [])
        if not isinstance(state_refs, list):
            raise EpisodeError("session retrieved references must be a list")
        happened.append(
            f"- [observed record; source: session-state] Session state records a recall with {len(state_refs)} knowledge references."
        )
        prefilled["what_happened"] = {"source": "session-state/recall", "evidence": "observed-record"}
    used = [event for event in events if event.subject_type == "knowledge"]
    skills = [event for event in events if event.subject_type == "skill"]
    quality = [event for event in events if event.subject_type == "recall"]
    if events:
        meta["outcome_events"] = [event.event_id for event in events]
    for name, values in (("knowledge_used", used), ("skill_outcomes", skills), ("recall_quality", quality)):
        if values:
            prefilled[name] = {"source": "outcome-journal", "evidence": "reported"}
    if quality:
        latest = quality[-1]
        meta["recall_quality"] = latest.outcome
        prefilled["recall_quality"]["event_id"] = latest.event_id
    if prefilled:
        meta["prefilled"] = prefilled
    retrieved_lines = "\n".join(f"- [[{ref}]]" for ref in dict.fromkeys(retrieved))
    body = "\n".join(
        [
            f"# Session: {slug}",
            "",
            "## Goal",
            "",
            "## What happened",
            "\n".join(happened),
            "",
            "## Decisions",
            "",
            "## Problems",
            "",
            "## Knowledge retrieved",
            retrieved_lines,
            "",
            "## Knowledge used",
            "\n".join(_render_outcome(event) for event in used),
            "",
            "## Skill outcomes",
            "\n".join(_render_outcome(event) for event in skills),
            "",
            "## Candidate learnings",
            "",
        ]
    )
    clean_slug, slug_findings = redact.redact(slug, vault)
    meta, body, _ = _clean_content(vault, meta, body)
    if slug_findings or checkpoint_redacted:
        meta["sensitivity"] = "redacted"
    meta["domains"] = [
        domain if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", domain) else "unclassified"
        for domain in meta["domains"]
    ]
    filename = f"{date}-{fsutil.safe_slug(meta['tool'], 20)}-{fsutil.safe_slug(clean_slug, 40)}.md"
    path = fsutil.unique_path(vault.path(config.EPISODES) / filename)
    return fsutil.agent_write(vault, path, frontmatter.compose(meta, body))


def checkpoint(vault: Vault, path: Path, text: str, now: datetime | None = None) -> None:
    """PreCompact: append a checkpoint bullet so long sessions lose nothing.
    Only valid while the episode is still raw."""
    note = _load_episode(vault, path)
    if note.status != "raw":
        raise EpisodeError("cannot checkpoint an episode that is not raw")
    stamp = _now(now).strftime("%H:%M")
    bullet = _checkpoint_line(vault, text, stamp)
    if not bullet:
        return
    lines = note.body.splitlines()
    out, inserted, in_wh = [], False, False
    for line in lines:
        if line.startswith("## What happened"):
            in_wh = True
        elif in_wh and line.startswith("## "):
            while out and not out[-1].strip():
                out.pop()  # keep exactly one blank line before the next heading
            out.append(bullet)
            out.append("")
            inserted = True
            in_wh = False
        out.append(line)
    if not inserted:
        if not in_wh:
            out.extend(["", "## What happened", ""])
        out.append(bullet)
    meta, body, _ = _clean_content(vault, note.meta, "\n".join(out))
    if redact.scan(text, vault):
        meta["sensitivity"] = "redacted"
    if not isinstance(meta.get("prefilled", {}), dict):
        raise EpisodeError("episode prefilled provenance must be a mapping")
    meta.setdefault("prefilled", {})["what_happened"] = {
        "source": "episode/checkpoints", "evidence": "observed-capture; reported-content",
    }
    fsutil.agent_write(vault, path, frontmatter.compose(meta, body))


def validate_summary(note: Note) -> list[str]:
    """Require useful available observations, not seven manufactured sections."""
    ep = parse_episode(note)
    problems = list(ep.parse_errors)
    meaningful = ("What happened", "Decisions", "Problems", "Knowledge used", "Candidate learnings", "Skill outcomes", "Skills used")
    if not any(_meaningful(section(note.body, name)) for name in meaningful) and not (
        ep.recall_quality is not None or note.meta.get("outcome_events")
    ):
        problems.append("episode has no available observations or feedback")
    if ep.recall_quality is not None and (
        not isinstance(ep.recall_quality, str) or ep.recall_quality not in SUBJECT_OUTCOMES["recall"]
    ):
        problems.append("invalid recall_quality")

    def reference_key(ref: str) -> str:
        if note.vault is not None:
            from .outcomes import canonical_subject_ref

            try:
                return canonical_subject_ref(note.vault, "knowledge", ref)
            except VaultError:
                pass
        return ref.replace("\\", "/").removesuffix(".md")

    retrieved = {reference_key(ref) for ref in ep.retrieved}
    for use in ep.used:
        if use.outcome not in ("held", "failed", "unclear", "not-applicable"):
            problems.append("invalid outcome in Knowledge used")
        if retrieved and reference_key(use.ref) not in retrieved and not use.event_id:
            problems.append(
                "a note appears under Knowledge used but not Knowledge retrieved — add it to both"
            )
    for use in ep.skill_outcomes:
        if use.outcome not in SUBJECT_OUTCOMES["skill"]:
            problems.append("invalid skill outcome")
    words = len(note.body.split())
    if words > config.EPISODE_WORD_BUDGET:
        problems.append(f"body is {words} words; target ≤ {config.EPISODE_WORD_BUDGET}")
    return problems


def finish(vault: Vault, path: Path, now: datetime | None = None) -> list[str]:
    """Finish a useful partial or complete episode; return budget warnings."""
    from .outcomes import episode_events

    note = _load_episode(vault, path)
    if note.status == "summarised":
        return []
    if note.status != "raw":
        raise EpisodeError("cannot finish an episode that is not raw")
    meta, clean_body, _ = _clean_content(vault, note.meta, note.body)
    clean_note = Note(note.path, meta, clean_body, vault)
    problems = validate_summary(clean_note)
    hard = [p for p in problems if not p.startswith("body is")]
    if hard:
        raise EpisodeError("episode not ready: " + "; ".join(hard))
    try:
        episode_events(vault, clean_note)
    except VaultError as exc:
        raise EpisodeError("episode feedback is invalid: " + str(exc)) from None
    meta["status"] = "summarised"
    ep = parse_episode(clean_note)
    meta["completeness"] = "complete" if (
        all(name in ep.present_sections for name in REQUIRED_SECTIONS)
        and _meaningful(section(clean_body, "Goal")) and _meaningful(section(clean_body, "What happened"))
    ) else "partial"
    fsutil.agent_write(vault, path, frontmatter.compose(meta, clean_body))
    return [p for p in problems if p.startswith("body is")]


def mark_mined(vault: Vault, path: Path, mined_refs: list[str]) -> None:
    """Curator-only transition summarised → mined. The single metadata change
    the curator may make to an episode (episode.md rule 5)."""
    note = _load_episode(vault, path)
    if note.status != "summarised":
        raise EpisodeError("cannot mine an episode that is not summarised")
    meta = dict(note.meta)
    meta["status"] = "mined"
    if mined_refs:
        meta["mined"] = mined_refs
    meta, body, _ = _clean_content(vault, meta, note.body)
    fsutil.curator_write(vault, path, frontmatter.compose(meta, body))


def redact_episode(vault: Vault, path: Path) -> list[redact.Finding]:
    """The one exception to append-only: redaction of an already-mined
    episode (issues.md I-012)."""
    note = _load_episode(vault, path)
    meta, clean, findings = _clean_content(vault, note.meta, note.body)
    if findings:
        fsutil.curator_write(vault, path, frontmatter.compose(meta, clean))
    return findings
