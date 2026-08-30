"""Multi-target Retrieval Schema for RegTrust-RAG.

Defines the data contract for multi-target query decomposition and targeted evidence retrieval:
  - TargetRetrievalTask: A specific unit of retrieval (candidate, operand, option claim)
  - TargetRetrievalResult: Status and evidence for a specific retrieval unit
  - MultiTargetRetrievalResponse: Aggregated response containing individual target results and merged evidence
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.schemas.chunk_schema import SearchResult
from app.schemas.task_plan_schema import TaskPlan


@dataclass(slots=True)
class TargetRetrievalTask:
    """A discrete retrieval task derived from a TaskPlan."""
    task_id: str
    target: str
    task_type: str = "DIRECT_FACT_QA"
    source_constraints: dict[str, Any] = field(default_factory=dict)
    sub_targets: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "target": self.target,
            "source_constraints": self.source_constraints,
        }
        if self.sub_targets:
            d["sub_targets"] = self.sub_targets
        if self.extra:
            d["extra"] = self.extra
        return d


@dataclass(slots=True)
class TargetRetrievalResult:
    """Retrieval outcome and supporting evidence for a single TargetRetrievalTask."""
    task_id: str
    target: str
    status: Literal["SUCCESS", "NO_EVIDENCE", "FAILED"] = "SUCCESS"
    evidence: list[SearchResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class MultiTargetRetrievalResponse:
    """Complete multi-target retrieval response container."""
    query: str
    task_type: str
    task_plan: TaskPlan | None = None
    retrieval_tasks: list[TargetRetrievalTask] = field(default_factory=list)
    retrieval_results: list[TargetRetrievalResult] = field(default_factory=list)
    merged_evidence: list[SearchResult] = field(default_factory=list)
    overall_status: str = "answerable"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "task_type": self.task_type,
            # Preserve the execution plan through serialization.  Module 4
            # relies on this plan to dispatch TABLE_LOOKUP/COMPARE/CALCULATION
            # to the deterministic table executor; dropping it silently
            # downgrades an otherwise answerable table task to DIRECT_QA.
            "task_plan": self.task_plan.to_dict() if self.task_plan else None,
            "retrieval_tasks": [t.to_dict() for t in self.retrieval_tasks],
            "retrieval_results": [r.to_dict() for r in self.retrieval_results],
            "merged_evidence": [e.to_dict() for e in self.merged_evidence],
            "overall_status": self.overall_status,
            "diagnostics": self.diagnostics,
        }
