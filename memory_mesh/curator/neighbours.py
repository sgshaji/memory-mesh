"""Deterministic lexical neighbour discovery (curator.md §2.4): domain index
links, keyword overlap, shared applies_to.tools. Top five. No embeddings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import config
from ..config import Vault
from ..indexes import load_index
from ..notes import Note, knowledge_notes

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have if in into is it its of on or "
    "that the their then there these this to was were when which with without not "
    "no do does did done you your we our they them so than too very can could "
    "should would may might must will just also only some any all each".split()
)


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9._-]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Neighbour:
    note: Note
    score: float
    similarity: float  # keyword Jaccard against title+observations


def find_neighbours(
    vault: Vault,
    claim_text: str,
    domains: list[str],
    tools: list[str],
    note_type: str | None = None,
    limit: int = 5,
) -> list[Neighbour]:
    claim_kw = keywords(claim_text)
    indexed_refs: set[str] = set()
    for d in domains:
        di = load_index(vault, d)
        if di:
            indexed_refs.update(e.ref.split("/")[-1] for _, e in di.all_entries())

    tools_l = {t.lower() for t in tools}
    results: list[Neighbour] = []
    for note in knowledge_notes(vault):
        if note.parse_error or note.type == "context-pack":
            continue
        text = note.title + " " + " ".join(fact for _, fact in note.observations())
        sim = jaccard(claim_kw, keywords(text))
        score = sim * 10
        if note.path.stem in indexed_refs:
            score += 1.5
        note_domains = set(note.meta.get("domains") or [])
        if note_domains & set(domains):
            score += 1.5
        ap = note.meta.get("applies_to") or {}
        note_tools = {str(t).lower() for t in (ap.get("tools") or [])}
        if tools_l & note_tools:
            score += 1.0
        if note_type and note.type == note_type:
            score += 0.5
        if score >= 1.0:
            results.append(Neighbour(note, score, sim))
    results.sort(key=lambda n: (-n.score, n.note.rel))
    return results[:limit]
