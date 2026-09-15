"""/learn — deliberate capture into 00-inbox/ (session-lifecycle.md L5).

One call, no prompts, no network: insight → safely stored candidate in
well under 15 seconds (Q1). Redaction runs BEFORE anything is written (G1).
Never touches canonical knowledge (P4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, frontmatter, fsutil, redact, router
from .config import Vault, VaultError
from .notes import WIKILINK_RE, iter_notes, load_note

STRUCTURED_KINDS = (
    "scenario",
    "behaviour",
    "procedure",
    "fix",
    "workaround",
    "limitation",
    "reason",
    "outcome",
    "evidence",
)
_ACTIONABLE_KINDS = {"behaviour", "procedure", "fix", "workaround", "limitation"}
_VERIFICATION_KINDS = {"outcome", "evidence"}
_STRUCTURED_FIELDS = {"title", "observations", "domain", "project", "trust"}


@dataclass
class CaptureResult:
    path: Path
    created: bool  # False when an identical candidate already existed
    redacted: bool
    findings: list[redact.Finding]
    updated: bool = False  # Existing candidate's attention/linkage metadata changed.
    warnings: list[str] = field(default_factory=list)


def _content_hash(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _now_iso(now: datetime | None) -> str:
    dt = now or datetime.now().astimezone()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def _existing_candidate(vault: Vault, content_hash: str) -> Path | None:
    for note in iter_notes(vault, config.INBOX):
        if note.type != "gap" and note.meta.get("content_hash") == content_hash and "processed" not in note.meta:
            return note.path
    return None


def _normalise_episode_ref(value: str) -> str:
    if not value.strip() or len(value.splitlines()) != 1 or any(ord(char) < 32 for char in value):
        raise ValueError("source_episode must be a non-empty single line episode reference")
    ref = value.strip()
    if match := WIKILINK_RE.fullmatch(ref):
        ref = match.group(1).strip()
    elif ref.startswith("[["):
        raise ValueError("source_episode contains a malformed episode link")
    ref = ref.replace("\\", "/")
    if ref.endswith(".md"):
        ref = ref[:-3]
    if ":" in ref or any(part in ("", ".", "..") for part in ref.split("/")):
        raise ValueError("source_episode must be a local reference under episodes/")
    if "/" not in ref:
        ref = f"{config.EPISODES}/{ref}"
    if not ref.startswith(config.EPISODES + "/"):
        raise ValueError("source_episode must be a local reference under episodes/")
    return ref


def _capture_options(
    vault: Vault, signal: str, source_episode: str | None,
) -> tuple[str | None, list[redact.Finding]]:
    if not isinstance(signal, str) or signal not in ("high", "normal", "low"):
        raise ValueError("signal must be high, normal or low")
    if source_episode is None:
        return None, []
    if not isinstance(source_episode, str):
        raise ValueError("source_episode must be an episode reference")
    clean, findings = redact.redact(_normalise_episode_ref(source_episode), vault)
    reference = _normalise_episode_ref(clean)
    path = fsutil.checked_regular_path(vault, vault.path(reference + ".md"))
    if path.exists():
        note = load_note(path, vault)
        if note.parse_error or note.type != "episode":
            raise ValueError("source_episode must reference an episode, not another record type")
    return reference, findings


def _update_duplicate(
    vault: Vault, path: Path, signal: str, source_episode: str | None,
    findings: list[redact.Finding],
) -> CaptureResult:
    result = CaptureResult(path, created=False, redacted=bool(findings), findings=findings)
    if signal != "high" and source_episode is None:
        return result
    note = load_note(path, vault)
    if note.parse_error or note.type != "candidate" or "processed" in note.meta:
        raise VaultError("duplicate candidate changed after lookup; retry capture before updating metadata")
    meta = dict(note.meta)
    if signal == "high":
        old_signal = meta.get("signal", "normal")
        if not isinstance(old_signal, str) or old_signal not in ("high", "normal", "low"):
            raise ValueError("existing candidate has an invalid signal; repair it before upgrading attention")
        meta["signal"] = "high"
    if source_episode is not None:
        original_source = meta.get("source_episode")
        if original_source is None:
            meta["source_episode"] = source_episode
            if findings:
                meta["sensitivity"] = "redacted"
        else:
            try:
                same_source = isinstance(original_source, str) and _normalise_episode_ref(original_source) == source_episode
            except ValueError:
                same_source = False
            if not same_source:
                result.warnings.append(
                    "duplicate retains its original source_episode; link this candidate from "
                    "the additional episode's Candidate learnings section to record recurrence"
                )
    if meta != note.meta:
        fsutil.agent_write(vault, path, frontmatter.compose(meta, note.body))
        result.updated = True
    return result


def _write_candidate(
    vault: Vault,
    *,
    title: str,
    observations: list[tuple[str, str]],
    source_tool: str,
    source_prefix: str,
    domains: list[str],
    project: str | None,
    trust: str,
    findings: list[redact.Finding],
    now: datetime | None,
    hash_input: str | None = None,
    signal: str = "normal",
    source_episode: str | None = None,
) -> CaptureResult:
    semantic_text = hash_input or "\n".join(f"{kind}: {text}" for kind, text in observations)
    chash = _content_hash(semantic_text)
    existing = _existing_candidate(vault, chash)
    if existing is not None:
        return _update_duplicate(vault, existing, signal, source_episode, findings)

    dt = now or datetime.now().astimezone()
    date = dt.strftime("%Y-%m-%d")
    slug = fsutil.safe_slug(title, 48)
    filename = f"{date}-{fsutil.safe_slug(source_tool, 20)}-{slug}.md"
    path = fsutil.unique_path(vault.path(config.INBOX) / filename)
    meta: dict = {
        "type": "candidate",
        "title": title[:120],
        "source": f"{source_prefix} via {source_tool}, {date}",
        "captured": _now_iso(now),
        "domains": domains,
        "trust": trust if trust in ("first-party", "mixed", "third-party", "unknown") else "unknown",
        "sensitivity": "redacted" if findings else "checked",
        "content_hash": chash,
    }
    if project:
        meta["project"] = project
    if signal != "normal":
        meta["signal"] = signal
    if source_episode is not None:
        meta["source_episode"] = source_episode
    body = "## Observations\n" + "\n".join(f"- [{kind}] {text}" for kind, text in observations)
    written = fsutil.agent_write(vault, path, frontmatter.compose(meta, body))
    return CaptureResult(written, created=True, redacted=bool(findings), findings=findings)


def learn(
    vault: Vault,
    text: str,
    source_tool: str = "cli",
    domain: str | None = None,
    project: str | None = None,
    trust: str = "first-party",
    now: datetime | None = None,
    *,
    signal: str = "normal",
    source_episode: str | None = None,
) -> CaptureResult:
    """Capture an observation; signal changes attention, never truth or trust.

    Duplicate captures keep their identity and original content. Only explicit
    high upgrades their signal; normal/low never overwrite existing attention.
    The first source episode is retained. Additional episodes should link the
    candidate in Candidate learnings; conflicting source requests warn.
    Episode references may be vault-relative, bare slugs or wikilinks.
    """
    from .experience import get_mode

    if get_mode(vault) != "legacy":
        raise VaultError("this profile requires reviewed V2 proposals; legacy capture is disabled")
    if not text or not text.strip():
        raise ValueError("nothing to capture")
    clean_episode, option_findings = _capture_options(vault, signal, source_episode)

    # Redact before persistence — the raw text never touches disk (G1).
    clean, findings = redact.redact(text, vault)
    findings.extend(option_findings)
    clean_project = project
    if project:
        if "\n" in project or "\r" in project:
            raise ValueError("project must be a single line")
        clean_project, project_findings = redact.redact(project, vault)
        findings.extend(project_findings)
    title = clean.strip().splitlines()[0][:120]
    observations = [
        ("observation", line.strip())
        for line in clean.strip().splitlines()
        if line.strip()
    ]
    return _write_candidate(
        vault,
        title=title,
        observations=observations,
        source_tool=source_tool,
        source_prefix="/learn",
        domains=[domain] if domain else [],
        project=clean_project,
        trust=trust,
        findings=findings,
        now=now,
        hash_input=clean,
        signal=signal,
        source_episode=clean_episode,
    )


def learn_structured(
    vault: Vault,
    data: dict[str, Any],
    source_tool: str = "cli",
    now: datetime | None = None,
    *,
    signal: str = "normal",
    source_episode: str | None = None,
) -> CaptureResult:
    """Validate structured learning; attention/linkage keywords follow learn().

    Signal and source_episode are capture options, not observation payload
    fields. Neither participates in the content hash or V2 admission.
    """
    from .experience import get_mode

    if get_mode(vault) != "legacy":
        raise VaultError("this profile requires reviewed V2 proposals; legacy capture is disabled")
    clean_episode, option_findings = _capture_options(vault, signal, source_episode)
    unknown = sorted(set(data) - _STRUCTURED_FIELDS)
    if unknown:
        raise ValueError(f"unknown structured learning fields: {', '.join(unknown)}")

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("structured learning requires a non-empty `title`")
    if "\n" in title or "\r" in title:
        raise ValueError("structured learning `title` must be a single line")
    if len(title.strip()) > 120:
        raise ValueError("structured learning `title` exceeds 120 characters")

    raw_observations = data.get("observations")
    if not isinstance(raw_observations, list) or not 2 <= len(raw_observations) <= 9:
        raise ValueError("structured learning requires 2-9 `observations`")

    observations: list[tuple[str, str]] = []
    for index, item in enumerate(raw_observations):
        if not isinstance(item, dict) or set(item) != {"kind", "text"}:
            raise ValueError(f"observation {index + 1} must contain only `kind` and `text`")
        kind = item.get("kind")
        text = item.get("text")
        if kind not in STRUCTURED_KINDS:
            raise ValueError(f"observation {index + 1} has invalid kind `{kind}`")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"observation {index + 1} requires non-empty text")
        if "\n" in text or "\r" in text:
            raise ValueError(f"observation {index + 1} text must be a single line")
        if len(text.strip()) > 500:
            raise ValueError(f"observation {index + 1} exceeds 500 characters")
        observations.append((kind, text.strip()))

    kinds = {kind for kind, _ in observations}
    if not kinds.intersection(_ACTIONABLE_KINDS):
        raise ValueError("structured learning needs an actionable behaviour, procedure, fix, workaround, or limitation")
    if not kinds.intersection(_VERIFICATION_KINDS):
        raise ValueError("structured learning needs an observed outcome or reproducible evidence")

    trust = data.get("trust", "first-party")
    if trust not in ("first-party", "mixed", "third-party", "unknown"):
        raise ValueError(f"invalid structured learning trust `{trust}`")
    project = data.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        raise ValueError("structured learning `project` must be a non-empty string")
    if isinstance(project, str) and ("\n" in project or "\r" in project):
        raise ValueError("structured learning `project` must be a single line")

    domain = data.get("domain")
    declared = {item.name for item in router.load_domains(vault)}
    if domain is not None:
        if not isinstance(domain, str) or domain not in declared:
            raise ValueError(f"structured learning domain `{domain}` is not declared")
        domains = [domain]
    else:
        matched = router.match(
            "\n".join([title, *(text for _, text in observations)]),
            router.load_domains(vault),
            limit=1,
        )
        domains = matched or ["unclassified"]

    clean_title, title_findings = redact.redact(title.strip(), vault)
    clean_observations: list[tuple[str, str]] = []
    findings = [*title_findings, *option_findings]
    for kind, text in observations:
        clean, item_findings = redact.redact(text, vault)
        clean_observations.append((kind, clean))
        findings.extend(item_findings)
    clean_project = None
    if isinstance(project, str):
        clean_project, project_findings = redact.redact(project.strip(), vault)
        findings.extend(project_findings)

    return _write_candidate(
        vault,
        title=clean_title,
        observations=clean_observations,
        source_tool=source_tool,
        source_prefix="automatic capture",
        domains=domains,
        project=clean_project,
        trust=trust,
        findings=findings,
        now=now,
        signal=signal,
        source_episode=clean_episode,
    )
