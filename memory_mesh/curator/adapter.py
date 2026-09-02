"""Reasoning adapter interface (mandate §J layer 2).

Every method may return None, meaning "no judgement available". The engine
then falls back to deterministic behaviour: HOLD, or a review-file proposal.
The NullAdapter is the V1 default — the system MUST work without any model,
and nothing here may make a network call during a curator run (G7)."""

from __future__ import annotations

from typing import Protocol


class ReasoningAdapter(Protocol):
    def extract_claims(self, episode_body: str) -> list[str] | None:
        """Additional claim extraction beyond the deterministic bullets."""
        ...

    def classify(self, claim: str) -> dict | None:
        """Optional {type, domains} judgement for an ambiguous claim."""
        ...

    def same_claim(self, claim: str, note_text: str) -> bool | None:
        """Semantic 'is this the same claim?' — None when unsure."""
        ...

    def merge_wording(self, text_a: str, text_b: str) -> str | None:
        """Proposed merged body for a MERGE review draft."""
        ...


class NullAdapter:
    """No model configured. Everything defers to deterministic rules."""

    def extract_claims(self, episode_body: str) -> list[str] | None:
        return None

    def classify(self, claim: str) -> dict | None:
        return None

    def same_claim(self, claim: str, note_text: str) -> bool | None:
        return None

    def merge_wording(self, text_a: str, text_b: str) -> str | None:
        return None
