"""Redaction: secrets, customer/tenant specifics and internal URLs are
removed BEFORE content is admitted anywhere in the vault (P10, G1, G3).

Two layers:
  1. Built-in secret/PII patterns — always on, not configurable off.
  2. `_meta/redact.txt` — user rules, one per line:
       plain text            → case-insensitive literal, replaced by [customer]
       literal:Contoso       → same, explicit
       regex:<pattern>       → regex rule, replaced by [redacted]
       <rule> => [token]     → custom replacement token
     Lines starting with # are comments.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import config
from .config import Vault

_Rule = tuple[str, re.Pattern, str]
_rule_snapshot: ContextVar[tuple[Path, tuple[_Rule, ...]] | None] = ContextVar(
    "memory_mesh_redaction_snapshot", default=None,
)

# Built-in patterns. Order matters: most specific first.
_BUILTIN: list[tuple[str, re.Pattern, str]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.|\n)*?-----END [A-Z ]*PRIVATE KEY-----|-----BEGIN [A-Z ]*PRIVATE KEY-----[^\n]*"), "[redacted-secret]"),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[redacted-secret]"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[redacted-secret]"),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[redacted-secret]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[redacted-secret]"),
    ("connection-string", re.compile(r"(?i)\b(?:AccountKey|SharedAccessKey|SharedAccessSignature|sig)=[A-Za-z0-9%+/=]{16,}"), "[redacted-secret]"),
    ("assignment-secret", re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|client[_-]?secret)\b(\s*[:=]\s*)(?!\[)(\"[^\"]{4,}\"|'[^']{4,}'|[^\s,;]{6,})"), None),  # keeps the key name, redacts the value
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "[redacted-secret]"),
    ("azure-sas-url", re.compile(r"https?://[^\s]*\?[^\s]*sig=[^\s]+"), "[internal-url]"),
    ("tenant-id", re.compile(r"(?i)\btenant(?:[ _-]?id)?\s*[:=#]?\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[tenant]"),
    ("sharepoint-url", re.compile(r"https?://[A-Za-z0-9-]+\.sharepoint\.com/[^\s)\]]*"), "[internal-url]"),
    ("internal-host-url", re.compile(r"https?://[A-Za-z0-9.-]*\b(?:internal|corp|intranet)\b[A-Za-z0-9.-]*/[^\s)\]]*"), "[internal-url]"),
    ("email-personal", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!(?:example|invalid|test)\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
]

_INJECTION_MARKERS = (
    "ignore your instructions",
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard your instructions",
    "mark this validated",
    "mark this as validated",
    "set status: validated",
    "set status to validated",
    "delete note",
    "delete the note",
    "delete knowledge",
    "run this command",
    "execute this command",
    "you are now",
    "system prompt",
)


@dataclass
class Finding:
    rule: str
    replacement: str
    count: int


def _load_user_rules(vault: Vault) -> list[tuple[str, re.Pattern, str]]:
    snapshot = _rule_snapshot.get()
    if snapshot is not None and snapshot[0] == vault.root:
        return list(snapshot[1])
    rules: list[tuple[str, re.Pattern, str]] = []
    path = vault.path(config.REDACT_FILE)
    if not path.exists():
        return rules
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        replacement = "[customer]"
        if "=>" in line:
            line, _, repl = line.rpartition("=>")
            line, replacement = line.strip(), repl.strip()
        if line.startswith("regex:"):
            pat_src, kind, default_repl = line[6:].strip(), "user-regex", "[redacted]"
        elif line.startswith("literal:"):
            pat_src, kind, default_repl = re.escape(line[8:].strip()), "user-literal", "[customer]"
        else:
            pat_src, kind, default_repl = re.escape(line), "user-literal", "[customer]"
        if replacement == "[customer]" and default_repl != "[customer]":
            replacement = default_repl
        try:
            rules.append((kind, re.compile(pat_src, re.IGNORECASE), replacement))
        except re.error:
            continue  # a broken user rule must not break capture; lint reports it
    return rules


@contextmanager
def redaction_snapshot(vault: Vault) -> Iterator[None]:
    """Pin rules for one read operation, never as a process-wide or TTL cache."""
    current = _rule_snapshot.get()
    if current is not None and current[0] == vault.root:
        yield
        return
    rules = tuple(_load_user_rules(vault))
    token = _rule_snapshot.set((vault.root, rules))
    try:
        yield
    finally:
        _rule_snapshot.reset(token)


def lint_user_rules(vault: Vault) -> list[str]:
    """Report unparseable rules in _meta/redact.txt."""
    problems = []
    path = vault.path(config.REDACT_FILE)
    if not path.exists():
        return problems
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            line = line.rpartition("=>")[0].strip()
        src = line[6:] if line.startswith("regex:") else re.escape(line.removeprefix("literal:"))
        try:
            re.compile(src, re.IGNORECASE)
        except re.error as e:
            problems.append(f"{config.REDACT_FILE}:{n}: bad rule ({e})")
    return problems


def redact(text: str, vault: Vault | None = None) -> tuple[str, list[Finding]]:
    """Return (clean_text, findings). Built-ins always run; user rules run
    when a vault is given. Idempotent: replacement tokens never re-match."""
    findings: list[Finding] = []
    rules = list(_BUILTIN)
    if vault is not None:
        rules += _load_user_rules(vault)
    for name, pattern, replacement in rules:
        if replacement is None:  # assignment-secret keeps the key, drops the value
            text, n = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}[redacted-secret]", text)
        else:
            text, n = pattern.subn(replacement, text)
        if n:
            findings.append(Finding(name, replacement or "[redacted-secret]", n))
    return text, findings


def scan(text: str, vault: Vault | None = None) -> list[Finding]:
    _, findings = redact(text, vault)
    return findings


def injection_markers(text: str) -> list[str]:
    """Instruction-like strings inside content. They are DATA: the caller
    logs them and continues; nothing ever executes them (curator.md §9)."""
    low = text.lower()
    return [m for m in _INJECTION_MARKERS if m in low]
