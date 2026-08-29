"""Option Verification Schema for RegTrust-RAG (Prompt 6).

Defines the contract for discrete option verification and structured verdict decision:
  - SubClaimVerification: Verification outcome for a single sub-assertion within an option
  - OptionVerificationItem: Tri-state verdict (SUPPORTED / CONTRADICTED / NOT_ENOUGH_EVIDENCE) per choice option
  - OptionVerificationResponse: Structured decision outcome, winner options, and trace
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VerdictType = Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"]


@dataclass(slots=True)
class SubClaimVerification:
    """Verification details for an individual sub-claim in an option."""
    sub_claim: str
    verdict: VerdictType
    score: float = 0.0
    similarity: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    supporting_text: str = ""
    contradiction_detail: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub_claim": self.sub_claim,
            "verdict": self.verdict,
            "score": round(self.score, 3),
            "similarity": round(self.similarity, 4),
            "evidence_ids": self.evidence_ids,
            "supporting_text": self.supporting_text,
            "contradiction_detail": self.contradiction_detail,
            "reason": self.reason,
        }

@dataclass(slots=True)
class OptionVerificationItem:
    """Tri-state verification result for an entire option (A, B, C, D)."""
    option: str  # "A", "B", "C", "D"
    claim: str
    verdict: VerdictType
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    max_similarity: float = 0.0
    source_match: float = 0.0
    entailment_support: float = 0.0
    relative_margin: float = 0.0
    contradiction_probability: float = 0.0
    ranking_score: float = 0.0
    sub_claims: list[SubClaimVerification] = field(default_factory=list)
    contradiction_detail: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "option": self.option,
            "claim": self.claim,
            "verdict": self.verdict,
            "evidence_ids": self.evidence_ids,
            "confidence": round(self.confidence, 4),
            "R_i": round(self.max_similarity, 4),
            "M_i": round(self.source_match, 4),
            "E_i": round(self.entailment_support, 4),
            "Delta_i": round(self.relative_margin, 4),
            "N_i": round(self.contradiction_probability, 4),
            "C_i": round(self.ranking_score, 4),
            "reason": self.reason,
        }
        if self.sub_claims:
            d["sub_claims"] = [sc.to_dict() for sc in self.sub_claims]
        if self.contradiction_detail:
            d["contradiction_detail"] = self.contradiction_detail
        return d


@dataclass(slots=True)
class OptionVerificationResponse:
    """Final decision outcome produced by OptionVerificationEngine."""
    status: Literal["SUCCESS", "CONFLICTING", "NO_DECISION", "FAILED"]
    choice_mode: Literal["SINGLE", "MULTI"]
    question_intent_target: Literal["CORRECT", "INCORRECT"]
    options_verification: list[OptionVerificationItem] = field(default_factory=list)
    selected_options: list[str] = field(default_factory=list)
    required_count: int = 1
    explanation: str = ""
    intermediate_verification: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "choice_mode": self.choice_mode,
            "question_intent_target": self.question_intent_target,
            "options_verification": [opt.to_dict() for opt in self.options_verification],
            "selected_options": self.selected_options,
            "required_count": self.required_count,
            "explanation": self.explanation,
            "intermediate_verification": self.intermediate_verification,
            "diagnostics": self.diagnostics,
        }
