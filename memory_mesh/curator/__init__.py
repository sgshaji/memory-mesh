"""The curator: two layers (mandate §J).

Layer 1 — deterministic engine (`engine`, `neighbours`, `review`): schema
validation, redaction, lifecycle, lexical retrieval, hashing, idempotence,
tallying, thresholds, diffs, packs, index hygiene. No network, ever (G7).

Layer 2 — reasoning adapter (`adapter`): optional model judgement behind an
interface. V1 works with the NullAdapter: no model means candidates HOLD and
reviews are proposed — never hallucinated confidence.
"""
