"""/learn — deliberate capture into 00-inbox/ (session-lifecycle.md L5).

One call, no prompts, no network: insight → safely stored candidate in
well under 15 seconds (Q1). Redaction runs BEFORE anything is written (G1).
Never touches canonical knowledge (P4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, frontmatter, fsutil, redact, router
from .config import Vault
from .notes import iter_notes

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
        if note.meta.get("content_hash") == content_hash and "processed" not in note.meta:
            return note.path
    return None


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
) -> CaptureResult:
    semantic_text = hash_input or "\n".join(f"{kind}: {text}" for kind, text in observations)
    chash = _content_hash(semantic_text)
    existing = _existing_candidate(vault, chash)
    if existing is not None:
        return CaptureResult(existing, created=False, redacted=bool(findings), findings=findings)

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
) -> CaptureResult:
    if not text or not text.strip():
        raise ValueError("nothing to capture")

    # Redact before persistence — the raw text never touches disk (G1).
    clean, findings = redact.redact(text, vault)
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
    )


def learn_structured(
    vault: Vault,
    data: dict[str, Any],
    source_tool: str = "cli",
    now: datetime | None = None,
) -> CaptureResult:
    """Validate an agent-authored learning before admitting it to the inbox."""
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
    findings = list(title_findings)
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
    )
