"""Domain router: parse knowledge/_index/_domains.md and match a task to at
most two domains (domain-index.md, session-lifecycle.md L2/R1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config, tokens
from .config import Vault


@dataclass
class Domain:
    name: str
    scope: str
    keywords: list[str]


_ROW_RE = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|\s*$")


def load_domains(vault: Vault) -> list[Domain]:
    path = vault.path(config.ROUTER)
    if not path.exists():
        return []
    domains: list[Domain] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        name = m.group(1).strip()
        if name in ("domain", "") or set(name) <= {"-", " ", ":"}:
            continue
        scope = m.group(2).strip()
        keywords = [k.strip().lower() for k in m.group(3).split(",") if k.strip()]
        domains.append(Domain(name, scope, keywords))
    return domains


def router_token_estimate(vault: Vault) -> int:
    path = vault.path(config.ROUTER)
    return tokens.estimate(path.read_text(encoding="utf-8")) if path.exists() else 0


def _normalise(text: str) -> str:
    # hyphen/space equivalence so `claude-code` matches keyword `claude code`
    return text.lower().replace("-", " ")


def _keyword_hits(text_lower: str, keyword: str) -> int:
    # word-boundary match so `mcs` does not fire inside `mcssomething`
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(_normalise(keyword))}(?![a-z0-9])", text_lower))


def match(task_text: str, domains: list[Domain], limit: int = 2) -> list[str]:
    """Score domains by keyword hits (domain name counts too). Returns up to
    `limit` matching domain names, best first; empty when nothing matches."""
    low = _normalise(task_text)
    scored: list[tuple[int, str]] = []
    for d in domains:
        score = sum(_keyword_hits(low, kw) for kw in d.keywords)
        score += 2 * _keyword_hits(low, d.name)
        if score > 0:
            scored.append((score, d.name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [name for _, name in scored[:limit]]
