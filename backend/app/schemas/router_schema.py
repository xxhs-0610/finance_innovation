from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

RouterIntent = Literal[
    "DOMAIN_QA",
    "SYSTEM_META",
    "OUT_OF_SCOPE",
    "NEED_CLARIFICATION",
]

# Upgraded task types: 6 core business task types + legacy type aliases
DomainTaskType = Literal[
    "TABLE_LOOKUP",
    "TABLE_COMPARE",
    "TABLE_CALCULATION",
    "FACT_SINGLE_CHOICE",
    "FACT_MULTI_CHOICE",
    "DIRECT_FACT_QA",
    # Legacy aliases
    "REGULATION_FACT",
    "THRESHOLD_RULE",
    "BUSINESS_PROCESS",
    "INDICATOR_DEFINITION",
    "CROSS_DOCUMENT",
    "COMPLIANCE_JUDGMENT",
]

DomainQAType = DomainTaskType


@dataclass(slots=True)
class RouteDecision:
    """Standardized decision contract emitted by the Question Router."""

    intent: RouterIntent
    task_type: Optional[DomainTaskType] = None
    qa_type: Optional[DomainTaskType] = None
    need_retrieval: bool = False
    need_clarification: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.task_type is None and self.qa_type is not None:
            self.task_type = self.qa_type
        elif self.qa_type is None and self.task_type is not None:
            self.qa_type = self.task_type

    def to_dict(self) -> dict[str, Any]:
        chosen_task = self.task_type or self.qa_type
        return {
            "intent": self.intent,
            "task_type": chosen_task,
            "qa_type": chosen_task,
            "need_retrieval": self.need_retrieval,
            "need_clarification": self.need_clarification,
            "reason": self.reason,
        }


__all__ = [
    "RouterIntent",
    "DomainTaskType",
    "DomainQAType",
    "RouteDecision",
]

