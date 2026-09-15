"""Domain router: parse knowledge/_index/_domains.md and match a task to at
most two domains (domain-index.md, session-lifecycle.md L2/R1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config, tokens
from .config import Vault, VaultError
from .feedback_config import load_settings


@dataclass
class Domain:
    name: str
    scope: str
    keywords: list[str]
    aliases: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DomainMatch:
    domain: str
    score: int
    terms: tuple[str, ...]


_ROW_RE = re.compile(r"^\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$")
_DOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")


def load_domains(vault: Vault) -> list[Domain]:
    """Read the registry and merge optional, human-maintained vocabulary.

    Descriptive scopes are not routing terms. Configuration cannot declare a
    new domain or silently repair a malformed registry.
    """
    settings = load_settings(vault)
    path = vault.path(config.ROUTER)
    if path.is_symlink() or not path.resolve().is_relative_to(vault.root):
        raise VaultError(f"{config.ROUTER}: router must be a regular file inside the vault")
    try:
        if path.exists() and (not path.is_file() or path.stat().st_size > 128 * 1024):
            raise VaultError(f"{config.ROUTER}: router exceeds the 128 KiB file limit")
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except (OSError, UnicodeError) as exc:
        raise VaultError(f"{config.ROUTER}: cannot read router") from exc
    domains: list[Domain] = []
    names: set[str] = set()
    for number, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            continue
        m = _ROW_RE.match(line.strip())
        if not m:
            raise VaultError(f"{config.ROUTER}:{number}: expected domain, scope and match columns")
        name = m.group(1).strip()
        if name.lower() == "domain" or (name and set(name) <= {"-", " ", ":"}):
            continue
        if not _DOMAIN_RE.fullmatch(name) or name in names:
            raise VaultError(f"{config.ROUTER}:{number}: invalid or duplicate domain")
        names.add(name)
        scope = m.group(2).strip()
        keywords = [k.strip().lower() for k in m.group(3).split(",") if k.strip()]
        overlay = settings.routing.get(name)
        domains.append(Domain(
            name, scope,
            list(dict.fromkeys(keywords + (list(overlay.keywords) if overlay else []))),
            list(overlay.aliases) if overlay else [],
            list(overlay.concepts) if overlay else [],
        ))
    unknown = settings.routing.keys() - names
    if unknown:
        raise VaultError(
            f"{config.SETTINGS_FILE}: routing domains not declared in {config.ROUTER}: "
            + ", ".join(sorted(unknown))
        )
    return domains


def router_token_estimate(vault: Vault) -> int:
    path = vault.path(config.ROUTER)
    return tokens.estimate(path.read_text(encoding="utf-8")) if path.exists() else 0


def _normalise(text: str) -> str:
    # hyphen/space equivalence so `claude-code` matches keyword `claude code`
    return " ".join(text.lower().replace("-", " ").split())


def _keyword_hits(text_lower: str, keyword: str) -> int:
    # word-boundary match so `mcs` does not fire inside `mcssomething`
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(_normalise(keyword))}(?![a-z0-9])", text_lower))


def match(task_text: str, domains: list[Domain], limit: int = 2) -> list[str]:
    """Score domains by keyword hits (domain name counts too). Returns up to
    `limit` matching domain names, best first; empty when nothing matches."""
    return [item.domain for item in match_evidence(task_text, domains)[:max(0, limit)]]


def match_evidence(task_text: str, domains: list[Domain]) -> list[DomainMatch]:
    """The same deterministic matcher, with inspectable terms for diagnostics."""
    low = _normalise(task_text)
    scored: list[DomainMatch] = []
    for d in domains:
        vocabulary = dict.fromkeys(
            _normalise(term) for term in (*d.keywords, *d.aliases, *d.concepts) if term.strip()
        )
        hits = {term: _keyword_hits(low, term) for term in vocabulary}
        score = sum(hits.values())
        name_hits = _keyword_hits(low, d.name)
        score += 2 * name_hits
        if name_hits:
            hits[_normalise(d.name)] = name_hits
        if score > 0:
            scored.append(DomainMatch(
                d.name, score, tuple(sorted(term for term, count in hits.items() if count))
            ))
    return sorted(scored, key=lambda item: (-item.score, item.domain))
