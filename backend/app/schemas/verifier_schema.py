"""Schemas and contract for Evidence Verifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ReasonCode = Literal[
    "SUFFICIENT",
    "NO_RELEVANT_EVIDENCE",
    "INSUFFICIENT_COVERAGE",
    "MISSING_KEY_FACT",
    "AMBIGUOUS_QUERY",
    "CONFLICTING_EVIDENCE",
    "OUTDATED_OR_VERSION_UNCLEAR",
    "MISSING_NUMERIC_EVIDENCE",
    "MISSING_SCENARIO_CONDITION",
]

ALLOWED_REASON_CODES: frozenset[ReasonCode] = frozenset(
    {
        "SUFFICIENT",
        "NO_RELEVANT_EVIDENCE",
        "INSUFFICIENT_COVERAGE",
        "MISSING_KEY_FACT",
        "AMBIGUOUS_QUERY",
        "CONFLICTING_EVIDENCE",
        "OUTDATED_OR_VERSION_UNCLEAR",
        "MISSING_NUMERIC_EVIDENCE",
        "MISSING_SCENARIO_CONDITION",
    }
)


@dataclass(slots=True)
class EvidenceVerificationResult:
    """Standardized decision payload produced by Evidence Verifier."""

    answerable: bool
    evidence_sufficient: bool
    need_clarification: bool
    reason_code: ReasonCode
    reason: str
    supporting_evidence_ids: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answerable": self.answerable,
            "evidence_sufficient": self.evidence_sufficient,
            "need_clarification": self.need_clarification,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "missing_information": list(self.missing_information),
        }


__all__ = ["ReasonCode", "ALLOWED_REASON_CODES", "EvidenceVerificationResult"]
