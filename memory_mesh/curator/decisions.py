"""Decision model (curator.md §4).

CREATE and UPDATE are auto-commit grade. MERGE, SUPERSEDE and REJECT are
human-gated through the review file. HOLD is the non-destructive default —
including whenever no model is available to judge sameness (mandate §J)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

AUTO = ("CREATE", "UPDATE")
GATED = ("MERGE", "SUPERSEDE", "REJECT")


@dataclass
class Decision:
    kind: str  # CREATE | UPDATE | MERGE | SUPERSEDE | REJECT | HOLD
    rationale: str
    claim: str = ""
    source_ref: str = ""  # episode/inbox item that produced the claim
    target_ref: str = ""  # existing note acted on (UPDATE/MERGE/SUPERSEDE/REJECT)
    other_ref: str = ""  # second note for MERGE
    payload: dict = field(default_factory=dict)  # machine-applied details

    @property
    def auto(self) -> bool:
        return self.kind in AUTO

    @property
    def gated(self) -> bool:
        return self.kind in GATED

    def payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
