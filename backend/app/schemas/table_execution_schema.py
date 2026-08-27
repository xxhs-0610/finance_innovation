"""Table Execution Schema for RegTrust-RAG.

Defines the contract for deterministic table lookup, compare, and calculation execution:
  - TableOperandResult: Extracted numeric value, unit, and verification status of a table cell/operand
  - TableExecutionResult: Deterministic calculation/comparison outcome, matched option, and trace
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class TableOperandResult:
    """Represents a single verified operand or candidate extracted from a table."""
    name: str
    value: float | None = None
    unit: str = ""
    verified: bool = False
    evidence_id: str = ""
    row_header: str = ""
    col_header: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "verified": self.verified,
            "evidence_id": self.evidence_id,
            "row_header": self.row_header,
            "col_header": self.col_header,
            "error": self.error,
        }


@dataclass(slots=True)
class TableExecutionResult:
    """Deterministic result of a TABLE_LOOKUP, TABLE_COMPARE, or TABLE_CALCULATION execution."""
    status: Literal["SUCCESS", "MISSING_OPERAND", "CALCULATION_ERROR", "FAILED"]
    task_type: str
    operation: str | None = None
    operands: list[TableOperandResult] = field(default_factory=list)
    result: float | str | None = None
    unit: str = ""
    matched_option: str | None = None
    explanation: str = ""
    intermediate_verification: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "task_type": self.task_type,
            "operation": self.operation,
            "operands": [op.to_dict() for op in self.operands],
            "result": self.result,
            "unit": self.unit,
            "matched_option": self.matched_option,
            "explanation": self.explanation,
            "intermediate_verification": self.intermediate_verification,
            "diagnostics": self.diagnostics,
        }
