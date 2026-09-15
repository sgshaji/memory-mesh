"""Optional human-managed feedback policy and routing vocabulary."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Mapping

from .config import SETTINGS_FILE, Vault, VaultError
from .frontmatter import FrontmatterError, parse


@dataclass(frozen=True)
class FeedbackPolicy:
    half_life_days: float = 90.0
    recent_days: int = 30
    behaviour_change_failures: int = 2
    unknown_context_weight: float = 0.5
    out_of_context_weight: float = 0.1
    future_tolerance_seconds: int = 300
    recall_target_minimum: int = 2
    inbox_review_days: int = 14
    skill_review_days: int = 90
    skill_failure_threshold: int = 2
    usage_promote_count: int = 5
    usage_demote_days: int = 180


@dataclass(frozen=True)
class CurationPolicy:
    mode: str = "single-user"
    curator: str = ""
    lock_timeout_seconds: float = 2.0


@dataclass(frozen=True)
class RoutingVocabulary:
    keywords: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    feedback: FeedbackPolicy = field(default_factory=FeedbackPolicy)
    curation: CurationPolicy = field(default_factory=CurationPolicy)
    routing: Mapping[str, RoutingVocabulary] = field(default_factory=dict)


def _mapping(value: object, field_name: str) -> dict:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise VaultError(f"{SETTINGS_FILE}: {field_name} must be a mapping")
    return value


def _known_keys(data: dict, allowed: set[str], name: str) -> None:
    unknown = data.keys() - allowed
    if unknown:
        raise VaultError(f"{SETTINGS_FILE}: unknown {name} fields: {', '.join(sorted(unknown))}")


def _number(value: object, name: str, *, integer: bool, minimum: float, maximum: float) -> None:
    valid_type = type(value) is int if integer else type(value) in (int, float)
    if not valid_type or not minimum <= value <= maximum or not math.isfinite(value):
        raise VaultError(f"{SETTINGS_FILE}: {name} must be {'an integer' if integer else 'a number'} between {minimum:g} and {maximum:g}")


def load_settings(vault: Vault) -> Settings:
    path = vault.path(SETTINGS_FILE)
    if path.is_symlink() or not path.resolve().is_relative_to(vault.root):
        raise VaultError(f"{SETTINGS_FILE}: configuration must be a regular file inside the vault")
    if not path.exists():
        return Settings()
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        raise VaultError(f"{SETTINGS_FILE}: configuration must be a file no larger than 128 KiB")
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise VaultError(f"{SETTINGS_FILE}: configuration requires YAML frontmatter")
        meta, _ = parse(text)
    except (FrontmatterError, UnicodeError, OSError) as exc:
        raise VaultError(f"{SETTINGS_FILE}: cannot read configuration: {exc}") from exc
    _known_keys(meta, {"type", "title", "version", "feedback", "curation", "routing"}, "configuration")
    if meta.get("type", "meta") != "meta" or type(meta.get("version", 1)) is not int or meta.get("version", 1) != 1:
        raise VaultError(f"{SETTINGS_FILE}: expected type meta and configuration version 1")
    feedback = _mapping(meta.get("feedback", {}), "feedback")
    _known_keys(feedback, {f.name for f in fields(FeedbackPolicy)}, "feedback")
    for name, value in feedback.items():
        if name in ("unknown_context_weight", "out_of_context_weight"):
            _number(value, name, integer=False, minimum=0, maximum=1)
        elif name == "half_life_days":
            _number(value, name, integer=False, minimum=1, maximum=36500)
        elif name == "recall_target_minimum":
            _number(value, name, integer=True, minimum=1, maximum=6)
        elif name == "future_tolerance_seconds":
            _number(value, name, integer=True, minimum=0, maximum=3600)
        else:
            _number(value, name, integer=True, minimum=1, maximum=36500)
    curation = _mapping(meta.get("curation", {}), "curation")
    _known_keys(curation, {f.name for f in fields(CurationPolicy)}, "curation")
    if curation.get("mode", "single-user") not in ("single-user", "designated"):
        raise VaultError(f"{SETTINGS_FILE}: curation.mode must be single-user or designated")
    curator = curation.get("curator", "")
    if not isinstance(curator, str) or len(curator) > 200 or any(ord(c) < 32 for c in curator):
        raise VaultError(f"{SETTINGS_FILE}: curation.curator must be a single-line identity")
    if curation.get("mode") == "designated" and not curator.strip():
        raise VaultError(f"{SETTINGS_FILE}: designated curation requires a curator identity")
    if "lock_timeout_seconds" in curation:
        _number(curation["lock_timeout_seconds"], "lock_timeout_seconds", integer=False, minimum=0.1, maximum=60)
    routing: dict[str, RoutingVocabulary] = {}
    for domain, raw in _mapping(meta.get("routing", {}), "routing").items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", domain):
            raise VaultError(f"{SETTINGS_FILE}: invalid routing domain: {domain}")
        vocab = _mapping(raw, f"routing.{domain}")
        _known_keys(vocab, {"keywords", "aliases", "concepts"}, f"routing.{domain}")
        converted: dict[str, tuple[str, ...]] = {}
        for key, values in vocab.items():
            if not isinstance(values, list) or len(values) > 64 or any(
                not isinstance(v, str) or not v.strip() or len(v) > 100
                or any(ord(c) < 32 for c in v) for v in values
            ):
                raise VaultError(f"{SETTINGS_FILE}: routing.{domain}.{key} must contain at most 64 single-line terms")
            converted[key] = tuple(dict.fromkeys(v.strip() for v in values))
        routing[domain] = RoutingVocabulary(**converted)
    return Settings(
        feedback=FeedbackPolicy(**feedback),
        curation=CurationPolicy(**curation),
        routing=MappingProxyType(routing),
    )
