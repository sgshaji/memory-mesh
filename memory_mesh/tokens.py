"""Conservative token estimation (issues.md I-008).

No tokenizer dependency in V1. The estimator deliberately over-counts
(~3.5 chars/token vs ~4 for real Markdown prose) so every budget check
fails safe: content judged inside budget here is inside budget for real.
"""

from __future__ import annotations

import math


def estimate(text: str) -> int:
    if not text:
        return 0
    chars = len(text)
    words = len(text.split())
    return math.ceil(max(chars / 3.5, words * 1.34))
