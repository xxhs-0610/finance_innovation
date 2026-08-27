"""Intermediate Evidence Verification Schema for RegTrust-RAG (Prompt 8).

Defines the contract for intermediate evidence verification across:
  - TABLE_COMPARE (Verifies candidate A, B, C, D values prior to programmatic comparison)
  - TABLE_CALCULATION (Verifies Operand1, Operand2 values prior to calculation)
  - TABLE_LOOKUP (Verifies multi-coordinate extraction)
  - FACT_SINGLE_CHOICE / FACT_MULTI_CHOICE (Verifies discrete option grounding)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TargetStatusType = Literal["VERIFIED", "MISSING", "CONFLICTING", "UNVERIFIED"]


@dataclass(slots=True)
class IntermediateTargetItem:
    """Detailed intermediate verification record for an individual target/operand/option."""
    name: str
    target_type: Literal["CANDIDATE", "OPERAND", "TABLE_CELL", "OPTION", "SUB_CLAIM"]
    status: TargetStatusType
    value: Any | None = None
    unit: str = ""
    evidence_id: str = ""
    source_title: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_type": self.target_type,
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "evidence_id": self.evidence_id,
            "source_title": self.source_title,
            "reason": self.reason,
        }


@dataclass(slots=True)
class IntermediateVerificationResult:
    """Unified Intermediate Evidence Verification Outcome."""
    task_complete: bool
    can_execute: bool
    verified_targets: list[str] = field(default_factory=list)
    missing_targets: list[str] = field(default_factory=list)
    conflicting_targets: list[str] = field(default_factory=list)
    error_code: str | None = None  # "MISSING_OPERAND" | "INSUFFICIENT_EVIDENCE" | "CONFLICTING_TARGETS"
    explanation: str = ""
    details: list[IntermediateTargetItem] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Produce the standardized Prompt 8 dictionary structure."""
        return {
            "task_complete": self.task_complete,
            "missing_targets": self.missing_targets,
            "conflicting_targets": self.conflicting_targets,
            "verified_targets": self.verified_targets,
            "can_execute": self.can_execute,
            "error_code": self.error_code,
            "explanation": self.explanation,
            "details": [item.to_dict() for item in self.details],
            "diagnostics": self.diagnostics,
        }
